package com.example.myapplication.map

import com.example.myapplication.domain.ruta.GrafosDePrueba
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** FE-5.1, criterio C4 (en la JVM): el aviso de ruta del mapa público y los datos de prueba del APK de depuración. */
class RutaEnMapaTest {

    private val planificador = Planificador(GrafosDePrueba.real())

    @After
    fun limpiar() = PruebaMapa.limpiar()

    @Test
    fun avisoSegunElEstado() {
        assertNull(TextosRutaMapa.aviso(null, true, true, null))
        assertEquals(TextosRutaMapa.RUTAS_DESACTIVADAS, TextosRutaMapa.aviso("Bloque 35", false, true, null)!!.titulo)
        assertEquals(
            "Destino: Bloque 35. Toca el mapa para fijar tu posición y ver la ruta.",
            TextosRutaMapa.aviso("Bloque 35", true, false, null)!!.titulo,
        )
        assertEquals(
            "No tengo un camino hasta Auditorio: no está en el grafo.",
            TextosRutaMapa.aviso("Auditorio", true, true, ResultadoRuta.DestinoFueraDelGrafo)!!.titulo,
        )
        assertEquals("No encontré un camino hasta X.", TextosRutaMapa.aviso("X", true, true, ResultadoRuta.SinCamino)!!.titulo)
        // La ruta de validate51.py C4b (grafo versión 209).
        val r = planificador.calcular(6.201434, -75.578707, listOf("bloque35"), "bloque 35", null)
        assertEquals(
            AvisoRuta("Ruta a bloque 35: 29 m por el camino", "Camina 14 metros por el camino."),
            TextosRutaMapa.aviso("bloque 35", true, true, r),
        )
        // Un destino de prueba por coordenadas (Bloque 35 del backend) también tiene ruta.
        val c = planificador.calcular(6.201434, -75.578707, listOf("6.201286,-75.578834"), TextosRutaMapa.DESTINO_DE_PRUEBA, null)
        assertEquals("Ruta a Destino de prueba: 31 m por el camino", TextosRutaMapa.aviso("Destino de prueba", true, true, c)!!.titulo)
    }

    @Test
    fun nombreDeUnDestinoDePrueba() {
        assertEquals("bloque 35", TextosRutaMapa.nombrePrueba(planificador, "bloque35"))
        assertEquals(TextosRutaMapa.DESTINO_DE_PRUEBA, TextosRutaMapa.nombrePrueba(planificador, "6.201286,-75.578834"))
        assertEquals("cafeteria", TextosRutaMapa.nombrePrueba(planificador, "Cafetería"))
        assertEquals("Auditorio", TextosRutaMapa.nombrePrueba(planificador, "Auditorio"))
        assertEquals("bloque35", TextosRutaMapa.nombrePrueba(null, "bloque35"))
    }

    @Test
    fun posicionDePrueba() {
        assertEquals(6.201434 to -75.578427, PruebaMapa.leerPosicion("6.201434,-75.578427"))
        assertEquals(6.2 to -75.5, PruebaMapa.leerPosicion(" 6.2 , -75.5 "))
        assertNull(PruebaMapa.leerPosicion("6,2;-75,5"))
        assertNull(PruebaMapa.leerPosicion("6.2"))
        assertNull(PruebaMapa.leerPosicion("95,10"))
        assertNull(PruebaMapa.leerPosicion(null))
        PruebaMapa.fijar("  bloque35 ", "6.201434,-75.578427")
        assertEquals("bloque35", PruebaMapa.destino)
        assertEquals(6.201434 to -75.578427, PruebaMapa.posicion)
        PruebaMapa.fijar("", "x")
        assertNull(PruebaMapa.destino)
        assertNull(PruebaMapa.posicion)
    }
}
