package com.example.myapplication.sensors

import android.content.Context
import android.hardware.GeomagneticField
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import com.example.myapplication.data.repository.CalibracionPasoRepository
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.abs
import kotlin.math.atan2

/**
 * Origen de los pasos. Desde 2026-10-12 los pasos salen **siempre** del acelerómetro ([ACELEROMETRO]);
 * `HARDWARE`, `ACELEROMETRO_SIN_PERMISO` y `ACELEROMETRO_SIN_SENSOR` se conservan solo para no romper
 * código que ya los nombra (el tracker ya no los asigna, salvo `ACELEROMETRO_SIN_SENSOR` si el teléfono
 * no tiene acelerómetro).
 */
enum class FuentePasos {
    NINGUNA, HARDWARE, ACELEROMETRO_SIN_PERMISO, ACELEROMETRO_SIN_SENSOR, ACELEROMETRO,
}

data class PdrEstado(
    val lat: Double? = null,
    val lng: Double? = null,
    /** Grados, 0 = norte real, sentido horario. */
    val rumboGrados: Float = 0f,
    val pasos: Int = 0,
    val distanciaMetros: Double = 0.0,
    val velocidadMps: Double = 0.0,
    val activo: Boolean = false,
    val fuentePasos: FuentePasos = FuentePasos.NINGUNA,
)

/** Avisos de una sola vez (no son estado). */
sealed interface PdrEvento {
    /** Se evalúa en cada [PdrTracker.iniciar]: ¿hay sensor de rotación para el rumbo? */
    data class Brujula(val disponible: Boolean) : PdrEvento

    /**
     * Los pasos no se pueden detectar bien. Hoy solo se emite con `no_sensor` (el teléfono no tiene
     * acelerómetro). Ya no se emite `permission_denied`: el acelerómetro no necesita permiso.
     */
    data class PasosPorAcelerometro(val motivo: String) : PdrEvento
}

/**
 * Conecta los sensores de Android con [PdrEngine]. No depende de ninguna pantalla ni del WebView:
 * cualquier vista que necesite la posición (mapa público, recolección, navegación guiada) crea uno,
 * llama a [fijarPosicion] + [iniciar] y lee [estado].
 *
 * Hilo: todo ocurre en el hilo principal (los sensores se registran sin `Handler`, así que sus
 * callbacks llegan al principal). Quien lo llame desde otro hilo debe pasar al principal antes.
 *
 * Pasos: siempre por acelerómetro ([StepDetector]). El sensor de hardware `TYPE_STEP_DETECTOR` se
 * descartó porque tarda 1–3 s en reaccionar; con el acelerómetro el primer paso se cuenta en
 * ~0,1 s desde [iniciar].
 * Rumbo: `TYPE_ROTATION_VECTOR`, corregido a norte real con la declinación magnética de la
 * posición actual.
 *
 * Longitud de paso: por defecto la calibrada del usuario (si existe) o la genérica de
 * [PdrEngine]; se lee **una vez, al crear** el tracker. Recalibrar no afecta a uno ya creado.
 * ⚠ Una longitud calibrada con el sensor de hardware ya no es válida: hay que recalibrar.
 */
class PdrTracker(
    context: Context,
    longitudPasoM: Double = CalibracionPasoRepository(context).longitudPasoM(),
) {

    private val app = context.applicationContext
    private val sm = app.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val engine = PdrEngine(longitudPasoM = longitudPasoM)
    private val detector = StepDetector()

    private val _estado = MutableStateFlow(PdrEstado())
    val estado: StateFlow<PdrEstado> = _estado.asStateFlow()

    private val _eventos = MutableSharedFlow<PdrEvento>(extraBufferCapacity = 8)
    val eventos: SharedFlow<PdrEvento> = _eventos.asSharedFlow()

    /** Desviación de la aceleración (m/s²), ~20 Hz, para dibujar gráficas. Hilo principal. */
    var onAceleracion: ((Float) -> Unit)? = null

    private var activo = false
    private var fuente = FuentePasos.NINGUNA
    private var declinacion = 0f
    private var ultimoRumboPublicadoMs = 0L
    private var ultimaAceleracionMs = 0L

    // ── API ────────────────────────────────────

    /** Fija el punto de partida. Úsalo antes de [iniciar] (o al tocar otro punto del mapa). */
    fun fijarPosicion(lat: Double, lng: Double) {
        engine.fijarPosicion(lat, lng)
        actualizarDeclinacion()
        publicar()
    }

    fun fijarRumboManual(grados: Float) {
        engine.fijarRumboManual(grados)
        publicar()
    }

    fun reiniciar() {
        engine.reiniciar()
        detector.reiniciar()
        publicar()
    }

    fun iniciar() {
        if (activo) return
        activo = true
        detector.reiniciar()
        actualizarDeclinacion()

        val rotacion = sm.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
        if (rotacion != null) {
            sm.registerListener(listenerRumbo, rotacion, SensorManager.SENSOR_DELAY_GAME)
        }
        _eventos.tryEmit(PdrEvento.Brujula(rotacion != null))

        // Pasos: siempre por acelerómetro (sin permiso, sin la latencia del sensor de hardware).
        val acelerometro = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if (acelerometro != null) {
            fuente = FuentePasos.ACELEROMETRO
            sm.registerListener(listenerAcel, acelerometro, SensorManager.SENSOR_DELAY_GAME)
        } else {
            fuente = FuentePasos.ACELEROMETRO_SIN_SENSOR
            _eventos.tryEmit(PdrEvento.PasosPorAcelerometro("no_sensor"))
        }
        publicar()
    }

    fun detener() {
        if (!activo) return
        activo = false
        sm.unregisterListener(listenerRumbo)
        sm.unregisterListener(listenerAcel)
        publicar()
    }

    /** Llamar al destruir la pantalla que lo creó. */
    fun liberar() {
        detener()
        onAceleracion = null
    }

    // ── Sensores ───────────────────────────────

    private val matriz = FloatArray(9)

    private val listenerRumbo = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            SensorManager.getRotationMatrixFromVector(matriz, e.values)
            engine.onRumboSensor(rumboDesdeMatriz(matriz) + declinacion)
            val ahora = SystemClock.elapsedRealtime()
            if (ahora - ultimoRumboPublicadoMs >= 50) { // ~20 Hz basta para la UI
                ultimoRumboPublicadoMs = ahora
                publicar()
            }
        }

        override fun onAccuracyChanged(s: Sensor?, accuracy: Int) = Unit
    }

    private val listenerAcel = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            val t = SystemClock.elapsedRealtime()
            if (detector.procesar(e.values[0], e.values[1], e.values[2], t)) registrarPaso(t)
            if (t - ultimaAceleracionMs >= 50) {
                ultimaAceleracionMs = t
                onAceleracion?.invoke(detector.ultimaDesviacion)
            }
        }

        override fun onAccuracyChanged(s: Sensor?, accuracy: Int) = Unit
    }

    private fun registrarPaso(tMs: Long) {
        if (engine.onPaso(tMs)) publicar()
    }

    private fun actualizarDeclinacion() {
        val la = engine.lat ?: return
        val ln = engine.lng ?: return
        declinacion = GeomagneticField(
            la.toFloat(), ln.toFloat(), 0f, System.currentTimeMillis(),
        ).declination
    }

    private fun publicar() {
        _estado.value = PdrEstado(
            lat = engine.lat,
            lng = engine.lng,
            rumboGrados = engine.rumbo,
            pasos = engine.pasos,
            distanciaMetros = engine.distanciaMetros,
            velocidadMps = engine.velocidadMps,
            activo = activo,
            fuentePasos = fuente,
        )
    }
}

/**
 * Rumbo (grados, 0–360, norte magnético) hacia donde "avanza" el celular, según cómo lo lleve:
 *  - plano (la pantalla mira al cielo): hacia donde apunta la parte superior del celular;
 *  - en vertical: hacia donde apunta la cámara trasera.
 * Así el PDR sirve con el celular en la mano en cualquiera de las dos posturas.
 *
 * `r` es la matriz de `getRotationMatrixFromVector` (dispositivo → mundo: Este, Norte, Arriba).
 */
internal fun rumboDesdeMatriz(r: FloatArray): Float {
    val plano = abs(r[8]) > 0.7f
    val este = if (plano) r[1] else -r[2]
    val norte = if (plano) r[4] else -r[5]
    val grados = Math.toDegrees(atan2(este.toDouble(), norte.toDouble()))
    return ((grados + 360.0) % 360.0).toFloat()
}