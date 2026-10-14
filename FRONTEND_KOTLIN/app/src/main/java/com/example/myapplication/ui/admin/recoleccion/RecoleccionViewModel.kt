package com.example.myapplication.ui.admin.recoleccion

import android.app.Application
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.RecoleccionRepository
import com.example.myapplication.data.repository.RecoleccionRepositoryLocal
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.DatosFoto
import com.example.myapplication.domain.model.FotoRecolectada
import com.example.myapplication.domain.model.SesionDeRecoleccion
import com.example.myapplication.domain.usecase.Deriva
import com.example.myapplication.domain.usecase.DisparadorCaptura
import com.example.myapplication.domain.usecase.ModoCaptura
import com.example.myapplication.logs.AppLog
import com.example.myapplication.sensors.PdrEstado
import com.example.myapplication.sensors.PdrEvento
import com.example.myapplication.sensors.PdrTracker
import com.example.myapplication.ui.admin.mapa.MAX_MENSAJE
import com.example.myapplication.ui.ubicacion.FeedbackCaptura
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import kotlin.math.abs

private const val TAG = "RecoleccionVM"

/**
 * ViewModel de la vista 7.4 (recolección en curso).
 *
 * Es dueño del [PdrTracker], del [DisparadorCaptura] y del almacenamiento: así la grabación
 * sobrevive a una rotación de pantalla. La **pantalla** es dueña de CameraX: cuando toca una foto
 * el ViewModel emite [RecoleccionEvento.Capturar] y la pantalla llama a `tomarFoto` con
 * [carpetaFotos], devolviendo el resultado por [onFotoTomada] / [onFotoFallida].
 *
 * Todo corre en el hilo principal (PdrTracker lo exige); el disco va por el repositorio.
 */
class RecoleccionViewModel(app: Application) : AndroidViewModel(app) {

    private val repo: RecoleccionRepository = RecoleccionRepositoryLocal(app)
    private val tracker = PdrTracker(app)
    private val feedback = FeedbackCaptura(app)
    private val disparador = DisparadorCaptura()

    private val _ui = MutableStateFlow(RecoleccionUiState())
    val ui: StateFlow<RecoleccionUiState> = _ui.asStateFlow()

    private val _eventos = Channel<RecoleccionEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    // ---- Estado interno (no se muestra tal cual) --------------------------------------------

    private var iniciado = false
    private var videoId: String? = null

    private val fotos = mutableListOf<FotoRecolectada>()
    private val trayectoria = mutableListOf<Punto>()
    private val alertas = mutableListOf<Alerta>()

    private var capturando = false
    private var pendiente: DatosFoto? = null
    private var distanciaAlCapturar = 0.0
    private var fallosSeguidos = 0
    private var pausaCapturaHastaMs = 0L

    /** Índices desde donde se corrige un re-anclaje (todo lo anterior ya está anclado). */
    private var indiceAnclaFoto = 0
    private var indiceAnclaTray = 0
    private var distanciaAncla = 0.0
    private var pasosUltimoPunto = 0

    private var acumuladoMs = 0L
    private var ultimoTickMs = 0L
    private var avisoMaximoDado = false

    private data class Punto(val lat: Double, val lng: Double)

    /** Carpeta donde la pantalla debe escribir la foto (prefijo recomendado: "tmp"). `null` antes de crear el video. */
    fun carpetaFotos(): File? = videoId?.let { repo.carpetaFotos(it) }

    // ---- Arranque ---------------------------------------------------------------------------

    /**
     * La llama la pantalla al abrirse. Idempotente (rotar o volver no reinicia el video).
     *
     * TODO: si no hay `inicio` pero `repo.buscarEnCurso()` devuelve un video, retomarlo (hoy se
     * muestra SIN_INICIO si Android mató el proceso a mitad de una grabación).
     */
    fun alAbrir() {
        if (iniciado) return
        iniciado = true
        val inicio = SesionDeRecoleccion.consumirInicio()
        if (inicio == null) {
            AppLog.w(TAG, "Se abrió la recolección sin InicioRecoleccion")
            _ui.update { it.copy(error = ErrorRecoleccion.SIN_INICIO) }
            return
        }
        val rumboInicial = inicio.rumbo.toFloat()
        _ui.update {
            it.copy(nombreVideo = inicio.nombreVideo, lat = inicio.lat, lng = inicio.lng, rumbo = rumboInicial)
        }
        viewModelScope.launch {
            val id = try {
                repo.crearVideo(inicio)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                AppLog.e(TAG, "No se pudo crear el video", e)
                _ui.update { it.copy(error = ErrorRecoleccion.NO_SE_PUDO_CREAR) }
                return@launch
            }
            videoId = id
            trayectoria.add(Punto(inicio.lat, inicio.lng))
            _ui.update { it.copy(trayectoriaJson = trayectoriaAJson()) }

            // Recoger ANTES de iniciar: `eventos` del PDR no se repite (11.2).
            escucharPdr()
            tracker.fijarPosicion(inicio.lat, inicio.lng)
            tracker.fijarRumboManual(rumboInicial) // solo vale hasta la primera lectura de la brújula
            disparador.reiniciar()
            tracker.iniciar()

            ultimoTickMs = SystemClock.elapsedRealtime()
            _ui.update { it.copy(fase = FaseRecoleccion.GRABANDO) }
            AppLog.i(TAG, "Grabando $id (${inicio.nombreVideo})")
            revisarRecursos()
            lanzarReloj()
        }
    }

    private fun escucharPdr() {
        viewModelScope.launch {
            tracker.eventos.collect { ev ->
                when (ev) {
                    is PdrEvento.Brujula ->
                        if (!ev.disponible) avisar("Este teléfono no tiene brújula: el rumbo de las fotos puede ser impreciso.")
                    is PdrEvento.PasosPorAcelerometro ->
                        avisar("Los pasos se detectan con el acelerómetro y pueden ser menos precisos.")
                    else -> Unit
                }
            }
        }
        viewModelScope.launch { tracker.estado.collect { alCambiarPdr(it) } }
    }

    // ---- Seguimiento y disparo de fotos -----------------------------------------------------

    private fun alCambiarPdr(e: PdrEstado) {
        if (_ui.value.fase != FaseRecoleccion.GRABANDO) return
        val lat = e.lat ?: return
        val lng = e.lng ?: return
        val actual = _ui.value
        val rumbo = if (e.activo) e.rumboGrados.toFloat() else actual.rumbo
        val dist = e.distanciaMetros.toDouble()
        val pasos = e.pasos

        // El rumbo llega ~20 Hz: solo se publica si cambió de verdad.
        val cambio = lat != actual.lat || lng != actual.lng || pasos != actual.pasos ||
            diferenciaCircular(rumbo, actual.rumbo) >= UMBRAL_RUMBO_GRADOS
        if (cambio) {
            _ui.update {
                it.copy(
                    lat = lat, lng = lng, rumbo = rumbo, pasos = pasos, distanciaMetros = dist,
                    deriva = Deriva.estimar((dist - distanciaAncla).coerceAtLeast(0.0)),
                )
            }
        }

        if (pasos - pasosUltimoPunto >= PASOS_POR_PUNTO) {
            pasosUltimoPunto = pasos
            trayectoria.add(Punto(lat, lng))
            _ui.update { it.copy(trayectoriaJson = trayectoriaAJson()) }
        }

        if (fotos.size >= MAX_FOTOS_VIDEO) {
            if (!avisoMaximoDado) {
                avisoMaximoDado = true
                avisar("Llegaste al máximo de $MAX_FOTOS_VIDEO fotos. Finaliza el video.")
            }
            return
        }

        val ahora = SystemClock.elapsedRealtime()
        if (!capturando && !actual.reubicando && ahora >= pausaCapturaHastaMs &&
            disparador.debeCapturar(dist, ahora)
        ) {
            capturando = true
            pendiente = DatosFoto(lat, lng, normalizar(rumbo), System.currentTimeMillis())
            distanciaAlCapturar = dist
            _eventos.trySend(RecoleccionEvento.Capturar)
        }
    }

    /** La pantalla la llama cuando CameraX guardó el JPG. */
    fun onFotoTomada(archivo: File) {
        val datos = pendiente
        val id = videoId
        if (datos == null || id == null) {
            archivo.delete()
            capturando = false
            return
        }
        viewModelScope.launch {
            try {
                val foto = repo.registrarFoto(id, archivo, datos)
                fotos.add(foto)
                disparador.alCapturar(distanciaAlCapturar, SystemClock.elapsedRealtime())
                fallosSeguidos = 0
                feedback.confirmar()
                publicarFotos(destello = true)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                AppLog.e(TAG, "No se pudo registrar la foto", e)
                archivo.delete()
                registrarFallo("No se pudo guardar la foto.")
            } finally {
                capturando = false
                pendiente = null
            }
        }
    }

    /** La pantalla la llama cuando CameraX falló (el motivo solo queda en el log `Camara`). */
    fun onFotoFallida() {
        capturando = false
        pendiente = null
        registrarFallo("No se pudo tomar la foto.")
    }

    /** `DisparadorCaptura` sigue diciendo "sí" tras un fallo: se pausa para no reintentar en bucle. */
    private fun registrarFallo(mensaje: String) {
        fallosSeguidos++
        pausaCapturaHastaMs = SystemClock.elapsedRealtime() + if (fallosSeguidos >= 5) 5_000 else 1_000
        if (fallosSeguidos == 1) avisar(mensaje)
        if (fallosSeguidos == 5) avisar("La cámara no responde. Revisa que ninguna otra app la esté usando.")
    }

    private fun publicarFotos(destello: Boolean) {
        val json = JSONArray().apply {
            fotos.forEach { f ->
                put(
                    JSONObject().put("id", f.id).put("lat", f.lat).put("lng", f.lng)
                        .put("rumbo", f.rumbo?.toDouble() ?: JSONObject.NULL),
                )
            }
        }.toString()
        _ui.update {
            it.copy(
                fotosTomadas = fotos.size,
                fotosJson = json,
                destelloCaptura = if (destello) it.destelloCaptura + 1 else it.destelloCaptura,
            )
        }
    }

    // ---- Pausa, intervalo y segundo plano ---------------------------------------------------

    fun alAlternarPausa() {
        when (_ui.value.fase) {
            FaseRecoleccion.GRABANDO -> pausar()
            FaseRecoleccion.PAUSADA -> reanudar()
            else -> Unit
        }
    }

    private fun pausar() {
        acumularTiempo()
        tracker.detener()
        _ui.update { it.copy(fase = FaseRecoleccion.PAUSADA) }
        AppLog.i(TAG, "Pausado")
    }

    private fun reanudar() {
        val ahora = SystemClock.elapsedRealtime()
        ultimoTickMs = ahora
        disparador.alReanudar(ahora)
        tracker.iniciar()
        _ui.update { it.copy(fase = FaseRecoleccion.GRABANDO) }
        AppLog.i(TAG, "Reanudado")
    }

    /** La pantalla la llama en ON_STOP: la recolección solo funciona en primer plano (7.4). */
    fun alIrASegundoPlano() {
        if (_ui.value.fase == FaseRecoleccion.GRABANDO) {
            pausar()
            avisar("Grabación en pausa porque la app pasó a segundo plano.")
        }
    }

    fun alCambiarModo(modo: ModoCaptura) {
        disparador.cambiarModo(modo)
        _ui.update { it.copy(modo = modo) }
    }

    // ---- Re-anclaje manual ------------------------------------------------------------------

    /** Abre el modo "arrastra tu posición": se pausan las capturas hasta confirmar o cancelar. */
    fun alReubicarse() {
        val s = _ui.value
        if (!s.enCurso || s.reanclaje != null) return
        val lat = s.lat ?: return
        val lng = s.lng ?: return
        _ui.update { it.copy(reanclaje = PuntoReanclaje(lat, lng)) }
    }

    /** El mapa avisa mientras se arrastra el marcador. */
    fun alMoverReanclaje(lat: Double, lng: Double) {
        if (_ui.value.reanclaje == null) return
        _ui.update { it.copy(reanclaje = PuntoReanclaje(lat, lng)) }
    }

    fun alCancelarReanclaje() {
        _ui.update { it.copy(reanclaje = null) }
    }

    /**
     * Fija la posición del PDR en el punto elegido y desplaza **por igual** las fotos y la
     * trayectoria hechas desde el último ancla (aproximación: el error real crece poco a poco,
     * no es un salto). No crea otro video.
     *
     * Límite conocido: una foto que esté guardándose justo ahora puede quedar con la coordenada
     * vieja (las capturas se frenan al abrir el modo, así que casi no ocurre).
     */
    fun alConfirmarReanclaje() {
        val s = _ui.value
        val destino = s.reanclaje ?: return
        val id = videoId ?: return
        val lat0 = s.lat ?: return
        val lng0 = s.lng ?: return
        val dLat = destino.lat - lat0
        val dLng = destino.lng - lng0

        tracker.fijarPosicion(destino.lat, destino.lng)

        for (i in indiceAnclaFoto until fotos.size) {
            fotos[i] = fotos[i].copy(lat = fotos[i].lat + dLat, lng = fotos[i].lng + dLng)
        }
        for (i in indiceAnclaTray until trayectoria.size) {
            trayectoria[i] = Punto(trayectoria[i].lat + dLat, trayectoria[i].lng + dLng)
        }
        trayectoria.add(Punto(destino.lat, destino.lng))
        val desde = indiceAnclaFoto
        indiceAnclaFoto = fotos.size
        indiceAnclaTray = trayectoria.size
        distanciaAncla = s.distanciaMetros

        publicarFotos(destello = false)
        _ui.update {
            it.copy(
                lat = destino.lat, lng = destino.lng, reanclaje = null,
                trayectoriaJson = trayectoriaAJson(), deriva = Deriva.estimar(0.0),
            )
        }
        AppLog.i(TAG, "Re-anclaje: ${fotos.size - desde} foto(s) desplazada(s)")
        viewModelScope.launch {
            try {
                repo.desplazarFotos(id, desde, dLat, dLng)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                AppLog.e(TAG, "No se pudo guardar el re-anclaje", e)
                avisar("No se pudo guardar la corrección de posición.")
            }
        }
    }

    // ---- Alertas ----------------------------------------------------------------------------

    /**
     * Abre el formulario de alerta (`AlertaFormSheet`) con la posición actual, sin interrumpir la grabación.
     *
     * TODO: las alertas existentes y las nuevas viven solo en este ViewModel. Falta un
     * `AlertasRepository` (7.8 también las tiene en memoria): cargar las existentes y guardar
     * las nuevas. Hasta entonces, **lo que se cree aquí se pierde al salir**.
     */
    fun alAgregarAlerta() {
        val s = _ui.value
        val lat = s.lat ?: return
        val lng = s.lng ?: return
        if (s.formularioAlerta != null) return
        _ui.update {
            it.copy(
                formularioAlerta = Alerta(id = UUID.randomUUID().toString(), lat = lat, lng = lng, mensaje = ""),
                errorAlerta = null,
            )
        }
    }

    fun alActualizarAlerta(alerta: Alerta) {
        _ui.update { it.copy(formularioAlerta = alerta, errorAlerta = null) }
    }

    fun alCancelarAlerta() {
        _ui.update { it.copy(formularioAlerta = null, errorAlerta = null) }
    }

    fun alGuardarAlerta() {
        val borrador = _ui.value.formularioAlerta ?: return
        val error = validarMensajeAlerta(borrador.mensaje)
        if (error != null) {
            _ui.update { it.copy(errorAlerta = error) }
            return
        }
        val guardada = borrador.copy(mensaje = borrador.mensaje.trim())
        alertas.removeAll { it.id == guardada.id }
        alertas.add(guardada)
        _ui.update {
            it.copy(
                formularioAlerta = null, errorAlerta = null,
                alertasJson = alertasAJson(), alertasActivas = alertas.count { a -> a.activa },
            )
        }
        AppLog.i(TAG, "Alerta agregada (${alertas.size} en total)")
    }

    // ---- Finalizar --------------------------------------------------------------------------

    /** Botón "Finalizar video" y también el "atrás" del sistema: siempre pide confirmación. */
    fun alPedirFinalizar() {
        if (_ui.value.enCurso) _ui.update { it.copy(confirmandoFinalizar = true) }
    }

    fun alCancelarFinalizar() {
        _ui.update { it.copy(confirmandoFinalizar = false) }
    }

    /**
     * Cierra el video. Con 0 fotos el video se borra (no hay nada que revisar) y se emite
     * [RecoleccionEvento.Descartado]; si no, [RecoleccionEvento.Finalizado].
     */
    fun alConfirmarFinalizar() {
        val id = videoId ?: return
        if (!_ui.value.enCurso) return
        acumularTiempo()
        tracker.detener()
        _ui.update { it.copy(fase = FaseRecoleccion.FINALIZANDO, confirmandoFinalizar = false) }
        viewModelScope.launch {
            var esperado = 0
            while (capturando && esperado < 3_000) { // dar tiempo a la última foto en curso
                delay(100)
                esperado += 100
            }
            try {
                if (fotos.isEmpty()) {
                    repo.descartar(id)
                    SesionDeRecoleccion.limpiar()
                    AppLog.i(TAG, "Video $id sin fotos: descartado")
                    _eventos.trySend(RecoleccionEvento.Descartado)
                } else {
                    val s = _ui.value
                    val resumen = repo.finalizar(id, acumuladoMs / 1000, s.distanciaMetros, s.pasos)
                    SesionDeRecoleccion.finalizar(resumen)
                    AppLog.i(TAG, "Video $id finalizado: ${resumen.totalFotos} fotos")
                    _eventos.trySend(RecoleccionEvento.Finalizado(resumen))
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                AppLog.e(TAG, "No se pudo finalizar $id", e)
                _ui.update { it.copy(fase = FaseRecoleccion.PAUSADA) }
                avisar("No se pudo finalizar el video. Inténtalo de nuevo.")
            }
        }
    }

    // ---- Reloj y recursos -------------------------------------------------------------------

    private fun lanzarReloj() {
        viewModelScope.launch {
            var ticks = 0
            while (true) {
                delay(1_000)
                if (_ui.value.fase == FaseRecoleccion.GRABANDO) {
                    acumularTiempo()
                    _ui.update { it.copy(duracionSegundos = acumuladoMs / 1000) }
                }
                if (++ticks % 30 == 0) revisarRecursos()
            }
        }
    }

    private fun acumularTiempo() {
        val ahora = SystemClock.elapsedRealtime()
        if (_ui.value.fase == FaseRecoleccion.GRABANDO) acumuladoMs += ahora - ultimoTickMs
        ultimoTickMs = ahora
    }

    /** Batería y almacenamiento (cada 30 s). Con muy poco espacio se pausa sola. */
    private fun revisarRecursos() {
        val intent = getApplication<Application>()
            .registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val nivel = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val escala = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val estado = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val cargando = estado == BatteryManager.BATTERY_STATUS_CHARGING || estado == BatteryManager.BATTERY_STATUS_FULL
        val porcentaje = if (nivel >= 0 && escala > 0) nivel * 100 / escala else 100
        val bateriaBaja = porcentaje <= BATERIA_BAJA_PCT && !cargando

        val libre = repo.espacioLibreBytes()
        val espacioBajo = libre < ESPACIO_BAJO_BYTES

        _ui.update {
            var avisos = it.avisos - AvisoRecoleccion.BATERIA_BAJA - AvisoRecoleccion.ALMACENAMIENTO_BAJO
            if (bateriaBaja) avisos = avisos + AvisoRecoleccion.BATERIA_BAJA
            if (espacioBajo) avisos = avisos + AvisoRecoleccion.ALMACENAMIENTO_BAJO
            it.copy(avisos = avisos)
        }
        if (libre < ESPACIO_CRITICO_BYTES && _ui.value.fase == FaseRecoleccion.GRABANDO) {
            pausar()
            avisar("Casi no queda espacio: la grabación se pausó. Libera almacenamiento y finaliza el video.")
        }
    }

    // ---- Avisos y utilidades ----------------------------------------------------------------

    private fun avisar(mensaje: String) {
        _ui.update { it.copy(aviso = mensaje) }
    }

    fun descartarAviso() {
        _ui.update { it.copy(aviso = null) }
    }

    private fun trayectoriaAJson(): String =
        JSONArray().apply {
            trayectoria.forEach { put(JSONArray().put(it.lat).put(it.lng)) }
        }.toString()

    private fun alertasAJson(): String =
        JSONArray().apply {
            alertas.forEach { a ->
                put(
                    JSONObject().put("id", a.id).put("lat", a.lat).put("lng", a.lng)
                        .put("mensaje", a.mensaje).put("tipo", a.tipo).put("prioridad", a.prioridad)
                        .put("radio", a.radio).put("activa", a.activa),
                )
            }
        }.toString()

    override fun onCleared() {
        // No se borra el video: queda `en_curso` en disco por si hay que retomarlo.
        tracker.liberar()
        feedback.liberar()
        super.onCleared()
    }

    private companion object {
        const val UMBRAL_RUMBO_GRADOS = 2f
        const val PASOS_POR_PUNTO = 3
        const val BATERIA_BAJA_PCT = 15
        const val ESPACIO_BAJO_BYTES = 200L * 1024 * 1024
        const val ESPACIO_CRITICO_BYTES = 50L * 1024 * 1024
    }
}

/** Misma regla que `EditorMapaViewModel.guardarFormulario` (candidata a extraerse a un caso de uso, 11.5). */
internal fun validarMensajeAlerta(mensaje: String): String? {
    val m = mensaje.trim()
    return when {
        m.isEmpty() -> "Escribe el mensaje que se leerá al usuario."
        m.length > MAX_MENSAJE -> "Máximo $MAX_MENSAJE caracteres."
        else -> null
    }
}

/** Diferencia mínima entre dos rumbos (359° y 1° dan 2°, no 358°). */
private fun diferenciaCircular(a: Float, b: Float): Float {
    val d = abs(a - b) % 360f
    return if (d > 180f) 360f - d else d
}

/** Rumbo en 0…360 (11.6: `Foto.rumbo` debe guardarse normalizado). */
private fun normalizar(grados: Float): Float = ((grados % 360f) + 360f) % 360f