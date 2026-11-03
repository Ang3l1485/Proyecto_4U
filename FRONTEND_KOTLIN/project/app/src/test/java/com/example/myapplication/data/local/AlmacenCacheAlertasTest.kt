package com.example.myapplication.data.local

import com.example.myapplication.domain.model.Alerta
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * `AlmacenCacheAlertasArchivo` y `ReglasCacheAlertas` (FE-3.6): caché local de las alertas públicas. Se prueba con una
 * carpeta temporal, como `AlmacenAlertasTest`.
 */
class AlmacenCacheAlertasTest {

    @get:Rule
    val carpeta = TemporaryFolder()

    private fun archivo() = File(carpeta.root, "alertas/${AlmacenCacheAlertasArchivo.NOMBRE}")

    private fun alerta(id: String, activa: Boolean = true, mensaje: String = id) =
        Alerta(id, 6.2, -75.578, mensaje, activa = activa)

    @Test
    fun cacheConAlertas_guardarYLeer_conservaAlertasYGeneradoEn() = runBlocking {
        val completa = Alerta("a", 6.200512, -75.578311, "Piso «mojado»", "agua", "alta", 35, true, 1L, 2L, 3, 4L)
        val cache = CachePublica(listOf(completa, alerta("b")), generadoEn = "2026-10-28T15:04:05Z")

        AlmacenCacheAlertasArchivo(archivo()).guardar(cache)
        val leida = AlmacenCacheAlertasArchivo(archivo()).leer()

        assertEquals(cache.alertas, leida.alertas)
        assertEquals("2026-10-28T15:04:05Z", leida.generadoEn)
        assertTrue(leida.cargada)
        assertFalse(File(archivo().parentFile, "${archivo().name}.tmp").exists())
    }

    @Test
    fun sinArchivo_leer_devuelveCacheVaciaYCargada() = runBlocking {
        val leida = AlmacenCacheAlertasArchivo(archivo()).leer()

        assertEquals(emptyList<Alerta>(), leida.alertas)
        assertNull(leida.generadoEn)
        assertTrue(leida.cargada)
    }

    @Test
    fun archivoDanado_leer_loApartaYEmpiezaVacio() = runBlocking {
        archivo().parentFile!!.mkdirs()
        archivo().writeText("{no es json")
        val registro = mutableListOf<String>()

        val leida = AlmacenCacheAlertasArchivo(archivo(), registrar = { registro += it }).leer()

        assertEquals(emptyList<Alerta>(), leida.alertas)
        assertFalse(archivo().exists())
        assertTrue(File(archivo().parentFile, "${archivo().name}.danado").exists())
        assertEquals(1, registro.size)
    }

    @Test
    fun cacheSinGeneradoEn_guardar_omiteLaClave() {
        val json = AlmacenCacheAlertasArchivo.aJson(CachePublica(listOf(alerta("a"))))

        assertFalse(json.has("generado_en"))
        assertEquals(AlmacenCacheAlertasArchivo.VERSION, json.get("version").asInt)
    }

    @Test
    fun respuestaCompleta_aplicar_dejaSoloActivasSinRepetir() {
        val resultado = ReglasCacheAlertas.aplicar(
            actual = listOf(alerta("vieja")),
            completo = true,
            alertas = listOf(alerta("a"), alerta("b", activa = false), alerta("a", mensaje = "repetida")),
            eliminadas = emptyList(),
        )

        assertEquals(listOf("a"), resultado.map { it.id })
    }

    @Test
    fun diferencias_aplicar_reemplazaAnadeQuitaInactivasYEliminadas() {
        val actual = listOf(alerta("a"), alerta("b"), alerta("c"))

        val resultado = ReglasCacheAlertas.aplicar(
            actual = actual,
            completo = false,
            alertas = listOf(alerta("a", mensaje = "nuevo"), alerta("b", activa = false), alerta("d")),
            eliminadas = listOf("c", "no-existe"),
        )

        assertEquals(listOf("a", "d"), resultado.map { it.id })
        assertEquals("nuevo", resultado.first().mensaje)
    }

    @Test
    fun diferenciaYaAplicada_aplicarDeNuevo_noCambiaNada() {
        val alertas = listOf(alerta("a", mensaje = "nuevo"), alerta("b", activa = false))
        val una = ReglasCacheAlertas.aplicar(listOf(alerta("a"), alerta("b")), false, alertas, listOf("x"))

        val dos = ReglasCacheAlertas.aplicar(una, false, alertas, listOf("x"))

        assertEquals(una, dos)
    }
}
