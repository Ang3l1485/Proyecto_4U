package com.example.myapplication.data.repository

import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.EstadoCola
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.data.local.ManifestPrueba
import com.example.myapplication.data.remote.SinConexionException
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.FiltrosImagenes
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.OrdenVideos
import com.example.myapplication.domain.model.PaginaImagenes
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

/**
 * FE-4.1: la mezcla de los videos del servidor con los recorridos del teléfono (`VideoRepositoryCompuesto` y
 * `MezclaVideos`). Un recorrido sale **una sola vez** (el que ya tiene `remote_video_id` lo representa el servidor), los
 * locales salen aunque el servidor falle, y renombrar/eliminar uno local persisten en disco salvo mientras se sube.
 */
class VideoRepositoryCompuestoTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val raiz: File by lazy { tmp.newFolder("recoleccion") }
    private val almacen by lazy { AlmacenRecorridos(raiz) }
    private val cambios = ContadorCambios()

    private class ServidorFalso : VideosServidor {
        val videos = mutableListOf<ResumenVideo>()
        val detalles = mutableMapOf<String, Video>()
        val fotos = mutableListOf<Foto>()
        var falla: Exception? = null
        val llamadas = CopyOnWriteArrayList<String>()

        override suspend fun paginaVideos(q: String?, orden: OrdenVideos, pagina: Int, porPagina: Int) =
            todosLosVideos(q, orden)

        override suspend fun todosLosVideos(q: String?, orden: OrdenVideos): PaginaVideos {
            falla?.let { throw it }
            llamadas += "videos q=$q orden=$orden"
            val f = videos.filter { q == null || it.nombre.lowercase().contains(q.lowercase()) }
            return PaginaVideos(f, f.size)
        }

        override suspend fun detalle(id: String): Video? {
            llamadas += "detalle $id"
            return detalles[id]
        }

        override suspend fun renombrar(id: String, nombre: String): ResumenVideo {
            llamadas += "renombrar $id $nombre"
            return videos.first { it.id == id }.copy(nombre = nombre)
        }

        override suspend fun eliminar(id: String): Int {
            llamadas += "eliminar $id"
            return 3
        }

        override suspend fun eliminarImagen(id: String) {
            llamadas += "eliminarImagen $id"
        }

        override suspend fun imagenes(filtros: FiltrosImagenes, pagina: Int, porPagina: Int): PaginaImagenes {
            falla?.let { throw it }
            llamadas += "imagenes $pagina"
            val desde = (pagina - 1) * porPagina
            return PaginaImagenes(fotos.drop(desde).take(porPagina), fotos.size, pagina, porPagina)
        }
    }

    private val uuid1 = "9c1d0000-0000-4000-8000-000000000001"
    private val uuid2 = "9c1d0000-0000-4000-8000-000000000002"

    private fun resumen(id: String, nombre: String) = ResumenVideo(
        id = id, nombre = nombre, creadoEn = "2026-10-27T15:00:00Z", finalizadoEn = null, fotos = 3,
        distanciaMetros = 10.0, duracionSegundos = 60, estado = EstadoVideo.PROCESADO,
    )

    private fun texto(s: String) = "\"$s\""

    private fun repo(
        servidor: VideosServidor,
        cola: EstadoCola = EstadoCola(),
        cambiosCola: MutableStateFlow<Int> = MutableStateFlow(0),
    ) = VideoRepositoryCompuesto(servidor, almacen, estadoCola = { cola }, cambiosCola = cambiosCola, cambiosVideos = cambios)

    @Test
    fun listar_unRecorridoSubidoSaleUnaSolaVez_conLosDatosDelServidor() = runBlocking {
        val servidor = ServidorFalso().apply { videos += resumen(uuid1, "video_5"); videos += resumen(uuid2, "Bloque 19") }
        // Ya en el servidor (a medias y completo): los representa el video del servidor.
        ManifestPrueba.crear(
            raiz, "rec_0001", fotos = 2, nombre = "video_5",
            extra = mapOf("remote_video_id" to texto(uuid1), "subida_estado" to texto("subiendo")),
        )
        ManifestPrueba.crear(
            raiz, "rec_0004", fotos = 2,
            extra = mapOf("remote_video_id" to texto("9c1d0000-0000-4000-8000-00000000dead"), "subida_estado" to texto("completada")),
        )
        // Sin subir: sale como local. En curso: no sale (se retoma en 7.4).
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 3, nombre = "Entrada norte")
        ManifestPrueba.crear(raiz, "rec_0003", fotos = 2, estado = "en_curso")

        val lista = repo(servidor).listarVideos()

        assertEquals(listOf("rec_0002"), lista.locales.map { it.id })
        assertEquals(listOf(uuid1, uuid2), lista.servidor.map { it.id })
        assertEquals(2, lista.totalServidor)
        assertNull(lista.errorServidor)
        val todos = (lista.locales + lista.servidor).map { it.id }
        assertEquals(todos.size, todos.toSet().size) // ningún video dos veces
        val local = lista.locales.single()
        assertTrue(local.local)
        assertEquals(EstadoVideo.SIN_SUBIR, local.estado)
        assertEquals(3, local.fotos)
        assertEquals(340.5, local.distanciaMetros!!, 0.0) // distance_m del manifest
        assertEquals(512L, local.duracionSegundos)
        assertEquals("video_5", lista.servidor[0].nombre) // los datos del servidor, no los del manifest
    }

    @Test
    fun listar_servidorCaido_dejaLosLocales_yLaExcepcion() = runBlocking {
        val servidor = ServidorFalso().apply { falla = SinConexionException() }
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 1)

        val lista = repo(servidor).listarVideos()

        assertEquals(listOf("rec_0002"), lista.locales.map { it.id })
        assertTrue(lista.servidor.isEmpty())
        assertNull(lista.totalServidor)
        assertTrue(lista.errorServidor is SinConexionException)
    }

    @Test
    fun listar_filtraLosLocalesPorNombre_yLosOrdena_yPasaQyOrdenAlServidor() = runBlocking {
        val servidor = ServidorFalso()
        ManifestPrueba.crear(raiz, "rec_0001", fotos = 1, nombre = "Entrada Norte")
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 3, nombre = "entrada sur")
        ManifestPrueba.crear(raiz, "rec_0003", fotos = 2, nombre = "Biblioteca")
        val r = repo(servidor)

        assertEquals(listOf("rec_0001", "rec_0002"), r.listarVideos("ENTRADA", OrdenVideos.NOMBRE).locales.map { it.id })
        assertEquals(listOf("rec_0002", "rec_0003", "rec_0001"), r.listarVideos(null, OrdenVideos.MAS_FOTOS).locales.map { it.id })
        // Misma fecha en los tres: a igualdad, el id mayor primero.
        assertEquals(listOf("rec_0003", "rec_0002", "rec_0001"), r.listarVideos(null, OrdenVideos.RECIENTES).locales.map { it.id })
        assertTrue(servidor.llamadas.contains("videos q=ENTRADA orden=NOMBRE"))
    }

    @Test
    fun subiendo_marcaElLocal_yNoDejaRenombrarNiEliminar() = runBlocking {
        val servidor = ServidorFalso()
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 2, nombre = "Entrada norte")
        val r = repo(servidor, cola = EstadoCola(fase = FaseCola.PREPARANDO, videoId = "rec_0002"))

        assertEquals(EstadoVideo.SUBIENDO, r.listarVideos().locales.single().estado)
        val video = r.obtenerVideo("rec_0002")!!
        assertFalse(video.editable)
        assertTrue(video.nota!!.startsWith("Se está subiendo"))
        assertThrows(RecorridoNoEditableException::class.java) { runBlocking { r.renombrarVideo("rec_0002", "Otro") } }
        assertThrows(RecorridoNoEditableException::class.java) { runBlocking { r.eliminarVideo("rec_0002") } }
        assertEquals("Entrada norte", almacen.leer("rec_0002").nombre) // el disco no cambió
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun obtenerVideo_localConMiniaturasPropias_yDelServidor_ySinPreguntarConIdsRaros() = runBlocking {
        val servidor = ServidorFalso().apply { detalles[uuid1] = Video(uuid1, "Del servidor") }
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 2, nombre = "Entrada norte")
        val r = repo(servidor)

        val local = r.obtenerVideo("rec_0002")!!
        assertTrue(local.local)
        assertTrue(local.editable)
        assertNull(local.nota)
        assertEquals(listOf("0001", "0002"), local.fotos.map { it.id })
        assertEquals("https://miniaturas.local/rec_0002/photos/0001.jpg", local.fotos[0].urlMiniatura)
        assertEquals(1, local.fotos[0].orden)
        assertEquals("Del servidor", r.obtenerVideo(uuid1)!!.nombre)
        assertNull(r.obtenerVideo("../rec_0002"))
        assertNull(r.obtenerVideo("rec_9999")) // ni carpeta ni UUID: ni se pregunta al servidor
        assertEquals(listOf("detalle $uuid1"), servidor.llamadas.toList())
    }

    @Test
    fun local_renombrarEliminarFotoYEliminar_persistenEnDisco_yAvisan() = runBlocking {
        val servidor = ServidorFalso()
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 2, nombre = "Entrada norte")
        val r = repo(servidor)

        r.renombrarVideo("rec_0002", "  Entrada sur ")
        assertEquals("Entrada sur", almacen.leer("rec_0002").nombre)
        r.eliminarFoto("rec_0002", "0002")
        assertEquals(listOf("0001"), almacen.leer("rec_0002").fotos.map { it.id })
        assertNull(r.eliminarVideo("rec_0002"))
        assertFalse(File(raiz, "rec_0002").exists())
        assertEquals(3, cambios.version.value)
        assertTrue(servidor.llamadas.isEmpty()) // nada fue al servidor
    }

    @Test
    fun servidor_renombrarEliminarFotoYEliminar_vanAlServidor() = runBlocking {
        val servidor = ServidorFalso().apply { videos += resumen(uuid1, "video_5") }
        val r = repo(servidor)

        r.renombrarVideo(uuid1, "validacion-4-1-renombrado")
        r.eliminarFoto(uuid1, "img-1")
        assertEquals(3, r.eliminarVideo(uuid1))
        assertEquals(
            listOf("renombrar $uuid1 validacion-4-1-renombrado", "eliminarImagen img-1", "eliminar $uuid1"),
            servidor.llamadas.toList(),
        )
    }

    @Test
    fun recorridosDelTelefono_incluyeLosSubidos_conSusFotos_ySinLosEnCurso() = runBlocking {
        ManifestPrueba.crear(raiz, "rec_0001", fotos = 2, extra = mapOf("remote_video_id" to texto(uuid1)))
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 3)
        ManifestPrueba.crear(raiz, "rec_0003", fotos = 2, estado = "en_curso")

        val videos = repo(ServidorFalso()).recorridosDelTelefono()

        assertEquals(listOf("rec_0001", "rec_0002"), videos.map { it.id })
        assertEquals(3, videos[1].fotos.size)
        assertEquals("2026-10-25T15:08:32-05:00", videos[1].finalizadoEn)
    }

    @Test
    fun puntosDeOtros_juntaLocalesSinSubirYServidor_sinElPropio_conTope() = runBlocking {
        val servidor = ServidorFalso().apply {
            repeat(5) { fotos += Foto("a$it", uuid1, "", "", "", 6.2, -75.5) } // las del propio video: fuera
            repeat(250) { fotos += Foto("b$it", uuid2, "", "", "", 6.3, -75.6) }
        }
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 2) // sin subir: entra
        ManifestPrueba.crear(raiz, "rec_0001", fotos = 2, extra = mapOf("remote_video_id" to texto(uuid2))) // ya en el servidor
        val r = repo(servidor)

        val sinTope = r.puntosDeOtros(uuid1, maximo = 500)
        assertEquals(setOf("rec_0002", uuid2), sinTope.videos.keys)
        assertEquals(250, sinTope.videos[uuid2]!!.size)
        assertFalse(sinTope.truncado)
        assertNull(sinTope.aviso)

        val conTope = r.puntosDeOtros(uuid1, maximo = 100)
        assertTrue(conTope.truncado)
        assertEquals(100, conTope.videos.values.sumOf { it.size })
        assertTrue(conTope.aviso!!.contains("100"))
    }

    @Test
    fun puntosDeOtros_servidorCaido_dejaLosLocales_yUnAviso() = runBlocking {
        val servidor = ServidorFalso().apply { falla = SinConexionException() }
        ManifestPrueba.crear(raiz, "rec_0002", fotos = 2)

        val p = repo(servidor).puntosDeOtros("rec_0009")

        assertEquals(setOf("rec_0002"), p.videos.keys)
        assertTrue(p.aviso!!.startsWith("No se pudieron cargar"))
    }

    @Test
    fun cambios_emiteConLasEscriturasYConLaCola() = runBlocking {
        val extra = MutableStateFlow(0)
        val r = repo(ServidorFalso(), cambiosCola = extra)
        val recibidos = CopyOnWriteArrayList<Int>()
        val primero = CompletableDeferred<Unit>()
        val segundo = CompletableDeferred<Unit>()
        val trabajo = launch {
            r.cambios().take(3).collect {
                recibidos += it
                if (recibidos.size == 1) primero.complete(Unit)
                if (recibidos.size == 2) segundo.complete(Unit)
            }
        }
        withTimeout(5_000) { primero.await() }
        extra.value = 1 // la cola terminó un intento
        withTimeout(5_000) { segundo.await() }
        cambios.avisar() // una escritura (renombrar, eliminar…)
        withTimeout(5_000) { trabajo.join() }
        assertEquals(3, recibidos.size)
        assertEquals(3, recibidos.toSet().size)
    }
}
