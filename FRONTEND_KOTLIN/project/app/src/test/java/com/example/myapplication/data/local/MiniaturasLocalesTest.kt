package com.example.myapplication.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * FE-4.1: las miniaturas de los recorridos del teléfono en 7.14 (hallazgo de FE-2.1: salían vacías). Solo se sirven
 * fotos de `files/recoleccion/<rec>/photos/` (nada de `..` ni otras rutas) y la copia se genera una vez.
 */
class MiniaturasLocalesTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val raiz: File by lazy { tmp.newFolder("recoleccion") }
    private val cache: File by lazy { tmp.newFolder("cache") }
    private var preparadas = 0
    private var fallar = false

    private val preparador = PreparadorFoto { original, destino ->
        if (fallar) {
            destino.parentFile?.mkdirs()
            destino.writeBytes(ByteArray(3)) // una copia a medias que debe borrarse
            throw FotoIlegibleException("no se pudo leer ${original.name}")
        }
        preparadas++
        destino.parentFile?.mkdirs()
        destino.writeBytes(ByteArray(20) { 7 })
        FotoPreparada(20, 240, 180)
    }

    private fun miniaturas() = MiniaturasLocales(raiz, cache, preparador)

    @Test
    fun ruta_soloAceptaFotosDeUnRecorrido() {
        assertEquals("https://miniaturas.local/rec_0003/photos/0001.jpg", MiniaturasLocales.url("rec_0003", "photos/0001.jpg"))
        assertEquals("rec_0003" to "photos/0001.jpg", MiniaturasLocales.ruta("https://miniaturas.local/rec_0003/photos/0001.jpg"))
        assertEquals("rec_0003" to "photos/0001.jpg", MiniaturasLocales.ruta("https://miniaturas.local/rec_0003/photos/0001.jpg?v=2"))
        assertNull(MiniaturasLocales.ruta("https://miniaturas.local/../photos/0001.jpg"))
        assertNull(MiniaturasLocales.ruta("https://miniaturas.local/rec_0003/../manifest.json"))
        assertNull(MiniaturasLocales.ruta("https://miniaturas.local/rec_0003/manifest.json"))
        assertNull(MiniaturasLocales.ruta("https://miniaturas.local/rec_0003/photos/a/0001.jpg"))
        assertNull(MiniaturasLocales.ruta("https://otro.local/rec_0003/photos/0001.jpg"))
        assertNull(MiniaturasLocales.ruta("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"))
    }

    @Test
    fun archivo_seGeneraUnaVez_yNoSaleDeLaCache() {
        ManifestPrueba.crear(raiz, "rec_0003", fotos = 2)
        val m = miniaturas()
        val url = MiniaturasLocales.url("rec_0003", "photos/0002.jpg")

        val primera = m.archivo(url)!!
        val segunda = m.archivo(url)!!

        assertEquals(primera, segunda)
        assertEquals(1, preparadas)
        assertEquals(File(File(cache, "rec_0003"), "0002.jpg").canonicalPath, primera.canonicalPath)
        assertTrue(File(raiz, "rec_0003/photos/0002.jpg").isFile) // el original no se toca
    }

    @Test
    fun archivo_sinFotoOIlegible_esNull_yNoDejaCopiasAMedias() {
        ManifestPrueba.crear(raiz, "rec_0003", fotos = 1)
        val m = miniaturas()

        assertNull(m.archivo(MiniaturasLocales.url("rec_0003", "photos/0009.jpg")))
        assertNull(m.archivo("https://miniaturas.local/rec_0003/../../secreto.jpg"))
        fallar = true
        assertNull(m.archivo(MiniaturasLocales.url("rec_0003", "photos/0001.jpg")))
        assertFalse(File(File(cache, "rec_0003"), "0001.jpg").exists())
    }
}
