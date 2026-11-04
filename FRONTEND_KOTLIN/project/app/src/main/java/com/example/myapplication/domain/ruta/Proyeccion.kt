package com.example.myapplication.domain.ruta

import kotlin.math.hypot

/**
 * Un punto proyectado sobre una arista: el punto del segmento más cercano a la persona (no el nodo más cercano, que
 * podría mandarla hacia atrás). Es el **nodo virtual de partida** de la ruta.
 *
 * [t] ∈ [0, 1] es la fracción desde el nodo `a` de la [arista]; ([lat], [lng]) el punto del segmento; [distanciaM] la
 * distancia en línea recta de la persona a ese punto.
 */
data class PuntoEnArista(
    val arista: Arista,
    val t: Double,
    val lat: Double,
    val lng: Double,
    val distanciaM: Double,
) {
    /** Metros (de los declarados en la arista) desde el punto hasta el nodo `a`. */
    val metrosHastaA: Double get() = t * arista.metros

    /** Metros desde el punto hasta el nodo `b`. */
    val metrosHastaB: Double get() = (1.0 - t) * arista.metros
}

/** Proyección de una posición sobre la arista usable (no `bloqueada`) más cercana (FE-5.1; `ProyeccionTest`). */
object Proyeccion {

    /** La arista usable más cercana a ([lat], [lng]) y el punto del segmento; `null` si no hay aristas usables. */
    fun masCercana(grafo: Grafo, lat: Double, lng: Double): PuntoEnArista? {
        val plano = Geo.Plano(lat, lng)
        var mejor: PuntoEnArista? = null
        for (ar in grafo.usables) {
            val na = grafo.porId[ar.a] ?: continue
            val nb = grafo.porId[ar.b] ?: continue
            val ax = plano.x(na.lng)
            val ay = plano.y(na.lat)
            val bx = plano.x(nb.lng)
            val by = plano.y(nb.lat)
            val dx = bx - ax
            val dy = by - ay
            val largo2 = dx * dx + dy * dy
            // La persona está en el origen del plano (0, 0).
            val t = if (largo2 == 0.0) 0.0 else (((0.0 - ax) * dx + (0.0 - ay) * dy) / largo2).coerceIn(0.0, 1.0)
            val qx = ax + t * dx
            val qy = ay + t * dy
            val d = hypot(qx, qy)
            if (mejor == null || d < mejor.distanciaM) {
                mejor = PuntoEnArista(ar, t, plano.lat(qy), plano.lng(qx), d)
            }
        }
        return mejor
    }
}
