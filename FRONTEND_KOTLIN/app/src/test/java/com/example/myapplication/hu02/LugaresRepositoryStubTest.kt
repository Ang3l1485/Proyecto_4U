package com.example.myapplication.hu02

import com.example.myapplication.data.repository.LUGARES_DE_PRUEBA
import com.example.myapplication.data.repository.LugaresRepositoryStub
import com.example.myapplication.domain.model.CategoriaLugar
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HU-02 / Selección de destino: lugares simulados que alimentan la lista y la búsqueda por voz.
 * (Cuando exista `GET /places`, esta batería sirve como contrato del repositorio real.)
 * `LugaresRepositoryStub` espera 300 ms con `delay`; se usa `runBlocking`, así que no hay
 * dependencias de test nuevas.
 */
class LugaresRepositoryStubTest {

    private fun cargar() = runBlocking { LugaresRepositoryStub().obtenerLugares() }

    @Test
    fun devuelve_la_lista_de_lugares_de_prueba() {
        val lugares = cargar()
        assertEquals(LUGARES_DE_PRUEBA, lugares)
        assertTrue(lugares.isNotEmpty())
    }

    @Test
    fun los_ids_son_unicos() {
        val ids = cargar().map { it.id }
        assertEquals(ids.size, ids.toSet().size)
    }

    @Test
    fun cada_lugar_tiene_nombre_alias_y_coordenadas_validas() {
        cargar().forEach { l ->
            assertTrue("${l.id}: nombre vacío", l.nombre.isNotBlank())
            assertTrue("${l.id}: sin alias (no se podría decir por voz)", l.alias.isNotEmpty())
            assertTrue("${l.id}: latitud inválida", l.lat in -90.0..90.0)
            assertTrue("${l.id}: longitud inválida", l.lng in -180.0..180.0)
        }
    }

    @Test
    fun las_distancias_cuando_existen_no_son_negativas() {
        cargar().forEach { l ->
            assertTrue("${l.id}: distancia negativa", (l.distanciaMetros ?: 0) >= 0)
        }
    }

    @Test
    fun cada_categoria_con_chip_propio_tiene_al_menos_un_lugar() {
        val categoriasConLugares = cargar().map { it.categoria }.toSet()
        CategoriaLugar.DESTACADAS.forEach { categoria ->
            assertTrue("Sin lugares de $categoria: el chip filtraría una lista vacía", categoria in categoriasConLugares)
        }
    }

    @Test
    fun las_categorias_destacadas_y_las_otras_cubren_todo_sin_repetirse() {
        val destacadas = CategoriaLugar.DESTACADAS.toSet()
        val otras = CategoriaLugar.OTRAS.toSet()
        assertTrue(destacadas.intersect(otras).isEmpty())
        assertEquals(CategoriaLugar.values().toSet(), destacadas + otras)
    }

    @Test
    fun la_etiqueta_singular_y_la_plural_de_bano_son_las_documentadas() {
        assertEquals("Baño", CategoriaLugar.BANO.etiqueta)
        assertEquals("Baños", CategoriaLugar.BANO.etiquetaPlural)
    }
}
