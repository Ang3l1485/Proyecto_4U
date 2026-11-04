package com.example.myapplication.domain.ruta

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.1, criterio C1: `grafo.json` se lee tal cual y se valida; uno inválido no lanza (ARCHITECTURE §5.7). `lugar` es
 * opcional e informativo (decisión del usuario del 2026-10-28).
 */
class LectorGrafoTest {

    private fun json(nodos: String, aristas: String, formato: Int = 1, version: String = "7") =
        """{"formato": $formato, "version": $version, "actualizado": "2026-10-28T09:00:00-05:00",
            "contadores": {"n": 9, "a": 9}, "nodos": [$nodos], "aristas": [$aristas]}"""

    private val dosNodos = """
        {"id": "n1", "lat": 6.2010, "lng": -75.5785, "tipo": "cruce"},
        {"id": "n2", "lat": 6.2011, "lng": -75.5785, "tipo": "entrada", "lugar": "Bloque 35"}"""
    private val unaArista = """{"id": "a1", "a": "n1", "b": "n2", "metros": 11.1, "tipo": "camino",
        "accesible": true, "bloqueada": false}"""

    private fun errores(texto: String): List<String> = (LectorGrafo.leer(texto) as CargaGrafo.Invalido).errores

    @Test
    fun grafoRealDeAssetsEsValidoYConexo() {
        val carga = LectorGrafo.leer(GrafosDePrueba.textoReal())
        assertTrue("$carga", carga is CargaGrafo.Valido)
        val g = (carga as CargaGrafo.Valido).grafo
        assertEquals(1, g.formato)
        assertEquals(209, g.version)
        assertEquals("2026-10-28T10:18:28-05:00", g.actualizado)
        assertEquals(28, g.nodos.size)
        assertEquals(33, g.aristas.size)
        assertEquals(8, g.entradas.size)
        assertEquals(20, g.nodos.count { it.tipo == TiposNodo.CRUCE })
        assertEquals(1, LectorGrafo.componentes(g.nodos, g.aristas).size)
        assertTrue(carga.avisos.isEmpty())
        assertEquals(
            listOf("bloque 33", "bloque 35", "biblioteca", "bloque 38", "cocnverso", "bloque 34", "cafeteria"),
            g.lugares,
        )
        assertTrue(g.aristas.none { it.bloqueada })
        assertEquals(647.2, g.metrosTotales, 0.05)
    }

    @Test
    fun grafoMinimoConDefectosYAvisos() {
        val texto = json(
            dosNodos + """, {"id": "n3", "lat": 6.2012, "lng": -75.5785, "tipo": "rampa", "lugar": "x"}""",
            unaArista + """, {"id": "a2", "a": "n2", "b": "n3"}""",
        )
        val carga = LectorGrafo.leer(texto) as CargaGrafo.Valido
        val g = carga.grafo
        assertEquals(7, g.version)
        assertEquals("camino", g.aristas[1].tipo)
        assertTrue(g.aristas[1].accesible)
        assertEquals(11.1, g.aristas[1].metros, 0.2) // sin metros: la distancia entre n2 y n3
        assertEquals("x", g.porId.getValue("n3").lugar) // lugar en cualquier nodo: informativo, se conserva
        assertEquals(2, carga.avisos.size) // tipo desconocido y metros calculados
    }

    @Test
    fun jsonRotoOFormatoDistintoNoLanzan() {
        assertTrue(errores("{no es json").single().startsWith("JSON ilegible"))
        assertEquals(listOf("la raíz no es un objeto JSON"), errores("[1, 2]"))
        assertEquals(listOf("formato 2 (se espera 1)"), errores(json(dosNodos, unaArista, formato = 2)))
        assertEquals(listOf("sin version entera"), errores(json(dosNodos, unaArista, version = "\"x\"")))
        assertTrue(errores("""{"formato": 1, "version": 1, "nodos": []}""").contains("sin lista «aristas»"))
    }

    @Test
    fun idsRepetidosYAristasANodosInexistentes() {
        val e = errores(
            json(
                dosNodos + """, {"id": "n1", "lat": 6.2, "lng": -75.5, "tipo": "cruce"}""",
                unaArista + """, {"id": "a1", "a": "n1", "b": "n9", "metros": 3}, {"id": "a3", "a": "n2", "b": "n2", "metros": 1}""",
            ),
        )
        assertTrue(e.toString(), e.contains("id de nodo repetido: n1"))
        assertTrue(e.toString(), e.contains("id de arista repetido: a1"))
        assertTrue(e.toString(), e.contains("arista a1: nodo inexistente n9"))
        assertTrue(e.toString(), e.contains("arista a3 une un nodo consigo mismo"))
    }

    @Test
    fun componenteAisladoInvalidaYEntradaSinLugarNo() {
        val e = errores(
            json(
                dosNodos + """, {"id": "n3", "lat": 6.2012, "lng": -75.5785, "tipo": "entrada"},
                    {"id": "n4", "lat": 6.2013, "lng": -75.5785, "tipo": "cruce"}""",
                unaArista + """, {"id": "a2", "a": "n3", "b": "n4", "metros": 11}""",
            ),
        )
        assertTrue(e.toString(), e.none { it.contains("sin lugar") })
        assertTrue(e.toString(), e.any { it.startsWith("el grafo tiene 2 componentes; fuera del principal: n3, n4") })
        // Una entrada sin lugar, sola, no invalida el grafo (el lugar es informativo).
        val sinLugar = LectorGrafo.leer(json(dosNodos.replace(", \"lugar\": \"Bloque 35\"", ""), unaArista))
        assertTrue("$sinLugar", sinLugar is CargaGrafo.Valido && (sinLugar as CargaGrafo.Valido).avisos.isEmpty())
    }

    @Test
    fun nodoSinCoordenadasEsError() {
        val e = errores(json("""{"id": "n1", "lat": "6.2", "lng": -75.5, "tipo": "cruce"}""", ""))
        assertTrue(e.toString(), e.contains("nodo #0 sin id, lat, lng o tipo"))
    }

    @Test
    fun componentesCuentaLasBloqueadas() {
        val g = GrafosDePrueba.cuadrado(bloquearBC = true)
        assertEquals(1, LectorGrafo.componentes(g.nodos, g.aristas).size)
        assertTrue(LectorGrafo.validar(g.nodos, g.aristas).isEmpty())
    }
}
