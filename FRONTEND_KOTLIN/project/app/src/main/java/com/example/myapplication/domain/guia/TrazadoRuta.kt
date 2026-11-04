package com.example.myapplication.domain.guia

import com.example.myapplication.domain.ruta.Geo
import com.example.myapplication.domain.ruta.PuntoRuta
import com.example.myapplication.domain.ruta.Ruta
import kotlin.math.hypot

/**
 * Dónde está la persona respecto a la ruta: [avanceM] = metros por la ruta desde su inicio hasta el punto más cercano
 * (en la misma escala que `Instruccion.desdeM`); [desvioM] = distancia en línea recta de la persona a ese punto
 * ([lat], [lng]); [segmento] = índice del tramo de la polilínea.
 */
data class PosicionEnRuta(val avanceM: Double, val desvioM: Double, val lat: Double, val lng: Double, val segmento: Int)

/**
 * La polilínea de una [Ruta] en la escala de sus instrucciones (FE-5.3; `TrazadoRutaTest`).
 *
 * `Instruccion.desdeM` se mide desde el inicio de la ruta: desde la persona si está fuera del camino
 * (`fueraDelCamino`, con el tramo hasta el camino) o desde el punto proyectado (`Ruta.inicio`) si no. [puntos] es esa
 * polilínea: `Ruta.puntos` tal cual en el primer caso; en el segundo, `Ruta.inicio` seguido de los puntos del camino.
 * Los metros de cada tramo son los declarados en las aristas (`PuntoRuta.metrosDesdeAnterior`), así que [largoM] es la
 * `desdeM` de la llegada.
 */
class TrazadoRuta(val ruta: Ruta) {

    val puntos: List<PuntoRuta> = polilinea(ruta)

    /** Metros acumulados hasta cada punto de [puntos]. */
    private val acumulado: DoubleArray = DoubleArray(puntos.size).also { a ->
        for (i in 1 until puntos.size) a[i] = a[i - 1] + puntos[i].metrosDesdeAnterior
    }

    val largoM: Double get() = acumulado.lastOrNull() ?: 0.0

    /**
     * Proyecta ([lat], [lng]) sobre el tramo más cercano. Con [avanceAnterior], prefiere el tramo más cercano cuyo
     * avance esté a ≤ [VENTANA_M] del anterior si está a menos de [EMPATE_M] del mejor (no salta a otra parte de una
     * ruta que vuelve sobre sí misma). Con un solo punto, ese punto.
     */
    fun proyectar(lat: Double, lng: Double, avanceAnterior: Double? = null): PosicionEnRuta {
        if (puntos.size < 2) {
            val p = puntos.first()
            return PosicionEnRuta(0.0, Geo.distancia(lat, lng, p.lat, p.lng), p.lat, p.lng, 0)
        }
        val plano = Geo.Plano(lat, lng)
        val candidatos = (0 until puntos.size - 1).map { i ->
            val a = puntos[i]
            val b = puntos[i + 1]
            val ax = plano.x(a.lng)
            val ay = plano.y(a.lat)
            val dx = plano.x(b.lng) - ax
            val dy = plano.y(b.lat) - ay
            val largo2 = dx * dx + dy * dy
            val t = if (largo2 == 0.0) 0.0 else ((-ax * dx - ay * dy) / largo2).coerceIn(0.0, 1.0)
            val qx = ax + t * dx
            val qy = ay + t * dy
            PosicionEnRuta(
                avanceM = acumulado[i] + t * b.metrosDesdeAnterior,
                desvioM = hypot(qx, qy),
                lat = plano.lat(qy),
                lng = plano.lng(qx),
                segmento = i,
            )
        }
        val mejor = candidatos.minBy { it.desvioM }
        if (avanceAnterior == null) return mejor
        // El más cercano dentro de la ventana [avanceAnterior − VENTANA_M, avanceAnterior + VENTANA_M], si está a menos
        // de EMPATE_M del mejor; si no, el mejor. En una esquina gana el más cercano (no se queda ni se adelanta).
        val enVentana = candidatos.filter { kotlin.math.abs(it.avanceM - avanceAnterior) <= VENTANA_M }
            .minByOrNull { it.desvioM }
        return if (enVentana != null && enVentana.desvioM <= mejor.desvioM + EMPATE_M) enVentana else mejor
    }

    /** El punto de la ruta a [avanceM] metros del inicio (recortado a [0, [largoM]]); lo usa el modo de simulación. */
    fun puntoEn(avanceM: Double): Pair<Double, Double> {
        if (puntos.size < 2) return puntos.first().let { it.lat to it.lng }
        val a = avanceM.coerceIn(0.0, largoM)
        var i = 1
        while (i < puntos.size - 1 && acumulado[i] < a) i++
        val p = puntos[i - 1]
        val q = puntos[i]
        val m = q.metrosDesdeAnterior
        val t = if (m <= 0.0) 1.0 else ((a - acumulado[i - 1]) / m).coerceIn(0.0, 1.0)
        return (p.lat + t * (q.lat - p.lat)) to (p.lng + t * (q.lng - p.lng))
    }

    companion object {
        /** Tramos a menos de esto (m) del más cercano se consideran empatados. */
        const val EMPATE_M = 2.0

        /** Ventana (m) alrededor del avance anterior en la que se prefiere el tramo. */
        const val VENTANA_M = 20.0

        private fun polilinea(ruta: Ruta): List<PuntoRuta> {
            if (ruta.fueraDelCamino) return ruta.puntos
            val ini = ruta.inicio
            val resto = ruta.puntos.drop(1) // el primero es la persona
            val sinInicio = when {
                resto.isEmpty() -> resto
                resto.first().lat == ini.lat && resto.first().lng == ini.lng -> resto.drop(1)
                // El punto proyectado quedó a menos de puntoRepetidoM de la persona y se juntó con el siguiente (desde
                // FE-5.1 0.17.0 sus metros pasan al siguiente): se le quitan, porque desdeM empieza en el proyectado.
                else -> {
                    val primero = resto.first()
                    val m = (primero.metrosDesdeAnterior - ini.distanciaM).coerceAtLeast(0.0)
                    listOf(primero.copy(metrosDesdeAnterior = m)) + resto.drop(1)
                }
            }
            return listOf(PuntoRuta(ini.lat, ini.lng, 0.0)) + sinInicio
        }
    }
}
