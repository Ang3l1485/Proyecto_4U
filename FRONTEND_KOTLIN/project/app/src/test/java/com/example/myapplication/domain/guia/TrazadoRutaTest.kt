package com.example.myapplication.domain.guia

import com.example.myapplication.domain.ruta.GrafosDePrueba
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import com.example.myapplication.domain.ruta.Ruta
import com.example.myapplication.domain.ruta.TipoInstruccion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.3: el avance sobre la ruta en la escala de `Instruccion.desdeM` (dentro y fuera del camino) y el desvío lateral.
 */
class TrazadoRutaTest {

    private fun ruta(planificador: Planificador, x: Double, y: Double): Ruta {
        val g = GrafosDePrueba
        val r = planificador.calcular(g.lat(y), g.lng(x), g.lat(100.0), g.lng(100.0), "Meta", null)
        return (r as ResultadoRuta.Encontrada).ruta
    }

    @Test
    fun dentroDelCaminoElAvanceEmpiezaEnElPuntoProyectado() {
        // 5 m al sur de la arista A–B, en x = 50: la ruta empieza en (50, 0) y va por B hasta C (150 m).
        val r = ruta(Planificador(GrafosDePrueba.cuadrado()), 50.0, -5.0)
        assertFalse(r.fueraDelCamino)
        val t = TrazadoRuta(r)
        assertEquals(r.instrucciones.last().desdeM, t.largoM, 0.01)
        assertEquals(150.0, t.largoM, 0.5)
        val g = GrafosDePrueba
        val enB = t.proyectar(g.lat(-5.0), g.lng(100.0))
        assertEquals(50.0, enB.avanceM, 0.3) // B
        assertEquals(5.0, enB.desvioM, 0.2)
        val giro = r.instrucciones.first { it.tipo == TipoInstruccion.GIRO }
        assertEquals(giro.desdeM, enB.avanceM, 0.3)
    }

    @Test
    fun aMenosDeMedioMetroDelCaminoElLargoSigueSiendoElDeLasInstrucciones() {
        // 0,3 m al sur de A–B: el punto proyectado se junta con el siguiente (FE-5.1 0.17.0 le pasa sus metros).
        val r = ruta(Planificador(GrafosDePrueba.cuadrado()), 50.0, -0.3)
        val t = TrazadoRuta(r)
        assertEquals(r.instrucciones.last().desdeM, t.largoM, 0.01)
        assertEquals(r.instrucciones.first { it.tipo == TipoInstruccion.GIRO }.desdeM, 50.0, 0.3)
    }

    @Test
    fun fueraDelCaminoCuentaElTramoHastaElCamino() {
        // 30 m al sur de A–B: primero «ve hasta el camino» (30 m), luego 50 + 100.
        val r = ruta(Planificador(GrafosDePrueba.cuadrado()), 50.0, -30.0)
        assertTrue(r.fueraDelCamino)
        val t = TrazadoRuta(r)
        assertEquals(r.puntos, t.puntos)
        assertEquals(180.0, t.largoM, 0.5)
        assertEquals(r.instrucciones.last().desdeM, t.largoM, 0.01)
        val inicio = t.proyectar(r.puntos.first().lat, r.puntos.first().lng)
        assertEquals(0.0, inicio.avanceM, 0.01)
        assertEquals(0.0, inicio.desvioM, 0.01)
    }

    @Test
    fun puntoEnYProyectarSonInversos() {
        val r = ruta(Planificador(GrafosDePrueba.cuadrado()), 50.0, -5.0)
        val t = TrazadoRuta(r)
        for (m in listOf(0.0, 12.5, 49.0, 50.0, 51.0, 99.9, 149.0)) {
            val (lat, lng) = t.puntoEn(m)
            val p = t.proyectar(lat, lng, m)
            assertEquals("avance en $m", m, p.avanceM, 0.05)
            assertEquals(0.0, p.desvioM, 0.05)
        }
        // Fuera de rango: se recorta a los extremos.
        assertEquals(t.puntoEn(t.largoM), t.puntoEn(t.largoM + 50.0))
    }

    @Test
    fun conAvanceAnteriorEligeElTramoMasParecidoSiHayEmpate() {
        // En la esquina B (avance 50) están empatados el final de A–B y el inicio de B–C: con avance anterior 49,
        // queda en 50; sin avance anterior, también (el mismo punto); lejos de la esquina gana el más cercano.
        val r = ruta(Planificador(GrafosDePrueba.cuadrado()), 50.0, -5.0)
        val t = TrazadoRuta(r)
        val g = GrafosDePrueba
        val p = t.proyectar(g.lat(1.0), g.lng(99.0), avanceAnterior = 49.0)
        assertTrue(p.avanceM in 49.0..51.5)
        val lejos = t.proyectar(g.lat(80.0), g.lng(101.0), avanceAnterior = 10.0)
        assertEquals(130.0, lejos.avanceM, 0.5)
    }
}
