package com.example.myapplication.data.local

import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.google.gson.JsonParser
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * FE-2.1: parser compartido del `manifest.json` (`ManifestRecorrido`, ARCHITECTURE §5.6) y la cola de subida en disco
 * (`AlmacenRecorridos`, §5.10): claves nuevas, regla de estados, escritura que conserva lo que no conoce y la regla de
 * «fotos pendientes» del Panel.
 */
class AlmacenRecorridosTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val raiz: File by lazy { tmp.newFolder("recoleccion") }
    private val almacen by lazy { AlmacenRecorridos(raiz) }

    // ---- parser -----------------------------------------------------------------------------------------------

    @Test
    fun video_manifestDeAssets_ordenaPorIdYAplicaPorDefecto() {
        val json = ManifestRecorrido.parsear(
            """{"name":"Video 1","created_at":"2026-10-09T10:00:00Z","photos":[
              {"id":"0010","file":"photos/0010.png","lat":6.1,"lng":-75.1,"heading":null,"estado":"ERROR","calidad":"alta","thumb":"thumbs/0010.png"},
              {"id":"0002","file":"photos/0002.png","lat":6.2,"lng":-75.2,"heading":90,"lugar":"Biblioteca","thumb":"thumbs/0002.png"},
              {"id":"0001","file":"photos/0001.png","lat":6.3,"lng":-75.3}]}""",
        )
        val video = ManifestRecorrido.video("vid_0001", json, url = { "u/$it" }, miniaturaExiste = { it.endsWith("0002.png") })
        assertEquals(listOf("0001", "0002", "0010"), video.fotos.map { it.id }) // texto: ceros a la izquierda
        assertEquals("Video 1", video.nombre)
        assertEquals("2026-10-09T10:00:00Z", video.creadoEn)
        val f10 = video.fotos.last()
        assertEquals(EstadoFoto.ERROR, f10.estado)
        assertEquals(CalidadFoto.ALTA, f10.calidad)
        assertNull(f10.rumbo)
        assertEquals("u/photos/0010.png", f10.urlMiniatura) // la miniatura no existe: la foto original
        val f2 = video.fotos[1]
        assertEquals("u/thumbs/0002.png", f2.urlMiniatura)
        assertEquals(90f, f2.rumbo)
        assertEquals("Biblioteca", f2.lugar)
        assertEquals(EstadoFoto.PROCESADA, video.fotos[0].estado) // sin estado ni sync
        assertEquals(CalidadFoto.NORMAL, video.fotos[0].calidad)
    }

    @Test
    fun estadoFoto_estadoGanaASync_yPendienteSubidaEsPendiente() {
        fun estado(texto: String) = ManifestRecorrido.estadoFoto(JsonParser.parseString(texto).asJsonObject)
        assertEquals(EstadoFoto.PENDIENTE, estado("""{"sync":"pendiente"}"""))
        assertEquals(EstadoFoto.SUBIDA, estado("""{"sync":"subida"}"""))
        assertEquals(EstadoFoto.PROCESADA, estado("""{"sync":"subida","estado":"procesada"}"""))
        assertEquals(EstadoFoto.ERROR, estado("""{"sync":"subida","estado":"error"}"""))
        assertEquals(EstadoFoto.PENDIENTE, estado("""{"estado":"pendiente_subida"}"""))
        assertEquals(EstadoFoto.PROCESADA, estado("""{}"""))
        assertEquals(EstadoFoto.PENDIENTE, estado("""{"sync":"pendiente","estado":"rara"}"""))
    }

    @Test
    fun parsear_jsonRotoOVacio_lanzaManifestException() {
        assertThrows(ManifestException::class.java) { ManifestRecorrido.parsear("{roto") }
        assertThrows(ManifestException::class.java) { ManifestRecorrido.parsear("[]") }
        assertThrows(ManifestException::class.java) { ManifestRecorrido.parsear("") }
    }

    @Test
    fun leer_recorridoConClavesDeFE21() = runBlocking {
        ManifestPrueba.crear(
            raiz, fotos = 3, subidas = setOf(1), preparadas = setOf(1, 2),
            extra = mapOf("remote_video_id" to "\"v-123\"", "subida_estado" to "\"subiendo\""),
        )
        val r = almacen.leer("rec_0001")
        assertTrue(r.finalizado)
        assertEquals("v-123", r.remoteVideoId)
        assertEquals(EstadoSubida.SUBIENDO, r.subida)
        assertEquals(2, r.fotosPendientes)
        assertFalse(r.editable)
        assertEquals(FotoPreparada(51, 1600, 1200), r.fotos[0].preparada)
        assertNull(r.fotos[2].preparada)
        assertEquals(1, r.fotos[0].orden)
        assertEquals(EstadoFoto.SUBIDA, r.fotos[0].estado)
        assertEquals(EstadoFoto.PENDIENTE, r.fotos[1].estado)
        assertEquals(2, r.trayectoria.size)
        assertEquals(512L, r.duracionSegundos)
        assertEquals(470, r.pasos)
        assertEquals(359.99, r.inicioRumbo!!, 1e-9)
    }

    @Test
    fun leer_sinSubidaEstado_esSinSubirYEditable() = runBlocking {
        ManifestPrueba.crear(raiz)
        val r = almacen.leer("rec_0001")
        assertEquals(EstadoSubida.SIN_SUBIR, r.subida)
        assertNull(r.remoteVideoId)
        assertTrue(r.editable)
    }

    // ---- escritura --------------------------------------------------------------------------------------------

    @Test
    fun escribir_conservaClavesDesconocidasYProgress() = runBlocking {
        val carpeta = ManifestPrueba.crear(raiz, extra = mapOf("clave_futura" to "{\"x\":1}"))
        almacen.marcarSubidas("rec_0001", listOf("0002"))
        almacen.cambiarEstadoSubida("rec_0001", EstadoSubida.SUBIENDO)
        almacen.guardarVideoRemoto("rec_0001", "v-9")
        val json = JsonParser.parseString(File(carpeta, "manifest.json").readText()).asJsonObject
        assertEquals(1, json.getAsJsonObject("clave_futura").get("x").asInt)
        assertEquals(2, json.getAsJsonObject("progress").getAsJsonArray("track").size())
        assertEquals("subiendo", json.get("subida_estado").asString)
        assertEquals("v-9", json.get("remote_video_id").asString)
        assertEquals(340.5, json.get("distance_m").asDouble, 0.0)
        val fotos = json.getAsJsonArray("photos")
        assertEquals("subida", fotos[1].asJsonObject.get("sync").asString)
        assertEquals("pendiente", fotos[0].asJsonObject.get("sync").asString)
        assertFalse(File(carpeta, "manifest.json.tmp").exists())
    }

    @Test
    fun contarFotosPendientes_soloFinalizadosYSyncPendiente() = runBlocking {
        ManifestPrueba.crear(raiz, id = "rec_0001", fotos = 5, subidas = setOf(1, 2))
        ManifestPrueba.crear(raiz, id = "rec_0002", fotos = 4, estado = "en_curso")
        ManifestPrueba.crear(raiz, id = "rec_0003", fotos = 2, subidas = setOf(1, 2))
        assertEquals(3, almacen.contarFotosPendientes())
    }

    @Test
    fun idsEnSubida_soloFinalizadosSubiendo_yListarSaltaIlegibles() = runBlocking {
        ManifestPrueba.crear(raiz, id = "rec_0001", extra = mapOf("subida_estado" to "\"subiendo\""))
        ManifestPrueba.crear(raiz, id = "rec_0002", extra = mapOf("subida_estado" to "\"completada\""))
        ManifestPrueba.crear(raiz, id = "rec_0003", estado = "en_curso", extra = mapOf("subida_estado" to "\"subiendo\""))
        File(raiz, "rec_0004").mkdirs()
        File(raiz, "rec_0004/manifest.json").writeText("{roto")
        assertEquals(listOf("rec_0001"), almacen.idsEnSubida())
        assertEquals(listOf("rec_0001", "rec_0002", "rec_0003"), almacen.listar().map { it.id })
    }

    @Test
    fun renombrar_recortaYLimita_yRechazaVacioOEnviado() = runBlocking {
        ManifestPrueba.crear(raiz, id = "rec_0001")
        assertEquals("Entrada sur", almacen.renombrar("rec_0001", "  Entrada sur  "))
        assertEquals("x".repeat(40), almacen.renombrar("rec_0001", "x".repeat(55)))
        assertEquals("x".repeat(40), almacen.leer("rec_0001").nombre)
        assertThrows(IllegalArgumentException::class.java) { runBlocking { almacen.renombrar("rec_0001", "   ") } }
        ManifestPrueba.crear(raiz, id = "rec_0002", extra = mapOf("remote_video_id" to "\"v\""))
        assertThrows(IllegalStateException::class.java) { runBlocking { almacen.renombrar("rec_0002", "Otro") } }
        assertEquals("Entrada norte", almacen.leer("rec_0002").nombre)
    }

    @Test
    fun descartarFoto_borraEntradaYArchivos_soloSiEditable() = runBlocking {
        val carpeta = ManifestPrueba.crear(raiz, id = "rec_0001", fotos = 3, preparadas = setOf(2))
        almacen.descartarFoto("rec_0001", "0002")
        assertEquals(listOf("0001", "0003"), almacen.leer("rec_0001").fotos.map { it.id })
        assertFalse(File(carpeta, "photos/0002.jpg").exists())
        assertFalse(File(carpeta, "subida/0002.jpg").exists())
        assertTrue(File(carpeta, "photos/0001.jpg").exists())
        ManifestPrueba.crear(raiz, id = "rec_0002", extra = mapOf("remote_video_id" to "\"v\""))
        assertThrows(IllegalStateException::class.java) { runBlocking { almacen.descartarFoto("rec_0002", "0001") } }
        assertEquals(3, almacen.leer("rec_0002").fotos.size)
    }

    @Test
    fun guardarEstadosRemotos_escribeEstadoYMotivo() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 3, subidas = setOf(1, 2, 3))
        almacen.guardarEstadosRemotos(
            "rec_0001",
            mapOf(
                "0001" to (EstadoFoto.PROCESADA to null),
                "0002" to (EstadoFoto.ERROR to "lado menor 200 px (mínimo 320)"),
                "0003" to (EstadoFoto.PENDIENTE to null), // no se escribe: lo dice sync
            ),
        )
        val r = almacen.leer("rec_0001")
        assertEquals(EstadoFoto.PROCESADA, r.fotos[0].estado)
        assertEquals(EstadoFoto.ERROR, r.fotos[1].estado)
        assertEquals("lado menor 200 px (mínimo 320)", r.fotos[1].error)
        assertEquals(EstadoFoto.SUBIDA, r.fotos[2].estado)
    }

    @Test
    fun guardarPreparada_yBorrarPreparadas_conservaElRegistro() = runBlocking {
        val carpeta = ManifestPrueba.crear(raiz, fotos = 2)
        val copia = almacen.archivoPreparado("rec_0001", "0001")
        copia.parentFile?.mkdirs()
        copia.writeBytes(ByteArray(10))
        almacen.guardarPreparada("rec_0001", "0001", FotoPreparada(10, 1200, 1600))
        assertEquals(FotoPreparada(10, 1200, 1600), almacen.leer("rec_0001").fotos[0].preparada)
        almacen.borrarPreparadas("rec_0001")
        assertFalse(File(carpeta, "subida").exists())
        assertEquals(FotoPreparada(10, 1200, 1600), almacen.leer("rec_0001").fotos[0].preparada)
    }

    @Test
    fun descartar_borraElRecorrido_yLeerLanzaManifestException() {
        runBlocking {
            ManifestPrueba.crear(raiz)
            almacen.descartar("rec_0001")
            assertFalse(File(raiz, "rec_0001").exists())
        }
        assertThrows(ManifestException::class.java) { runBlocking { almacen.leer("rec_0001") } }
    }
}
