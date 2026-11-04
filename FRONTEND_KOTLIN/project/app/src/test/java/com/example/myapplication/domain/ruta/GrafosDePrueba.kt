package com.example.myapplication.domain.ruta

import java.io.File
import kotlin.math.cos

/**
 * Ayudas de las pruebas de FE-5.1: grafos sintéticos en metros (x al este, y al norte) alrededor de un origen del
 * campus, y el `grafo.json` real de `assets/`.
 */
object GrafosDePrueba {
    const val LAT0 = 6.2010
    const val LNG0 = -75.5785
    private const val M_POR_GRADO = 111_194.93 // R · π / 180 con R = 6 371 000 m

    fun lat(y: Double) = LAT0 + y / M_POR_GRADO
    fun lng(x: Double) = LNG0 + x / (M_POR_GRADO * cos(Math.toRadians(LAT0)))

    fun nodo(id: String, x: Double, y: Double, lugar: String? = null) =
        Nodo(id, lat(y), lng(x), if (lugar != null) TiposNodo.ENTRADA else TiposNodo.CRUCE, lugar)

    fun arista(id: String, a: Nodo, b: Nodo, bloqueada: Boolean = false) =
        Arista(id, a.id, b.id, Geo.distancia(a.lat, a.lng, b.lat, b.lng), bloqueada = bloqueada)

    /**
     * Cuadrado de 100 m: A(0, 0) – B(100, 0) – C(100, 100) – D(0, 100) – A. C es la entrada de «Meta». Con
     * [bloquearBC] la arista B–C queda bloqueada; con [entradaE] hay otra entrada de «Meta» en E(150, 0), unida a B.
     */
    fun cuadrado(bloquearBC: Boolean = false, entradaE: Boolean = false): Grafo {
        val a = nodo("A", 0.0, 0.0)
        val b = nodo("B", 100.0, 0.0)
        val c = nodo("C", 100.0, 100.0, lugar = "Meta")
        val d = nodo("D", 0.0, 100.0)
        val nodos = mutableListOf(a, b, c, d)
        val aristas = mutableListOf(
            arista("ab", a, b),
            arista("bc", b, c, bloqueada = bloquearBC),
            arista("cd", c, d),
            arista("da", d, a),
        )
        if (entradaE) {
            val e = nodo("E", 150.0, 0.0, lugar = "Meta")
            nodos += e
            aristas += arista("be", b, e)
        }
        return Grafo(1, 1, null, nodos, aristas)
    }

    /** Camino A(0, 0) → B(100, 0) → C (a [anguloGrados] de giro desde el este, positivo a la izquierda), C = «Meta». */
    fun codo(anguloGrados: Double): Grafo {
        val r = Math.toRadians(anguloGrados)
        val a = nodo("A", 0.0, 0.0)
        val b = nodo("B", 100.0, 0.0)
        val c = nodo("C", 100.0 + 50.0 * cos(r), 50.0 * kotlin.math.sin(r), lugar = "Meta")
        return Grafo(1, 1, null, listOf(a, b, c), listOf(arista("ab", a, b), arista("bc", b, c)))
    }

    /** El `grafo.json` de la app (las pruebas corren con el módulo `app/` como directorio actual). */
    fun textoReal(): String = File("src/main/assets/grafo.json").readText(Charsets.UTF_8)

    fun real(): Grafo = (LectorGrafo.leer(textoReal()) as CargaGrafo.Valido).grafo
}
