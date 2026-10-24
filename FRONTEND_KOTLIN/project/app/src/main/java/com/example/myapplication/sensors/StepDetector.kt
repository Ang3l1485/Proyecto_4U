package com.example.myapplication.sensors

import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Detector de pasos por acelerómetro. Es la **fuente única de pasos** del PDR (el sensor de hardware
 * `TYPE_STEP_DETECTOR` se descartó: confirma una secuencia antes de avisar y tarda 1–3 s en reaccionar).
 * Lógica pura (sin Android).
 *
 * Algoritmo:
 *  1. Magnitud de la aceleración menos la gravedad, con signo, y filtro pasa-bajos suave (quita ruido).
 *  2. Se cuenta el paso en el **flanco de subida** del pico (cuando cruza el umbral), no al terminar
 *     el pico: la latencia es de unas pocas muestras (~50–100 ms a 50 Hz).
 *  3. Histéresis: no vuelve a armarse hasta bajar del 60 % del umbral.
 *  4. Pausa mínima entre pasos ([pausaMs]) contra rebotes.
 *  5. Umbral adaptativo: la mitad del pico típico reciente (limitado a [UMBRAL_MIN]…[UMBRAL_MAX]),
 *     así sirve para pasos suaves y fuertes y distintas formas de llevar el teléfono.
 *
 * Solo cuentan los picos positivos (el golpe del talón): el valle posterior no genera otro paso.
 */
class StepDetector(
    private val umbralInicial: Float = UMBRAL,
    private val pausaMs: Long = PAUSA_MS,
) {
    companion object {
        const val GRAVEDAD = 9.81f

        /** Umbral de partida (m/s²); también es el que dibuja la gráfica de `app.js`. */
        const val UMBRAL = 1.4f
        const val UMBRAL_MIN = 1.1f
        const val UMBRAL_MAX = 4.0f
        const val PAUSA_MS = 250L

        /** Peso de la muestra nueva en el filtro pasa-bajos (1 = sin filtro). */
        const val FILTRO = 0.5f

        /** Peso del último pico en el pico típico (media móvil exponencial). */
        const val PESO_PICO = 0.3f

        /** Fracción del pico típico que fija el umbral. */
        const val FACTOR_UMBRAL = 0.5f

        /** Picos mayores se recortan para que un golpe aislado no suba el umbral. */
        const val PICO_MAX = 8f
    }

    /** Desviación absoluta (filtrada) respecto a la gravedad (m/s²). Sirve para la gráfica. */
    var ultimaDesviacion: Float = 0f
        private set

    private var filtrada = 0f
    private var hayMuestra = false
    private var sobreUmbral = false
    private var picoActual = 0f
    private var picoContado = false
    private var picoTipico = umbralInicial / FACTOR_UMBRAL
    private var ultimoPasoMs = 0L

    /** Umbral vigente (m/s²). */
    val umbral: Float
        get() = (picoTipico * FACTOR_UMBRAL).coerceIn(UMBRAL_MIN, UMBRAL_MAX)

    /**
     * Procesa una muestra del acelerómetro (con gravedad incluida).
     * Devuelve `true` si esta muestra marca un paso. Con [detectar] en `false` solo actualiza
     * [ultimaDesviacion].
     */
    fun procesar(x: Float, y: Float, z: Float, tMs: Long, detectar: Boolean = true): Boolean {
        val bruta = sqrt(x * x + y * y + z * z) - GRAVEDAD
        if (!hayMuestra) {
            filtrada = bruta
            hayMuestra = true
        } else {
            filtrada += FILTRO * (bruta - filtrada)
        }
        ultimaDesviacion = abs(filtrada)
        if (!detectar) return false

        val u = umbral
        var paso = false
        if (!sobreUmbral) {
            if (filtrada > u) {
                sobreUmbral = true
                picoActual = filtrada
                picoContado = false
                if (tMs - ultimoPasoMs > pausaMs) {
                    ultimoPasoMs = tMs
                    picoContado = true
                    paso = true
                }
            }
        } else {
            if (filtrada > picoActual) picoActual = filtrada
            if (filtrada < u * 0.6f) {
                sobreUmbral = false
                if (picoContado) {
                    picoTipico += PESO_PICO * (min(picoActual, PICO_MAX) - picoTipico)
                }
            }
        }
        return paso
    }

    fun reiniciar() {
        filtrada = 0f
        hayMuestra = false
        sobreUmbral = false
        picoActual = 0f
        picoContado = false
        picoTipico = umbralInicial / FACTOR_UMBRAL
        ultimoPasoMs = 0L
        ultimaDesviacion = 0f
    }
}