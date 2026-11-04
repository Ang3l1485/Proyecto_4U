package com.example.myapplication.ui.ubicacion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * FE-3.2, apoyo del criterio C3 (`CONSERVAR_FOTOS = false`: ninguna foto de escaneo queda en el teléfono; decisión
 * abierta 12). `FotosEscaneo` borra la carpeta entera al cerrar y las fotos que llegan fuera de tiempo.
 */
class FotosEscaneoTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun carpeta(nombre: String) = File(tmp.root, "camera/photos/$nombre").apply { mkdirs() }

    private fun foto(carpeta: File, nombre: String) = File(carpeta, nombre).apply { writeBytes(byteArrayOf(1, 2, 3)) }

    @Test
    fun cerrar_borraLaCarpetaConOriginalesYCopias() {
        val c = carpeta("2026-10-26_10-00-00")
        val fotos = FotosEscaneo(conservar = false)
        fotos.abrir(c)
        for (i in 1..5) fotos.aceptar(foto(c, "escaneo_$i.jpg"), i * 72.0)
        for (i in 1..5) foto(c, "envio_$i.jpg") // copias re-codificadas de RemoteLocalizacionRepository

        assertEquals(5, fotos.cantidad)
        assertEquals(listOf(72.0, 144.0, 216.0, 288.0, 360.0), fotos.fotos.map { it.rumboGrados })
        assertEquals(10, fotos.cerrar())
        assertFalse(c.exists())
        assertNull(fotos.carpeta)
        assertEquals(0, fotos.cantidad)
        assertEquals(0, fotos.cerrar()) // idempotente
    }

    @Test
    fun conservar_noBorraNada() {
        val c = carpeta("2026-10-26_10-00-00")
        val fotos = FotosEscaneo(conservar = true)
        fotos.abrir(c)
        val f = foto(c, "escaneo_1.jpg")
        fotos.aceptar(f, 0.0)
        fotos.descartar(foto(c, "escaneo_2.jpg"))
        assertEquals(0, fotos.cerrar())
        assertTrue(f.exists())
        assertTrue(File(c, "escaneo_2.jpg").exists())
    }

    @Test
    fun abrirOtraCarpeta_borraLaAnterior() {
        val vieja = carpeta("2026-10-26_10-00-00")
        val nueva = carpeta("2026-10-26_10-01-00")
        val fotos = FotosEscaneo(conservar = false)
        fotos.abrir(vieja)
        fotos.aceptar(foto(vieja, "escaneo_1.jpg"), 10.0)
        fotos.abrir(nueva)
        assertFalse(vieja.exists())
        assertTrue(nueva.isDirectory)
        assertEquals(0, fotos.cantidad)
        assertEquals(nueva, fotos.carpeta)
    }

    @Test
    fun abrirLaMismaCarpeta_laVaciaPeroLaDeja() {
        // Dos escaneos en el mismo segundo: crearCarpetaEscaneo devuelve el mismo nombre.
        val c = carpeta("2026-10-26_10-00-00")
        val fotos = FotosEscaneo(conservar = false)
        fotos.abrir(c)
        foto(c, "escaneo_1.jpg")
        fotos.abrir(c)
        assertTrue(c.isDirectory)
        assertEquals(0, c.listFiles()!!.size)
    }

    @Test
    fun fotoTardia_deUnEscaneoCerrado_seBorraConSuCarpetaVacia() {
        val c = carpeta("2026-10-26_10-00-00")
        val fotos = FotosEscaneo(conservar = false)
        fotos.abrir(c)
        fotos.cerrar()
        // CameraX termina después: `tomarFoto` volvió a crear la carpeta (mkdirs) y escribió el JPG.
        val tardia = foto(carpeta("2026-10-26_10-00-00"), "escaneo_3.jpg")
        assertFalse(fotos.esDeLaCarpeta(tardia))
        fotos.descartar(tardia)
        assertFalse(tardia.exists())
        assertFalse(c.exists())
    }

    @Test
    fun fotoFueraDeFase_enLaCarpetaActual_seBorraPeroLaCarpetaQueda() {
        val c = carpeta("2026-10-26_10-00-00")
        val fotos = FotosEscaneo(conservar = false)
        fotos.abrir(c)
        val f = foto(c, "escaneo_6.jpg")
        assertTrue(fotos.esDeLaCarpeta(f))
        fotos.descartar(f)
        assertFalse(f.exists())
        assertTrue(c.isDirectory)
        assertEquals(0, fotos.cantidad)
    }
}
