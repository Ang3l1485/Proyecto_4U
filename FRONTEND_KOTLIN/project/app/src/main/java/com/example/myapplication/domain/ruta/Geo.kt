package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.usecase.CalibracionPaso
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * Geometría para el grafo (FE-5.1). Distancias con la haversine de `CalibracionPaso.distanciaEntre` (R = 6 371 000 m,
 * la de Leaflet) y, para proyectar un punto sobre una arista, un plano local equirectangular (x al este, y al norte, en
 * metros): en los ~650 m del grafo el error es de milímetros.
 */
object Geo {

    const val RADIO_TIERRA_M = 6_371_000.0

    /** Distancia en metros (haversine). */
    fun distancia(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double =
        CalibracionPaso.distanciaEntre(lat1, lng1, lat2, lng2)

    /** Rumbo inicial de (lat1, lng1) a (lat2, lng2), en [0, 360), 0 = norte, sentido horario. Sin redondear. */
    fun rumbo(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val f1 = Math.toRadians(lat1)
        val f2 = Math.toRadians(lat2)
        val dl = Math.toRadians(lng2 - lng1)
        val y = sin(dl) * cos(f2)
        val x = cos(f1) * sin(f2) - sin(f1) * cos(f2) * cos(dl)
        val g = Math.toDegrees(atan2(y, x))
        return ((g % 360.0) + 360.0) % 360.0
    }

    /** `a − b` en (−180, 180]: positivo = [a] queda a la derecha (sentido horario) de [b]. */
    fun diferencia(a: Double, b: Double): Double {
        var d = (a - b) % 360.0
        if (d <= -180.0) d += 360.0
        if (d > 180.0) d -= 360.0
        return d
    }

    /** Plano local alrededor de ([lat0], [lng0]). */
    class Plano(private val lat0: Double, private val lng0: Double) {
        private val kx = Math.toRadians(1.0) * RADIO_TIERRA_M * cos(Math.toRadians(lat0))
        private val ky = Math.toRadians(1.0) * RADIO_TIERRA_M

        fun x(lng: Double): Double = (lng - lng0) * kx
        fun y(lat: Double): Double = (lat - lat0) * ky
        fun lat(y: Double): Double = lat0 + y / ky
        fun lng(x: Double): Double = lng0 + x / kx
    }
}
