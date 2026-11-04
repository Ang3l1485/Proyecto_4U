package com.example.myapplication.ui.navegacion

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.camera.Calidad
import com.example.myapplication.camera.evaluarCalidad
import com.example.myapplication.data.local.GrafoDeLaApp
import com.example.myapplication.data.remote.AlertasPublicas
import com.example.myapplication.data.remote.CacheAlertasPublicas
import com.example.myapplication.data.remote.RemoteFrameRepository
import com.example.myapplication.data.repository.LocalizacionFrameRepository
import com.example.myapplication.domain.guia.FalloFrame
import com.example.myapplication.domain.guia.GuiaNavegacion
import com.example.myapplication.domain.guia.ParametrosGuia
import com.example.myapplication.domain.guia.PruebaGuia
import com.example.myapplication.domain.guia.SalidaGuia
import com.example.myapplication.domain.guia.SimuladorPasos
import com.example.myapplication.domain.guia.AlertasEnRuta
import com.example.myapplication.domain.guia.TextosGuia
import com.example.myapplication.domain.guia.TrazadoRuta
import com.example.myapplication.domain.guia.ColaVoz
import com.example.myapplication.domain.model.ResultadoFrame
import com.example.myapplication.domain.model.SesionDeNavegacion
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import com.example.myapplication.domain.ruta.Ruta
import com.example.myapplication.domain.usecase.DescribirUbicacion
import com.example.myapplication.logs.AppLog
import com.example.myapplication.map.TextosRutaMapa
import com.example.myapplication.sensors.PdrEstado
import com.example.myapplication.ui.inicio.VoiceController
import com.example.myapplication.ui.ubicacion.FeedbackCaptura
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.File
import kotlin.math.roundToInt

private const val TAG = "Guia"

/**
 * Cerebro de la vista 6.5 (Navegación guiada, FE-5.3). Une la guía pura ([GuiaNavegacion]) con Android: la voz
 * ([VoiceController] a través de [ColaVoz]), las fotos de corrección ([RemoteFrameRepository] y `CalidadImagen`) y el
 * PDR (la pantalla le pasa cada [PdrEstado]) o, en el APK de depuración, el modo de simulación ([PruebaGuia]).
 *
 * Alertas: [AlertasEnRuta] sobre la caché de FE-3.6 (`AlertasPublicas`); cada alerta dicha vibra.
 *
 * Al crearse lee **una vez** la posición de «Ubicarme» (`SesionDeNavegacion.ubicacion`, aunque ya no sea vigente: es la
 * mejor posición que hay) y el destino de 6.4, y calcula la ruta con el rumbo del final del escaneo corregido. Con
 * datos de prueba ([PruebaGuia.activa]) usa su destino y su posición. Líneas `Guia` en `app.log` (sin posiciones; el
 * destino sale como `<destino>`): las lee `validate53.py`.
 */
class NavegacionViewModel(app: Application) : AndroidViewModel(app) {

    private val parametros = ParametrosGuia()
    private val voz = VoiceController(app)
    private val cola = ColaVoz({ texto, alTerminar -> voz.speak(texto, alTerminar) })
    private val repo: LocalizacionFrameRepository = RemoteFrameRepository(appVersion = versionDeLaApp(app))
    private val prueba = PruebaGuia.activa
    private val simulacion = if (prueba) PruebaGuia.simulacion else null
    private val carpetaFotos = File(app.filesDir, CARPETA_FOTOS)
    private val vibracion = FeedbackCaptura(app) // alertas: vibra como el mapa (FE-3.6)

    /** `true` en el modo de simulación: la pantalla no crea el PDR. */
    val simulando: Boolean = simulacion != null

    /** Posición de partida para el PDR (`null` si no se pudo empezar). */
    var posicionInicial: Pair<Double, Double>? = null
        private set

    private val guia: GuiaNavegacion?
    private var simulador: SimuladorPasos? = null
    private var trabajoSimulacion: Job? = null
    private var pedido: SalidaGuia.TomarFoto? = null
    private var abierto = false
    private var pausado = false
    private var terminado = false
    private var ultimosPasos = -1
    private var destinoTexto = ""

    private val _estado = MutableStateFlow(NavegacionUiState(simulacion = simulando))
    val estado: StateFlow<NavegacionUiState> = _estado.asStateFlow()

    private val _eventos = Channel<NavegacionEvento>(Channel.BUFFERED)
    val eventos: Flow<NavegacionEvento> = _eventos.receiveAsFlow()

    init {
        guia = crearGuia(app)
    }

    private fun crearGuia(app: Application): GuiaNavegacion? {
        val planificador: Planificador? = runCatching { GrafoDeLaApp.planificador(app) }.getOrNull()
        if (planificador == null) return fallar(TextosGuia.RUTAS_DESACTIVADAS, "grafo no disponible")
        val inicio: Pair<Double, Double>
        val rumbo: Double?
        var incertidumbre = parametros.incertidumbreInicialM
        val calcular: (Double, Double, Double?) -> Ruta?
        if (prueba) {
            val texto = PruebaGuia.destino!!
            inicio = PruebaGuia.posicion!!
            rumbo = null
            val nombre = TextosRutaMapa.nombrePrueba(planificador, texto)
            destinoTexto = nombre
            calcular = { la, ln, r -> encontrada(planificador.calcular(la, ln, listOf(texto), nombre, r)) }
        } else {
            val u = SesionDeNavegacion.ubicacion.value
            val ubicado = u?.ubicado ?: return fallar(TextosGuia.SIN_UBICACION, "sin ubicación")
            val destino = SesionDeNavegacion.destino.value ?: return fallar(TextosGuia.SIN_RUTA, "sin destino")
            inicio = ubicado.posicion.lat to ubicado.posicion.lng
            incertidumbre = ubicado.posicion.radioM
            rumbo = DescribirUbicacion.rumboCorregido(u.rumboAlTerminar, ubicado.correccionRumboGrados)
            destinoTexto = destino.nombre
            calcular = { la, ln, r -> encontrada(planificador.calcular(la, ln, destino, r)) }
        }
        val ruta = calcular(inicio.first, inicio.second, rumbo) ?: return fallar(TextosGuia.SIN_RUTA, "sin ruta")
        posicionInicial = inicio
        simulacion?.let { simulador = SimuladorPasos(TrazadoRuta(ruta), it.pasoM) }
        AppLog.i(
            TAG,
            "Guía iniciada: ruta ${ruta.metros.roundToInt()} m, ${ruta.instrucciones.size} instrucciones" +
                (if (ruta.fueraDelCamino) ", fuera del camino" else "") +
                (if (prueba) ", datos de prueba" else "") +
                (simulacion?.let { ", simulación ${it.pasoM} m cada ${it.intervaloMs} ms" } ?: ""),
        )
        // FE-3.6 en la guía: la caché de alertas públicas (ya cargada por MyApp; se vuelve a pedir por si acaso).
        val cache = AlertasPublicas.de(app)
        viewModelScope.launch { runCatching { cache.cargar() } }
        val avisador = AlertasEnRuta(
            alertas = { cache.estado.value.alertas },
            p = parametros,
            registrar = { AppLog.i(CacheAlertasPublicas.TAG, it) },
        )
        return GuiaNavegacion(calcular, ruta, parametros, avisador, incertidumbreInicialM = incertidumbre)
    }

    private fun encontrada(r: ResultadoRuta): Ruta? = (r as? ResultadoRuta.Encontrada)?.ruta

    private fun fallar(texto: String, motivo: String): GuiaNavegacion? {
        AppLog.w(TAG, "Guía no iniciada: $motivo")
        _estado.value = _estado.value.copy(instruccion = texto, error = texto)
        return null
    }

    /** Al entrar en composición: dice cómo llevar el teléfono y la primera instrucción (una sola vez). */
    fun alAbrir() {
        if (abierto) return
        abierto = true
        carpetaFotos.listFiles()?.forEach { it.delete() } // restos de una guía anterior
        val g = guia
        if (g == null) {
            cola.decir(_estado.value.error ?: TextosGuia.SIN_RUTA)
            return
        }
        procesar(g.empezar())
        arrancarSimulacion()
    }

    private fun arrancarSimulacion() {
        val sim = simulador ?: return
        val intervalo = simulacion?.intervaloMs ?: return
        trabajoSimulacion = viewModelScope.launch {
            while (!terminado) {
                delay(intervalo)
                if (pausado) continue
                val g = guia ?: break
                if (g.llegado) break
                val p = sim.siguiente()
                procesar(g.alMoverse(p.lat, p.lng, p.caminadoM, null))
            }
        }
    }

    /** Cada estado del PDR (la pantalla lo recoge); solo cuenta cuando hay un paso nuevo. Ignorado al simular. */
    fun onPdr(e: PdrEstado) {
        val g = guia ?: return
        if (simulando || terminado || g.llegado) return
        val lat = e.lat ?: return
        val lng = e.lng ?: return
        if (!e.activo || e.pasos == ultimosPasos) return
        ultimosPasos = e.pasos
        procesar(g.alMoverse(lat, lng, e.distanciaMetros, e.rumboGrados.toDouble()))
    }

    /** «Repetir instrucción». */
    fun repetir() {
        val g = guia
        cola.decir(if (g == null) _estado.value.error ?: TextosGuia.SIN_RUTA else g.repetir(), prioritario = true)
    }

    /** «Terminar»: calla y deja de guiar (la pantalla navega). */
    fun terminar() {
        if (terminado) return
        terminado = true
        trabajoSimulacion?.cancel()
        cola.vaciar()
        voz.stopAll()
        AppLog.i(TAG, "Guía terminada por la persona")
    }

    /** `ON_STOP`: calla y pausa la simulación (el PDR se pausa solo: sigue el ciclo de vida de la pantalla). */
    fun alPausar() {
        pausado = true
        cola.vaciar()
        voz.stopAll()
    }

    fun alReanudar() {
        pausado = false
    }

    /** La pantalla guardó la foto pedida: comprobar nitidez, enviarla y pasar la respuesta a la guía. Se borra siempre. */
    fun onFotoTomada(archivo: File) {
        val p = pedido
        val g = guia
        if (p == null || g == null || terminado) {
            archivo.delete()
            return
        }
        viewModelScope.launch {
            val inicio = SystemClock.elapsedRealtime()
            try {
                if (parametros.descartarBorrosas) {
                    val calidad = withContext(Dispatchers.Default) { runCatching { evaluarCalidad(archivo) }.getOrDefault(Calidad.OK) }
                    if (calidad != Calidad.OK) {
                        AppLog.i(TAG, "Foto no enviada: ${calidad.name.lowercase()}")
                        procesar(g.alFallarFoto(p, FalloFrame.FOTO_NO_VALIDA))
                        return@launch
                    }
                }
                AppLog.i(TAG, "Enviando foto a POST /v1/localize/frame (radio ${p.radioM.roundToInt()} m)")
                val r = withTimeout(TIMEOUT_FRAME_MS) {
                    repo.localizarFrame(archivo, p.rumbo, p.previaLat, p.previaLng, p.radioM)
                }
                val ms = SystemClock.elapsedRealtime() - inicio
                AppLog.i(
                    TAG,
                    when (r) {
                        is ResultadoFrame.Ubicado ->
                            "Foto: ok nivel=${r.nivel.etiqueta} distancia_previa=${r.distanciaPreviaM} en_radio=${r.imagenesEnRadio} ($ms ms)"
                        is ResultadoFrame.SinCoincidencias -> "Foto: sin_coincidencias en_radio=${r.imagenesEnRadio} ($ms ms)"
                    },
                )
                procesar(g.alResponderFoto(p, r))
                AppLog.i(TAG, "Foto ${g.estado().ultimaFoto}")
            } catch (e: Throwable) {
                if (e is CancellationException && e !is kotlinx.coroutines.TimeoutCancellationException) throw e
                val fallo = falloFrameDe(e)
                AppLog.w(TAG, "Foto falló (${fallo.clave}): ${e.javaClass.simpleName}")
                procesar(g.alFallarFoto(p, fallo))
            } finally {
                if (pedido === p) pedido = null
                withContext(Dispatchers.IO) { archivo.delete() }
            }
        }
    }

    /** La pantalla no pudo tomar la foto (sin cámara, sin permiso o error de CameraX). */
    fun onFotoFallida() {
        val p = pedido ?: return
        pedido = null
        AppLog.w(TAG, "Foto falló (sin_foto)")
        guia?.let { procesar(it.alFallarFoto(p, FalloFrame.OTRO)) }
    }

    /** Carpeta de las fotos de corrección (`files/camera/guia/`); se borran al enviarlas. */
    fun carpetaFotos(): File = carpetaFotos.apply { mkdirs() }

    private fun procesar(salidas: List<SalidaGuia>) {
        val g = guia ?: return
        for (s in salidas) {
            when (s) {
                is SalidaGuia.Hablar -> {
                    AppLog.i(TAG, "Voz${if (s.prioritario) " (ya)" else ""}: ${sinDestino(s.texto)}")
                    if (!pausado && !terminado) {
                        cola.decir(s.texto, s.prioritario)
                        if (s.vibrar) vibracion.confirmar()
                    }
                }
                is SalidaGuia.TomarFoto -> {
                    pedido = s
                    _eventos.trySend(NavegacionEvento.TomarFoto)
                }
                is SalidaGuia.CorregirPosicion -> {
                    AppLog.i(TAG, "Posición corregida por la foto")
                    if (!simulando) _eventos.trySend(NavegacionEvento.CorregirPosicion(s.lat, s.lng))
                }
                is SalidaGuia.RutaNueva -> {
                    AppLog.i(TAG, "Ruta recalculada: ${s.ruta.metros.roundToInt()} m, ${s.ruta.instrucciones.size} instrucciones")
                    simulador?.cambiarRuta(TrazadoRuta(s.ruta))
                }
                is SalidaGuia.Llegada -> {
                    AppLog.i(TAG, "Llegada: ${sinDestino(s.texto)}")
                    LlegadaGuia.texto = s.texto
                    terminado = true
                    cola.vaciar()
                    voz.stopAll()
                    _eventos.trySend(NavegacionEvento.Llegada)
                }
            }
        }
        _estado.value = NavegacionUiState.de(g.estado(), simulando)
    }

    private fun sinDestino(texto: String): String =
        if (destinoTexto.isBlank()) texto else texto.replace(destinoTexto, "<destino>")

    override fun onCleared() {
        trabajoSimulacion?.cancel()
        voz.release()
        vibracion.liberar()
        if (prueba) PruebaGuia.limpiar()
        carpetaFotos.listFiles()?.forEach { it.delete() }
    }

    companion object {
        /** Espera máxima de una foto (re-codificar + `POST /v1/localize/frame`): después ya no sirve (se caminó). */
        const val TIMEOUT_FRAME_MS = 15_000L
        const val CARPETA_FOTOS = "camera/guia"

        private fun versionDeLaApp(app: Application): String? =
            runCatching { app.packageManager.getPackageInfo(app.packageName, 0).versionName }.getOrNull()
    }
}
