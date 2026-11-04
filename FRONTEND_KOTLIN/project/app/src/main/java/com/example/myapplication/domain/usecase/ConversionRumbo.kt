package com.example.myapplication.domain.usecase

import kotlin.math.roundToLong

/**
 * Rumbos del contrato (backend ADR-BE-12; ARCHITECTURE §5.10, «Rumbo»): grados en [0, 360), **norte verdadero**,
 * sentido horario. El escaneo 360° (6.2) lee el acimut **magnético** de `EscucharOrientacion` en (−180, 180]: antes de
 * enviarlo se le suma la declinación magnética (`GeomagneticField`, positiva hacia el este). Lógica pura: la prueba
 * `ConversionRumboTest` (FE-3.2, criterio C2).
 */
object ConversionRumbo {

    /**
     * Cualquier ángulo finito → [0, 360) redondeado a 0,1°. Lo que el redondeo lleve a 360,0 sale como 0,0 (359,96 →
     * 0,0), porque el backend rechaza 360. No acepta `NaN` ni infinitos ([IllegalArgumentException]).
     */
    fun normalizar(grados: Double): Double {
        require(grados.isFinite()) { "rumbo no finito: $grados" }
        val r = ((grados % 360.0) + 360.0) % 360.0
        val redondeado = (r * 10.0).roundToLong() / 10.0
        return if (redondeado >= 360.0) 0.0 else redondeado
    }

    /**
     * Acimut magnético (−180…180, el de `EscucharOrientacion`) → rumbo verdadero [0, 360):
     * `(acimut + declinación + 360) % 360`, redondeado a 0,1°. Con la declinación de Medellín (≈ −7°, oeste), 3° magnético
     * es ≈ 356° verdadero.
     */
    fun magneticoAVerdadero(acimutMagnetico: Double, declinacionGrados: Double): Double =
        normalizar(acimutMagnetico + declinacionGrados)

    /** Diferencia angular `a − b` en (−180, 180] (180 y −180 dan 180). */
    fun diferencia(a: Double, b: Double): Double {
        var d = (a - b) % 360.0
        if (d > 180.0) d -= 360.0
        if (d <= -180.0) d += 360.0
        return d
    }
}
