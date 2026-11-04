package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.ruta.GrafosDePrueba.cuadrado
import com.example.myapplication.domain.ruta.GrafosDePrueba.lat
import com.example.myapplication.domain.ruta.GrafosDePrueba.lng
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * FE-5.1, criterio C2: la posición se proyecta sobre la **arista** más cercana (no el nodo más cercano) y la ruta más
 * corta va de ese nodo virtual de partida al nodo virtual de llegada (la proyección de las coordenadas del destino), sin
 * aristas bloqueadas.
 */
class ProyeccionRutaTest {

    private fun proyectar(g: Grafo, x: Double, y: Double) = Proyeccion.masCercana(g, lat(y), lng(x))!!

    private fun camino(g: Grafo, desde: Pair<Double, Double>, hasta: Pair<Double, Double>) =
        CalculoRuta.masCorta(g, proyectar(g, desde.first, desde.second), proyectar(g, hasta.first, hasta.second))

    @Test
    fun proyectaSobreElSegmentoConFraccionYDistancia() {
        val p = proyectar(cuadrado(), 10.0, -5.0)
        assertEquals("ab", p.arista.id)
        assertEquals(0.1, p.t, 0.002)
        assertEquals(5.0, p.distanciaM, 0.05)
        assertEquals(lat(0.0), p.lat, 1e-7)
        assertEquals(lng(10.0), p.lng, 1e-7)
        assertEquals(10.0, p.metrosHastaA, 0.2)
        assertEquals(90.0, p.metrosHastaB, 0.2)
    }

    @Test
    fun fueraDelSegmentoSeRecortaAlExtremo() {
        val p = proyectar(cuadrado(), -30.0, -40.0)
        assertEquals(0.0, p.t, 1e-9)
        assertEquals(50.0, p.distanciaM, 0.1)
    }

    @Test
    fun noUsaAristasBloqueadas() {
        // (105, 50) está a 5 m de B–C; con B–C bloqueada, lo más cerca son los extremos B o C (a ~50,25 m).
        val libre = proyectar(cuadrado(), 105.0, 50.0)
        assertEquals("bc", libre.arista.id)
        assertEquals(5.0, libre.distanciaM, 0.05)
        val bloqueada = proyectar(cuadrado(bloquearBC = true), 105.0, 50.0)
        assertEquals(50.25, bloqueada.distanciaM, 0.2)
    }

    @Test
    fun sinAristasUsablesNoHayProyeccion() {
        val g = Grafo(1, 1, null, cuadrado().nodos, cuadrado().aristas.map { it.copy(bloqueada = true) })
        assertNull(Proyeccion.masCercana(g, lat(0.0), lng(0.0)))
    }

    @Test
    fun laRutaSaleDelPuntoProyectadoNoDelNodoMasCercano() {
        // A 45 m de A y 55 m de B: el nodo más cercano es A, pero la ruta a C va hacia B (55 + 100), no hacia atrás.
        val c = camino(cuadrado(), 45.0 to -3.0, 100.0 to 100.0)!!
        assertEquals("B", c.nodos.first().id) // [B] o [B, C]: la meta está sobre C (empate exacto entre los dos)
        assertEquals(155.0, c.metros, 0.5)
    }

    @Test
    fun laMetaEsLaProyeccionDelDestinoEnMitadDeUnaArista() {
        // Destino (104, 60): se proyecta a 60 m de B sobre B–C; desde (45, −3): 55 + 60.
        val c = camino(cuadrado(), 45.0 to -3.0, 104.0 to 60.0)!!
        assertEquals("bc", c.fin.arista.id)
        assertEquals(0.6, c.fin.t, 0.002)
        assertEquals(4.0, c.fin.distanciaM, 0.05)
        assertEquals(listOf("B"), c.nodos.map { it.id })
        assertEquals(115.0, c.metros, 0.5)
    }

    @Test
    fun enLaMismaAristaVaDirecto() {
        val c = camino(cuadrado(), 10.0 to -5.0, 60.0 to 3.0)!!
        assertEquals(emptyList<String>(), c.nodos.map { it.id })
        assertEquals(50.0, c.metros, 0.3)
        // Hacia atrás en la misma arista, también directo.
        assertEquals(50.0, camino(cuadrado(), 60.0 to -5.0, 10.0 to 3.0)!!.metros, 0.3)
    }

    @Test
    fun evitaLasAristasBloqueadas() {
        val c = camino(cuadrado(bloquearBC = true), 45.0 to -3.0, 100.0 to 100.0)!!
        assertEquals(listOf("A", "D"), c.nodos.map { it.id }.take(2))
        assertEquals(245.0, c.metros, 0.5)
    }

    @Test
    fun sinCaminoDaNull() {
        // Con B–C y D–A bloqueadas, A–B y C–D quedan sueltas: de A–B no se llega a una meta sobre C–D.
        val base = cuadrado()
        val g = Grafo(
            1, 1, null, base.nodos,
            base.aristas.map { if (it.id == "bc" || it.id == "da") it.copy(bloqueada = true) else it },
        )
        assertNull(camino(g, 45.0 to -3.0, 50.0 to 103.0))
    }

    @Test
    fun enElDestinoLaRutaMideCero() {
        val c = camino(cuadrado(), 100.0 to 100.0, 100.0 to 100.0)!!
        assertEquals(0.0, c.metros, 0.01)
    }
}
