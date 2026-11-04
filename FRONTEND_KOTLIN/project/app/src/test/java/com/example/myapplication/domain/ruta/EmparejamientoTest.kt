package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.ruta.GrafosDePrueba.cuadrado
import com.example.myapplication.domain.ruta.GrafosDePrueba.lat
import com.example.myapplication.domain.ruta.GrafosDePrueba.lng
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.1, criterio C3 (en la JVM): los lugares del backend se emparejan con el grafo **por coordenadas** (el punto más
 * cercano del grafo es la meta); los nombres de `lugar` del grafo son informativos.
 */
class EmparejamientoTest {

    private fun lugar(id: String, nombre: String, lat: Double, lng: Double) =
        LugarDestino(id, nombre, CategoriaLugar.BLOQUE, lat, lng)

    @Test
    fun normalizaSinTildesNiSignos() {
        assertEquals("cafeconverso", EmparejarLugares.normalizar("Café Con.verso"))
        assertEquals("bloque35", EmparejarLugares.normalizar(" Bloque  35 "))
        assertEquals("cafeteria", EmparejarLugares.normalizar("CAFETERÍA"))
        assertEquals("bano", EmparejarLugares.normalizar("Baño"))
    }

    @Test
    fun cadaLugarConSuPuntoMasCercanoYSiQuedaLejos() {
        val lugares = listOf(
            lugar("cerca", "Cerca", lat(-5.0), lng(10.0)), // a 5 m de A–B
            lugar("lejos", "Lejos", lat(100.0), lng(140.0)), // a 40 m de C
            lugar("roto", "Sin coordenadas", Double.NaN, lng(0.0)),
        )
        val e = EmparejarLugares.emparejar(cuadrado(), lugares)
        assertEquals(listOf("cerca", "lejos", "roto"), e.map { it.lugar.id })
        assertEquals("ab", e[0].punto!!.arista.id)
        assertEquals(5.0, e[0].punto!!.distanciaM, 0.05)
        assertFalse(e[0].lejos)
        assertEquals(40.0, e[1].punto!!.distanciaM, 0.1)
        assertTrue(e[1].lejos)
        assertNull(e[2].punto)
        assertFalse(e[2].lejos)
        // Con otro umbral, «Lejos» deja de estarlo.
        assertFalse(EmparejarLugares.emparejar(cuadrado(), lugares, ParametrosRuta(fueraDelCaminoM = 50.0))[1].lejos)
    }

    @Test
    fun elBloque35DeDevQuedaJuntoAlGrafo() {
        // GET /v1/places en dev el 2026-10-28: «Bloque 35» en (6.201286, −75.578834), a ~2 m al sur del nodo n0007.
        val e = EmparejarLugares.emparejar(GrafosDePrueba.real(), listOf(lugar("b35", "Bloque 35", 6.201286, -75.578834)))
        val p = e.single().punto!!
        assertEquals("a0007", p.arista.id)
        assertTrue(p.distanciaM < 1.0)
        assertFalse(e.single().lejos)
    }
}
