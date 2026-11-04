package com.example.myapplication.ui.ubicacion

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.RemoteLocalizacionRepository
import com.example.myapplication.data.repository.LocalizacionRepository
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.usecase.ConversionRumbo
import com.example.myapplication.logs.AppLog
import com.example.myapplication.sensors.Declinacion
import com.example.myapplication.ui.inicio.VoiceController
import com.example.myapplication.ui.ubicacion.EscaneoConfig.AVISO_CADA_MS
import com.example.myapplication.ui.ubicacion.EscaneoConfig.GRADOS_POR_FOTO
import com.example.myapplication.ui.ubicacion.EscaneoConfig.INACTIVIDAD_MS
import com.example.myapplication.ui.ubicacion.EscaneoConfig.INCLINACION_MAX
import com.example.myapplication.ui.ubicacion.EscaneoConfig.TIMEOUT_BACKEND_MS
import com.example.myapplication.ui.ubicacion.EscaneoConfig.TOTAL_FOTOS
import com.example.myapplication.ui.ubicacion.EscaneoConfig.VELOCIDAD_MAX
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import java.io.File
import java.util.Locale
import kotlin.math.abs

private const val TAG = "EscaneoVM"

/**
 * true  = las fotos NO se borran del disco (solo para depurar).
 * false = se borran al recibir la respuesta del backend (o el error), al cancelar, al repetir y al destruir el
 *         ViewModel, también las que llegan fuera de la fase ESCANEANDO (FE-3.2, decisión abierta 12; validation-3-2
 *         C3 comprueba esta línea).
 */
internal const val CONSERVAR_FOTOS = false

/**
 * Cerebro del escaneo 360°.
 *
 * Responsabilidades:
 *  - Seguir cuánto ha girado el usuario (a partir del acimut del sensor).
 *  - Decidir cuándo pedir una foto (cada 72°, solo si va despacio y con el celular vertical).
 *  - Aceptar cada foto guardada (por ahora SIN control de calidad) con su rumbo en norte verdadero.
 *  - Dar retroalimentación por voz, vibración y sonido.
 *  - Enviar las 5 fotos a `POST /v1/localize` y entregar el resultado (o decir el error), y borrar las fotos.
 *
 * Qué NO hace: no toca la cámara ni los sensores directamente; la pantalla se los
 * entrega ([onOrientacion], [onFotoTomada]...) y recibe órdenes por [eventos].
 */
class EscaneoViewModel(app: Application) : AndroidViewModel(app) {

    // --- Dependencias -------------------------------------------------------
    // FE-3.2: `POST /v1/localize` real (antes `EscaneoBackendStub`).
    private val repositorio: LocalizacionRepository = RemoteLocalizacionRepository(appVersion = versionDeLaApp(app))
    private val voz = VoiceController(app)
    private val feedback = FeedbackCaptura(app)

    // --- Salidas hacia la UI ------------------------------------------------
    private val _estado = MutableStateFlow(EscaneoUiState())
    val estado: StateFlow<EscaneoUiState> = _estado.asStateFlow()

    // FE-3.2: Channel (un solo colector, la pantalla) en vez de SharedFlow sin repetición: un `Capturar` o un
    // `Completado` emitido sin colector (p. ej. al rotar) espera al siguiente colector en vez de perderse.
    private val _eventos = Channel<EscaneoEvento>(Channel.BUFFERED)
    val eventos: Flow<EscaneoEvento> = _eventos.receiveAsFlow()

    // --- Estado interno (no necesita ser observado por la UI) ---------------
    private val fotos = FotosEscaneo(conservar = CONSERVAR_FOTOS) // fotos aceptadas y su carpeta
    private var declinacion = 0.0               // grados (este +), calculada al iniciar (Declinacion)
    private var ultimoAcimut: Float? = null     // acimut de la lectura anterior (magnético)
    private var acimutPedido: Float? = null     // acimut al pedir la foto en curso (magnético)
    private var ultimoT = 0L                    // instante de la lectura anterior (ms)
    private var ultimoAvance = 0L               // último instante en que el usuario avanzó
    private var velocidad = 0f                  // velocidad angular suavizada (°/s)
    private var capturando = false              // hay una foto en curso: no pedir otra
    private var bloqueadoHasta = 0L             // pausa tras fallar una foto
    private var ultimoAviso = 0L                // anti-spam de avisos hablados
    private var job: Job? = null                // corrutina del análisis en el backend
    private var liberado = false                // onCleared ya corrió: toda foto que llegue se borra

    // ========================================================================
    // Acciones que dispara la pantalla
    // ========================================================================

    /**
     * Empieza (o reinicia) el escaneo en [carpeta] (la crea la pantalla con `crearCarpetaEscaneo`): instrucciones por
     * voz y luego seguimiento del giro. Borra las fotos del escaneo anterior.
     */
    fun iniciar(carpeta: File) {
        job?.cancel()
        fotos.abrir(carpeta)
        reiniciarSeguimiento()
        declinacion = Declinacion.paraLaUltimaPosicion()
        _estado.value = EscaneoUiState()
        AppLog.nuevaSesion("scan")
        AppLog.i(TAG, "Escaneo iniciado (declinación %.1f°)".format(Locale.ROOT, declinacion))
        voz.speak(
            "Sostén el celular vertical y gira lentamente hacia la derecha. " +
                "Sentirás una vibración con cada foto."
        ) {
            // Al terminar de hablar, pasamos a ESCANEANDO (si nadie canceló mientras tanto).
            if (_estado.value.fase == Fase.PREPARANDO) {
                reiniciarSeguimiento()
                _estado.update { it.copy(fase = Fase.ESCANEANDO) }
                AppLog.i(TAG, "Fase ESCANEANDO: ya puede girar")
            }
        }
    }

    /** Aborta todo, borra las fotos y deja el estado limpio. */
    fun cancelar() {
        AppLog.i(TAG, "Escaneo cancelado (${fotos.cantidad} fotos tomadas)")
        job?.cancel()
        voz.stopAll()
        borrarFotos()
        reiniciarSeguimiento()
        _estado.value = EscaneoUiState()
    }

    fun sensorNoDisponible() = fallar(ErrorEscaneo.SIN_SENSOR)

    // ========================================================================
    // Seguimiento del giro (se llama ~50 veces por segundo, hilo principal)
    // ========================================================================

    fun onOrientacion(acimutGrados: Float, cabeceoGrados: Float) {
        val s = _estado.value
        if (s.fase != Fase.ESCANEANDO) return

        val ahora = SystemClock.elapsedRealtime()
        val inclinacionOk = abs(cabeceoGrados) <= INCLINACION_MAX

        // Primera lectura: solo tomamos la referencia, aún no hay giro que medir.
        val previo = ultimoAcimut
        ultimoAcimut = acimutGrados
        if (previo == null) {
            ultimoT = ahora
            ultimoAvance = ahora
            _estado.value = s.copy(inclinacionOk = inclinacionOk)
            return
        }

        val dt = (ahora - ultimoT) / 1000f
        ultimoT = ahora
        if (dt <= 0f) return

        // Giro desde la lectura anterior, normalizado a (-180°, 180°] para cruzar 359°→0° sin saltos.
        var delta = acimutGrados - previo
        while (delta > 180f) delta -= 360f
        while (delta < -180f) delta += 360f

        // Velocidad suavizada (media móvil exponencial) para ignorar picos del sensor.
        velocidad = 0.85f * velocidad + 0.15f * (abs(delta) / dt)

        // El progreso suma el giro con signo (girar a la izquierda resta); nunca baja de 0 ni pasa de 360.
        val progreso = (s.progreso + delta).coerceIn(0f, 360f)
        if (delta > 0.2f) ultimoAvance = ahora

        // Qué le decimos al usuario (la inclinación tiene prioridad sobre la velocidad).
        val rapido = velocidad > VELOCIDAD_MAX
        val instruccion = when {
            !inclinacionOk -> Instruccion.VERTICAL
            rapido -> Instruccion.MAS_DESPACIO
            else -> Instruccion.GIRAR
        }
        if (instruccion != Instruccion.GIRAR) avisar(instruccion.texto.replace("\n", " "))

        // Si lleva demasiado sin avanzar, damos la vuelta por incompleta.
        if (ahora - ultimoAvance > INACTIVIDAD_MS) {
            fallar(ErrorEscaneo.VUELTA_INCOMPLETA)
            return
        }

        // ¿Toca foto? Todas las condiciones deben cumplirse:
        //  sin captura en curso, sin pausa activa, celular recto, giro lento,
        //  fotos pendientes y ya llegamos al ángulo de la siguiente (n * 72°).
        if (!capturando && ahora >= bloqueadoHasta && inclinacionOk && !rapido &&
            fotos.cantidad < TOTAL_FOTOS && progreso >= fotos.cantidad * GRADOS_POR_FOTO
        ) {
            capturando = true
            acimutPedido = acimutGrados
            AppLog.i(
                TAG,
                "Pidiendo foto ${fotos.cantidad + 1}/$TOTAL_FOTOS " +
                    "(progreso=%.1f°, acimut=%.1f°, cabeceo=%.1f°)".format(
                        Locale.ROOT, progreso, acimutGrados, cabeceoGrados,
                    )
            )
            _eventos.trySend(EscaneoEvento.Capturar)
        }

        _estado.value = s.copy(progreso = progreso, inclinacionOk = inclinacionOk, instruccion = instruccion)
    }

    // ========================================================================
    // Resultado de la captura (lo reporta la pantalla)
    // ========================================================================

    /** CameraX no pudo capturar: pausa 1 s y deja que se reintente solo. */
    fun onFotoFallida() {
        if (liberado) return
        AppLog.w(TAG, "CameraX no pudo capturar; se reintenta en 1 s")
        capturando = false
        bloqueadoHasta = SystemClock.elapsedRealtime() + 1000
    }

    /**
     * Foto guardada: se acepta siempre (sin control de calidad por ahora) con el rumbo verdadero del momento en que se
     * pidió. Una foto que llega fuera de la fase ESCANEANDO o de otra carpeta no se cuenta y se borra (FE-3.2).
     */
    fun onFotoTomada(archivo: File) {
        if (liberado || !fotos.esDeLaCarpeta(archivo)) {
            AppLog.w(TAG, "Foto ${archivo.name} de un escaneo ya cerrado: se descarta")
            fotos.descartar(archivo)
            return
        }
        if (_estado.value.fase != Fase.ESCANEANDO) {
            AppLog.w(TAG, "Foto ${archivo.name} llegó fuera de la fase ESCANEANDO; no se cuenta y se descarta")
            fotos.descartar(archivo)
            capturando = false
            return
        }

        val rumbo = acimutPedido?.let { ConversionRumbo.magneticoAVerdadero(it.toDouble(), declinacion) }
        fotos.aceptar(archivo, rumbo)
        feedback.confirmar()
        val n = fotos.cantidad
        _estado.update { it.copy(fotos = n) }
        capturando = false
        acimutPedido = null
        AppLog.i(TAG, "Foto aceptada $n/$TOTAL_FOTOS: ${archivo.name} (rumbo verdadero ${rumbo ?: "?"}°)")
        if (n >= TOTAL_FOTOS) analizar()
    }

    // ========================================================================
    // Backend
    // ========================================================================

    /** Envía las fotos a `POST /v1/localize` con un tiempo límite; al terminar (bien o mal) borra las fotos. */
    private fun analizar() {
        _estado.update { it.copy(fase = Fase.ANALIZANDO, progreso = 360f) }
        val enviadas = fotos.fotos
        val rumboAlTerminar = ultimoAcimut?.let { ConversionRumbo.magneticoAVerdadero(it.toDouble(), declinacion) }
        AppLog.i(TAG, "Enviando ${enviadas.size} fotos a POST /v1/localize")
        voz.speak("Listo, analizando.")
        job = viewModelScope.launch {
            val t0 = SystemClock.elapsedRealtime()
            try {
                val resultado = withTimeout(TIMEOUT_BACKEND_MS) { repositorio.localizar(enviadas) }
                AppLog.i(TAG, "Resultado: ${describir(resultado)} (${SystemClock.elapsedRealtime() - t0} ms)")
                borrarFotos()
                _eventos.trySend(EscaneoEvento.Completado(resultado, rumboAlTerminar))
            } catch (e: TimeoutCancellationException) {
                // Importante: va ANTES que CancellationException (es una subclase suya).
                AppLog.w(TAG, "Localización falló (TIEMPO_AGOTADO): sin respuesta en $TIMEOUT_BACKEND_MS ms")
                borrarFotos()
                fallar(ErrorEscaneo.TIEMPO_AGOTADO)
            } catch (e: CancellationException) {
                throw e // cancelación normal (p. ej. el usuario pulsó Cancelar): no es un error
            } catch (e: Exception) {
                val error = ErrorEscaneo.deExcepcion(e)
                if (error == ErrorEscaneo.DESCONOCIDO) {
                    AppLog.e(TAG, "Localización falló (${error.name}): ${detalleError(e)}", e)
                } else {
                    AppLog.w(TAG, "Localización falló (${error.name}): ${detalleError(e)}")
                }
                borrarFotos()
                fallar(error)
            }
        }
    }

    // ========================================================================
    // Utilidades internas
    // ========================================================================

    /** Pasa a ERROR y lo anuncia por voz. */
    private fun fallar(error: ErrorEscaneo) {
        AppLog.w(TAG, "Escaneo en ERROR: $error")
        capturando = false
        _estado.update { it.copy(fase = Fase.ERROR, error = error) }
        voz.speak("${error.mensaje}. Toca repetir para intentar otra vez.")
    }

    /** Habla [texto], pero no más seguido que [AVISO_CADA_MS] salvo que [forzar] sea true. */
    private fun avisar(texto: String, forzar: Boolean = false) {
        val ahora = SystemClock.elapsedRealtime()
        if (forzar || ahora - ultimoAviso > AVISO_CADA_MS) {
            ultimoAviso = ahora
            voz.speak(texto)
        }
    }

    /** Borra toda la memoria del giro para empezar una vuelta desde cero. */
    private fun reiniciarSeguimiento() {
        ultimoAcimut = null
        acimutPedido = null
        velocidad = 0f
        capturando = false
        bloqueadoHasta = 0L
    }

    /** Cierra el escaneo: con CONSERVAR_FOTOS en false borra su carpeta (originales y copias re-codificadas). */
    private fun borrarFotos() {
        val carpeta = fotos.carpeta?.name ?: return
        val n = fotos.cerrar()
        if (CONSERVAR_FOTOS) {
            AppLog.i(TAG, "Fotos del escaneo conservadas (carpeta $carpeta)")
        } else {
            AppLog.i(TAG, "Fotos del escaneo borradas (carpeta $carpeta, $n archivos)")
        }
    }

    /** Lo que se registra de un resultado: sin posición ni nombres de lugares (privacidad, HU-23). */
    private fun describir(r: ResultadoUbicacion): String = when (r) {
        is ResultadoUbicacion.SinCoincidencias -> "sin_coincidencias fotos=${r.fotosUsadas}"
        is ResultadoUbicacion.Ubicado ->
            "ok nivel=${r.nivel.etiqueta} confianza=${"%.2f".format(Locale.ROOT, r.confianza)} " +
                "cercano=${if (r.lugarCercano != null) "sí" else "no"} referencias=${r.referencias.size} " +
                "correccion=${r.correccionRumboGrados ?: "-"} fotos=${r.fotosUsadas}/${r.fotosConCoincidencia}"
    }

    /** Detalle de un error para el registro: código, fallo y `X-Request-Id` (nunca cuerpos ni tokens). */
    private fun detalleError(e: Exception): String = when (e) {
        is ApiException -> "HTTP ${e.http} ${e.fallo} rid=${e.requestId ?: "-"}"
        else -> "${e.javaClass.simpleName}: ${e.message}"
    }

    override fun onCleared() {
        liberado = true
        job?.cancel()
        voz.release()
        feedback.liberar()
        borrarFotos()
    }

    private companion object {
        fun versionDeLaApp(app: Application): String? =
            runCatching { app.packageManager.getPackageInfo(app.packageName, 0).versionName }.getOrNull()
    }
}
