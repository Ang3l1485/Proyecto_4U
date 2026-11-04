package com.example.myapplication.domain.ruta

/**
 * Grafo de caminos del campus (FE-5.1; ARCHITECTURE §5.7, «Grafo y rutas»). Lógica pura, sin Android.
 *
 * Es el `grafo.json` que entrega el equipo, leído **tal cual**: la app no tiene ninguna función que cambie cómo está
 * construido (decisión del usuario, resuelve la decisión abierta 2). Lo lee y valida [LectorGrafo].
 */

/** Tipos de nodo de `grafo.json` (formato 1). Otro tipo se lee igual, con un aviso de [LectorGrafo]. */
object TiposNodo {
    const val CRUCE = "cruce"
    const val ENTRADA = "entrada"
}

/**
 * Un nodo: un cruce o la entrada a un lugar. [lugar] es un nombre **opcional e informativo** (decisión del usuario del
 * 2026-10-28): la meta de una ruta sale de las coordenadas del destino, no de este campo. Solo lo usan los destinos de
 * prueba por nombre del mapa (`Planificador.nodoConLugar`).
 */
data class Nodo(
    val id: String,
    val lat: Double,
    val lng: Double,
    val tipo: String,
    val lugar: String? = null,
) {
    val esEntrada: Boolean get() = tipo == TiposNodo.ENTRADA
}

/**
 * Una arista no dirigida entre los nodos [a] y [b]. [metros] es la longitud declarada en el archivo (la que usa la ruta
 * más corta). Una arista [bloqueada] no se usa nunca (ni para proyectar ni para la ruta); [accesible] y [tipo] se leen
 * pero hoy no cambian nada (todas son `camino` y accesibles).
 */
data class Arista(
    val id: String,
    val a: String,
    val b: String,
    val metros: Double,
    val tipo: String = "camino",
    val accesible: Boolean = true,
    val bloqueada: Boolean = false,
) {
    /** El extremo que no es [id], o `null` si [id] no es un extremo. */
    fun otro(id: String): String? = when (id) {
        a -> b
        b -> a
        else -> null
    }
}

/**
 * Grafo ya validado (lo construye [LectorGrafo]; las pruebas también pueden construirlo a mano). No valida nada por sí
 * mismo: [porId] toma el último nodo si un id se repite.
 */
class Grafo(
    val formato: Int,
    val version: Int,
    val actualizado: String?,
    val nodos: List<Nodo>,
    val aristas: List<Arista>,
) {
    val porId: Map<String, Nodo> = nodos.associateBy { it.id }

    /** Nodos de tipo `entrada` (informativo). */
    val entradas: List<Nodo> = nodos.filter { it.esEntrada }

    /** Aristas que se pueden recorrer (no `bloqueada`). */
    val usables: List<Arista> = aristas.filter { !it.bloqueada }

    /** Aristas usables por nodo. */
    val adyacencia: Map<String, List<Arista>> = buildMap<String, MutableList<Arista>> {
        for (ar in usables) {
            getOrPut(ar.a) { mutableListOf() }.add(ar)
            getOrPut(ar.b) { mutableListOf() }.add(ar)
        }
    }

    /** Los nombres de `lugar` (informativos) de los nodos, sin repetir, en el orden del archivo. */
    val lugares: List<String> = nodos.mapNotNull { it.lugar }.distinct()

    /** Suma de [Arista.metros] de todas las aristas. */
    val metrosTotales: Double get() = aristas.sumOf { it.metros }
}
