package com.example.myapplication.domain.usecase

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** Resultado de una medición de calibración de la longitud de paso. */
sealed interface ResultadoCalibracion {

    /**
     * Medición aceptada. [longitudPasoM] es lo único que se guarda; [cadenciaPpm] y
     * [velocidadMps] son solo informativas (la longitud no depende de ellas).
     */
    data class Valido(
        val longitudPasoM: Double,
        val pasos: Int,
        val distanciaM: Double,
        val duracionS: Double,
        val cadenciaPpm: Double,
        val velocidadMps: Double,
    ) : ResultadoCalibracion

    /** Medición rechazada. [longitudPasoM] viene si se llegó a calcular (rango o pasos fuera de lo normal). */
    data class Invalido(
        val motivo: MotivoInvalido,
        val longitudPasoM: Double? = null,
    ) : ResultadoCalibracion
}

enum class MotivoInvalido { TRAMO_CORTO, POCOS_PASOS, PASO_MUY_CORTO, PASO_MUY_LARGO }

/**
 * Calibración de la longitud de paso con una sola pasada sobre un tramo de distancia conocida:
 * `longitud = distancia / pasos`. Lógica pura, sin Android.
 */
object CalibracionPaso {
    const val MIN_PASO_M = 0.40
    const val MAX_PASO_M = 1.20

    /** Pasos mínimos para fiarse de la medición. */
    const val MIN_PASOS = 15

    /** Tramo mínimo (con menos, el error de marcar A y B en el mapa pesa demasiado). */
    const val MIN_DISTANCIA_M = 10.0

    /** Tramo recomendado: más largo = menos error relativo al marcar A y B. */
    const val DISTANCIA_RECOMENDADA_M = 30.0

    private const val RADIO_TIERRA_M = 6_371_000.0

    /** Distancia sobre la esfera (haversine), en metros. Igual que `map.distance` de Leaflet. */
    fun distanciaEntre(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val f1 = Math.toRadians(lat1)
        val f2 = Math.toRadians(lat2)
        val df = Math.toRadians(lat2 - lat1)
        val dl = Math.toRadians(lng2 - lng1)
        val a = sin(df / 2).pow(2) + cos(f1) * cos(f2) * sin(dl / 2).pow(2)
        return 2 * RADIO_TIERRA_M * atan2(sqrt(a), sqrt(1 - a))
    }

    fun calcular(distanciaM: Double, pasos: Int, duracionS: Double): ResultadoCalibracion {
        if (distanciaM < MIN_DISTANCIA_M) return ResultadoCalibracion.Invalido(MotivoInvalido.TRAMO_CORTO)
        if (pasos < MIN_PASOS) return ResultadoCalibracion.Invalido(MotivoInvalido.POCOS_PASOS)

        val longitud = distanciaM / pasos
        if (longitud < MIN_PASO_M) {
            return ResultadoCalibracion.Invalido(MotivoInvalido.PASO_MUY_CORTO, longitud)
        }
        if (longitud > MAX_PASO_M) {
            return ResultadoCalibracion.Invalido(MotivoInvalido.PASO_MUY_LARGO, longitud)
        }
        return ResultadoCalibracion.Valido(
            longitudPasoM = longitud,
            pasos = pasos,
            distanciaM = distanciaM,
            duracionS = duracionS,
            cadenciaPpm = if (duracionS > 0) pasos * 60.0 / duracionS else 0.0,
            velocidadMps = if (duracionS > 0) distanciaM / duracionS else 0.0,
        )
    }
}