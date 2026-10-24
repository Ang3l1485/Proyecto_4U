package com.example.myapplication.ui.ubicacion

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.logs.AppLog
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
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import java.io.File
import java.io.IOException
import kotlin.math.abs

private const val TAG = "EscaneoVM"

/**
 * true  = las fotos NO se borran del disco (ni al cancelar, ni al terminar).
 * false = se borran al cancelar, al reiniciar y al destruir el ViewModel.
 * Ponlo en false antes de publicar la app (ver decisión abierta de privacidad).
 */
private const val CONSERVAR_FOTOS = true

/**
 * Cerebro del escaneo 360°.
 *
 * Responsabilidades:
 *  - Seguir cuánto ha girado el usuario (a partir del acimut del sensor).
 *  - Decidir cuándo pedir una foto (cada 72°, solo si va despacio y con el celular vertical).
 *  - Aceptar cada foto guardada (por ahora SIN control de calidad).
 *  - Dar retroalimentación por voz, vibración y sonido.
 *  - Enviar las 5 fotos al backend y reportar éxito o error.
 *
 * Qué NO hace: no toca la cámara ni los sensores directamente; la pantalla se los
 * entrega ([onOrientacion], [onFotoTomada]...) y recibe órdenes por [eventos].
 */
class EscaneoViewModel(app: Application) : AndroidViewModel(app) {

    // --- Dependencias -------------------------------------------------------
    private val backend: EscaneoBackend = EscaneoBackendStub
    private val voz = VoiceController(app)
    private val feedback = FeedbackCaptura(app)

    // --- Salidas hacia la UI ------------------------------------------------
    private val _estado = MutableStateFlow(EscaneoUiState())
    val estado: StateFlow<EscaneoUiState> = _estado.asStateFlow()

    private val _eventos = MutableSharedFlow<EscaneoEvento>(extraBufferCapacity = 4)
    val eventos: SharedFlow<EscaneoEvento> = _eventos.asSharedFlow()

    // --- Estado interno (no necesita ser observado por la UI) ---------------
    private val fotos = mutableListOf<File>()   // fotos ya aceptadas
    private var ultimoAcimut: Float? = null     // acimut de la lectura anterior
    private var ultimoT = 0L                    // instante de la lectura anterior (ms)
    private var ultimoAvance = 0L               // último instante en que el usuario avanzó
    private var velocidad = 0f                  // velocidad angular suavizada (°/s)
    private var capturando = false              // hay una foto en curso: no pedir otra
    private var bloqueadoHasta = 0L             // pausa tras fallar una foto
    private var ultimoAviso = 0L                // anti-spam de avisos hablados
    private var job: Job? = null                // corrutina del análisis en el backend

    // ========================================================================
    // Acciones que dispara la pantalla
    // ========================================================================

    /** Empieza (o reinicia) el escaneo: instrucciones por voz y luego seguimiento del giro. */
    fun iniciar() {
        job?.cancel()
        descartarFotos()
        reiniciarSeguimiento()
        _estado.value = EscaneoUiState()
        AppLog.nuevaSesion("scan")
        AppLog.i(TAG, "Escaneo iniciado")
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

    /** Aborta todo y deja el estado limpio. */
    fun cancelar() {
        AppLog.i(TAG, "Escaneo cancelado (${fotos.size} fotos tomadas)")
        job?.cancel()
        voz.stopAll()
        descartarFotos()
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

        // Solo cuenta el giro hacia la derecha (delta > 0); nunca baja de 0 ni pasa de 360.
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
            fotos.size < TOTAL_FOTOS && progreso >= fotos.size * GRADOS_POR_FOTO
        ) {
            capturando = true
            AppLog.i(
                TAG,
                "Pidiendo foto ${fotos.size + 1}/$TOTAL_FOTOS " +
                    "(progreso=%.1f°, acimut=%.1f°, cabeceo=%.1f°)".format(progreso, acimutGrados, cabeceoGrados)
            )
            _eventos.tryEmit(EscaneoEvento.Capturar)
        }

        _estado.value = s.copy(progreso = progreso, inclinacionOk = inclinacionOk, instruccion = instruccion)
    }

    // ========================================================================
    // Resultado de la captura (lo reporta la pantalla)
    // ========================================================================

    /** CameraX no pudo capturar: pausa 1 s y deja que se reintente solo. */
    fun onFotoFallida() {
        AppLog.w(TAG, "CameraX no pudo capturar; se reintenta en 1 s")
        capturando = false
        bloqueadoHasta = SystemClock.elapsedRealtime() + 1000
    }

    /** Foto guardada: se acepta siempre (sin control de calidad por ahora). */
    fun onFotoTomada(archivo: File) {
        // Si mientras tanto se canceló o falló, la foto no se cuenta (pero queda en disco).
        if (_estado.value.fase != Fase.ESCANEANDO) {
            AppLog.w(TAG, "Foto ${archivo.name} llegó fuera de la fase ESCANEANDO; no se cuenta")
            capturando = false
            return
        }

        fotos += archivo
        feedback.confirmar()
        val n = fotos.size
        _estado.update { it.copy(fotos = n) }
        capturando = false
        AppLog.i(TAG, "Foto aceptada $n/$TOTAL_FOTOS: ${archivo.name}")
        if (n >= TOTAL_FOTOS) analizar()
    }

    // ========================================================================
    // Backend
    // ========================================================================

    /** Envía las fotos al backend con un tiempo límite. */
    private fun analizar() {
        _estado.update { it.copy(fase = Fase.ANALIZANDO, progreso = 360f) }
        AppLog.i(TAG, "Enviando ${fotos.size} fotos al backend")
        voz.speak("Listo, analizando.")
        job = viewModelScope.launch {
            val t0 = SystemClock.elapsedRealtime()
            try {
                withTimeout(TIMEOUT_BACKEND_MS) { backend.analizar(fotos.toList()) }
                AppLog.i(TAG, "Backend OK en ${SystemClock.elapsedRealtime() - t0} ms")
                _eventos.emit(EscaneoEvento.Completado)
            } catch (e: TimeoutCancellationException) {
                // Importante: va ANTES que CancellationException (es una subclase suya).
                AppLog.e(TAG, "Backend: tiempo agotado", e)
                fallar(ErrorEscaneo.TIEMPO_AGOTADO)
            } catch (e: CancellationException) {
                throw e // cancelación normal (p. ej. el usuario pulsó Cancelar): no es un error
            } catch (e: IOException) {
                AppLog.e(TAG, "Backend: error de red", e)
                fallar(ErrorEscaneo.SIN_CONEXION)
            } catch (e: Exception) {
                AppLog.e(TAG, "Backend: error inesperado", e)
                fallar(ErrorEscaneo.SIN_CONEXION)
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
        velocidad = 0f
        capturando = false
        bloqueadoHasta = 0L
    }

    /** Suelta la lista de fotos; solo las borra del disco si CONSERVAR_FOTOS es false. */
    private fun descartarFotos() {
        if (CONSERVAR_FOTOS) {
            if (fotos.isNotEmpty()) AppLog.i(TAG, "Conservando ${fotos.size} fotos en disco")
        } else {
            fotos.forEach { it.delete() }
        }
        fotos.clear()
    }

    override fun onCleared() {
        job?.cancel()
        voz.release()
        feedback.liberar()
        descartarFotos()
    }
}