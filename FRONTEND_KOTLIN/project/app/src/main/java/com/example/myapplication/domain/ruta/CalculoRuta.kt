package com.example.myapplication.domain.ruta

import java.util.PriorityQueue

/**
 * Camino más corto por el grafo entre dos puntos proyectados: de [inicio] (nodo virtual de partida) a [fin] (nodo
 * virtual de llegada). [nodos] son los nodos del grafo que se cruzan, en orden (vacío si los dos puntos están en la
 * misma arista y lo más corto es ir directo por ella); [metros] es la longitud por el grafo entre los dos puntos (con los
 * metros declarados; sin el tramo de la persona hasta el camino ni el del camino hasta el destino).
 */
data class Camino(
    val inicio: PuntoEnArista,
    val fin: PuntoEnArista,
    val nodos: List<Nodo>,
    val metros: Double,
)

/**
 * Ruta más corta (Dijkstra) en el teléfono, sin red (FE-5.1; `ProyeccionRutaTest`). Los dos extremos son puntos
 * proyectados sobre aristas: el de partida se une a los nodos `a` y `b` de su arista con `t · metros` y
 * `(1 − t) · metros`, y el de llegada igual con los de la suya. Si los dos están en la misma arista, también cuenta ir
 * directo por ella (`|t₁ − t₂| · metros`). Solo se usan aristas no `bloqueada`. Empates: gana ir directo y, entre los dos
 * extremos de la arista de llegada, el que tenga menor id (resultado estable).
 */
object CalculoRuta {

    fun masCorta(grafo: Grafo, inicio: PuntoEnArista, fin: PuntoEnArista): Camino? {
        val dist = HashMap<String, Double>()
        val previo = HashMap<String, String?>()
        val cola = PriorityQueue<Pair<Double, String>>(compareBy<Pair<Double, String>> { it.first }.thenBy { it.second })

        fun relajar(id: String, d: Double, desde: String?) {
            val actual = dist[id]
            if (actual == null || d < actual) {
                dist[id] = d
                previo[id] = desde
                cola.add(d to id)
            }
        }

        relajar(inicio.arista.a, inicio.metrosHastaA, null)
        relajar(inicio.arista.b, inicio.metrosHastaB, null)
        val cerrados = HashSet<String>()
        while (cola.isNotEmpty()) {
            val (d, id) = cola.poll()!!
            if (!cerrados.add(id)) continue
            if (d > (dist[id] ?: Double.MAX_VALUE)) continue
            for (ar in grafo.adyacencia[id].orEmpty()) {
                val otro = ar.otro(id) ?: continue
                if (otro in cerrados) continue
                relajar(otro, d + ar.metros, id)
            }
        }

        // Candidatos: por cada extremo de la arista de llegada, y directo si comparten arista.
        val candidatos = listOf(fin.arista.a to fin.metrosHastaA, fin.arista.b to fin.metrosHastaB)
            .mapNotNull { (id, resto) -> dist[id]?.let { Triple(id, it + resto, it) } }
            .sortedWith(compareBy<Triple<String, Double, Double>> { it.second }.thenBy { it.first })
        val directo = if (inicio.arista.id == fin.arista.id) kotlin.math.abs(inicio.t - fin.t) * fin.arista.metros else null
        val mejor = candidatos.firstOrNull()
        if (directo != null && (mejor == null || directo <= mejor.second)) {
            return Camino(inicio, fin, emptyList(), directo)
        }
        mejor ?: return null
        val ids = ArrayDeque<String>()
        var cursor: String? = mejor.first
        while (cursor != null) {
            ids.addFirst(cursor)
            cursor = previo[cursor]
        }
        return Camino(inicio, fin, ids.mapNotNull { grafo.porId[it] }, mejor.second)
    }
}
