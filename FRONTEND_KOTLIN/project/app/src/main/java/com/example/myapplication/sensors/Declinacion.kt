package com.example.myapplication.sensors

import android.hardware.GeomagneticField
import com.example.myapplication.domain.model.SesionDeNavegacion

/**
 * Declinación magnética (grados, positiva hacia el este) para pasar el acimut de `EscucharOrientacion` (norte magnético)
 * a norte verdadero con `ConversionRumbo.magneticoAVerdadero` (FE-3.2; ARCHITECTURE §5.10, «Rumbo»; ADR-FE-25).
 *
 * El escaneo no sabe todavía dónde está la persona: usa la última posición de `SesionDeNavegacion` y, si no hay, el
 * centro del campus ([LAT_CAMPUS], [LNG_CAMPUS]). La declinación cambia muy poco en unos kilómetros (en Medellín es
 * ≈ −7°, a verificar en el teléfono con `GeomagneticField`), así que el centro del campus basta. Si `GeomagneticField`
 * falla, 0.
 */
internal object Declinacion {
    /** Centro aproximado del campus (EAFIT), el mismo `POSICION_CAMPUS` de `validate31.py`. */
    const val LAT_CAMPUS = 6.2006
    const val LNG_CAMPUS = -75.5783

    /** Altitud aproximada de Medellín (m); su efecto en la declinación es despreciable. */
    const val ALTITUD_CAMPUS_M = 1500f

    fun grados(lat: Double, lng: Double, ahoraMs: Long = System.currentTimeMillis()): Double =
        runCatching {
            GeomagneticField(lat.toFloat(), lng.toFloat(), ALTITUD_CAMPUS_M, ahoraMs).declination.toDouble()
        }.getOrDefault(0.0)

    /** Con la última posición conocida de `SesionDeNavegacion` o, sin ella, con el centro del campus. */
    fun paraLaUltimaPosicion(): Double {
        val p = SesionDeNavegacion.ultimaPosicion()
        return if (p != null) grados(p.lat, p.lng) else grados(LAT_CAMPUS, LNG_CAMPUS)
    }
}
