package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.model.UbicacionEstimada
import com.example.myapplication.domain.usecase.DescribirUbicacion
import com.example.myapplication.map.TextosRutaMapa
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.1, criterio C4 (en la JVM): con el `grafo.json` real (versión 209), la ruta de la validación en casa
 * (`validate51.py`: destino de prueba `bloque35` y posición 6.201434, −75.578707, sobre la arista a0032 n0002–n0008), la
 * meta por las coordenadas del destino y lo que dice la vista 6.3 con ruta y sin ella.
 */
class PlanificadorTest {

    private val planificador = Planificador(GrafosDePrueba.real())

    /** La misma posición que `POSICION_PRUEBA` de `validate51.py`. */
    private val latPrueba = 6.201434
    private val lngPrueba = -75.578707

    /** «Bloque 35» de `GET /v1/places` en `dev` (2026-10-28): ~2 m al sur del nodo n0007. */
    private val bloque35 = LugarDestino("b35", "Bloque 35", CategoriaLugar.BLOQUE, 6.201286, -75.578834)

    @Test
    fun rutaDeLaValidacionEnCasa() {
        // Destino de prueba por texto: el `lugar` informativo «bloque 35» del nodo n0007 da sus coordenadas.
        val r = planificador.calcular(latPrueba, lngPrueba, listOf("bloque35"), "bloque 35", null)
        val ruta = (r as ResultadoRuta.Encontrada).ruta
        assertEquals("a0032", ruta.inicio.arista.id)
        assertTrue(ruta.metrosAlCamino < 1.0)
        assertTrue(ruta.fin.distanciaM < 0.01)
        assertFalse(ruta.destinoLejos)
        assertEquals(28.7, ruta.metros, 0.3)
        assertEquals(6.2013034, ruta.puntos.last().lat, 1e-6) // n0007
        assertEquals(
            listOf("Camina 14 metros por el camino.", "Gira a la izquierda y sigue recto 14 metros.", "Has llegado a bloque 35."),
            ruta.instrucciones.map { it.texto },
        )
        // Lo que muestra el aviso del mapa y lo que busca validate51.py C4b.
        assertEquals("Ruta a bloque 35: 29 m por el camino", TextosRutaMapa.titulo("bloque 35", ruta.metros))
    }

    @Test
    fun laMetaSaleDeLasCoordenadasDelLugar() {
        // Bloque 35 del backend se proyecta sobre a0007 (n0007–n0025), ~1,9 m más allá de n0007.
        val ruta = planificador.rutaA(bloque35, latPrueba, lngPrueba, null)!!
        assertEquals("a0007", ruta.fin.arista.id)
        assertEquals(30.7, ruta.metros, 0.3)
        assertEquals("Gira a la izquierda y sigue recto 16 metros.", ruta.instrucciones[1].texto)
        assertEquals("Has llegado a Bloque 35.", ruta.instrucciones.last().texto)
    }

    @Test
    fun laPrimeraDependeDelRumbo() {
        val norte = planificador.rutaA(bloque35, latPrueba, lngPrueba, 0.0)!!
        assertEquals("Gira a tu izquierda y sigue recto 14 metros.", norte.primera.texto)
        val oeste = planificador.rutaA(bloque35, latPrueba, lngPrueba, 270.0)!!
        assertEquals("Sigue recto 14 metros.", oeste.primera.texto)
    }

    @Test
    fun cualquierLugarTieneRutaAunqueElGrafoNoLoNombre() {
        // Un lugar inventado ~40 m al oeste de n0002 (fuera del grafo): llega al punto más cercano y dice cuánto falta.
        val lejos = LugarDestino("x", "Auditorio", CategoriaLugar.AUDITORIO, 6.2014317, -75.5791977)
        val ruta = planificador.rutaA(lejos, latPrueba, lngPrueba, null)!!
        assertTrue(ruta.destinoLejos)
        assertEquals(40.0, ruta.metrosAlDestino, 2.0)
        assertTrue(ruta.instrucciones.last().texto, ruta.instrucciones.last().texto.startsWith(
            "Has llegado al punto del camino más cercano a Auditorio. Está a ",
        ))
        assertTrue(ruta.instrucciones.last().texto.endsWith(" en línea recta, al frente."))
    }

    @Test
    fun jsonParaElMapa() {
        val ruta = planificador.rutaA(bloque35, latPrueba, lngPrueba, null)!!
        val o = JsonParser.parseString(ruta.json()).asJsonObject
        assertEquals("Bloque 35", o.get("destino").asString)
        assertEquals(30.7, o.get("metros").asDouble, 0.3)
        assertEquals("Camina 14 metros por el camino.", o.get("primera").asString)
        val puntos = o.getAsJsonArray("puntos")
        assertEquals(ruta.puntos.size, puntos.size())
        assertEquals(ruta.fin.lat, puntos.last().asJsonArray[0].asDouble, 1e-9)
    }

    private fun ubicadoEn(lat: Double, lng: Double) = UbicacionEstimada(
        ResultadoUbicacion.Ubicado(
            posicion = PosicionEstimada(lat, lng, 5.0),
            confianza = 0.8,
            nivel = NivelConfianza.ALTA,
            correccionRumboGrados = -10.0,
            lugarCercano = LugarCercano("b38", "Bloque 38", 15.0),
            referencias = emptyList(),
            fotosUsadas = 5,
            fotosConCoincidencia = 5,
        ),
        obtenidaEnMs = 0L,
        rumboAlTerminar = null,
    )

    @Test
    fun laVista63DiceLaDistanciaPorElCaminoYLaPrimeraInstruccion() {
        // Brújula 10° + corrección −10° = norte: el camino va al oeste, «a tu izquierda».
        val d = DescribirUbicacion.describir(ubicadoEn(latPrueba, lngPrueba), 10.0, bloque35, planificador)
        assertEquals(
            listOf(
                "Tu destino, Bloque 35, está a unos 31 metros por el camino.",
                "Gira a tu izquierda y sigue recto 14 metros.",
                DescribirUbicacion.GUIA_DISPONIBLE,
            ),
            d.detalles,
        )
        assertTrue(d.hablado.endsWith("Confianza alta. Tu destino, Bloque 35, está a unos 31 metros por el camino. " +
            "Gira a tu izquierda y sigue recto 14 metros. ${DescribirUbicacion.GUIA_DISPONIBLE}"))
    }

    @Test
    fun laVista63SinPlanificadorSigueEnLineaRecta() {
        val otro = LugarDestino("x", "Auditorio", CategoriaLugar.AUDITORIO, latPrueba + 0.001, lngPrueba)
        val sinPlan = DescribirUbicacion.describir(ubicadoEn(latPrueba, lngPrueba), 10.0, otro, null)
        assertEquals("Tu destino, Auditorio, está al frente, a unos 111 metros.", sinPlan.detalles.first())
        // Con planificador, cualquier lugar con coordenadas tiene ruta (por el camino), también este.
        val conPlan = DescribirUbicacion.describir(ubicadoEn(latPrueba, lngPrueba), 10.0, otro, planificador)
        assertTrue(conPlan.detalles.first(), conPlan.detalles.first().endsWith(" por el camino."))
    }

    @Test
    fun laVista63ConElDestinoLejosDiceElTramoEnLineaRecta() {
        // ~40 m al oeste de n0002: la meta cae sobre a0042, 0,3 m al norte de n0002 (14,7 m por el camino), y faltan
        // ~40 m en línea recta; las alertas (FE-3.6) van después.
        val lejos = LugarDestino("x", "Auditorio", CategoriaLugar.AUDITORIO, 6.2014317, -75.5791977)
        val d = DescribirUbicacion.describir(ubicadoEn(latPrueba, lngPrueba), 10.0, lejos, planificador)
        assertEquals(
            listOf(
                "Tu destino, Auditorio, está a unos 15 metros por el camino.",
                "Gira a tu izquierda y sigue recto 15 metros.",
                "Desde el camino, Auditorio queda a unos 40 metros en línea recta.",
                DescribirUbicacion.GUIA_DISPONIBLE,
            ),
            d.detalles,
        )
        assertTrue(d.hablado.endsWith("Desde el camino, Auditorio queda a unos 40 metros en línea recta. " +
            DescribirUbicacion.GUIA_DISPONIBLE))
        // Cerca del grafo (Bloque 35), sin esa frase.
        val cerca = DescribirUbicacion.describir(ubicadoEn(latPrueba, lngPrueba), 10.0, bloque35, planificador)
        assertTrue(cerca.detalles.none { it.startsWith("Desde el camino") })
    }
}
