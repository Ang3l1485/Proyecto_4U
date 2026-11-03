package com.example.myapplication.data.local

import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.session.AlmacenSesion
import com.example.myapplication.session.SessionManager
import com.example.myapplication.session.VigilanteSesion
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/**
 * FE-2.1, criterio C2 (ARCHITECTURE §5.10; contrato en backend §5.4): `SubidaRecorrido` contra un backend y un S3
 * simulados con MockWebServer. Crear el video, registrar en lotes de 50, `PUT` con exactamente los encabezados
 * firmados (sin `X-Request-Id` ni `Authorization`), `complete`; y sobre todo **retomar sin duplicar** tras un corte de
 * red, una URL vencida (403) o la sesión perdida (que espera sesión, no reintenta).
 */
class SubidaRecorridoTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var servidor: MockWebServer
    private lateinit var raiz: File
    private lateinit var almacen: AlmacenRecorridos
    private val registro = CopyOnWriteArrayList<String>()
    private val lineasApi = CopyOnWriteArrayList<String>()

    /** El backend y S3 simulados. */
    private inner class Backend : Dispatcher() {
        val creados = AtomicInteger()
        val cuerposCrear = CopyOnWriteArrayList<JsonObject>()
        val lotes = CopyOnWriteArrayList<List<Int>>()
        val putsOk = ConcurrentHashMap<Int, AtomicInteger>()
        val putsIntentos = ConcurrentHashMap<Int, AtomicInteger>()
        val encabezadosPut = CopyOnWriteArrayList<Map<String, String>>()
        val enS3 = ConcurrentHashMap.newKeySet<Int>()
        val completados = AtomicInteger()

        /** Órdenes que el backend ya tiene subidas (responde `subida: null`, `estado: subida`). */
        val yaSubidas = ConcurrentHashMap.newKeySet<Int>()

        /** Órdenes cuyo próximo `PUT` responde 403 (una vez cada una). */
        val vencer403 = ConcurrentHashMap.newKeySet<Int>()

        /** Órdenes cuyo `PUT` corta la conexión mientras esté aquí (corte de red). */
        val cortar = ConcurrentHashMap.newKeySet<Int>()

        @Volatile var respuestaCrear: MockResponse? = null
        @Volatile var imagesNumero401: Int = -1 // n.º de llamada a images (desde 1) que responde 401
        @Volatile var completePendientes = 0
        private val llamadasImages = AtomicInteger()

        override fun dispatch(request: RecordedRequest): MockResponse {
            val ruta = request.requestUrl!!.encodedPath
            return when {
                request.method == "POST" && ruta == "/v1/collect/videos" -> {
                    creados.incrementAndGet()
                    cuerposCrear += JsonParser.parseString(request.body.readUtf8()).asJsonObject
                    respuestaCrear ?: json(201, """{"id":"$VIDEO","numero":7,"nombre":"Entrada norte","ref_cliente":"rec_0001","estado":"pendiente"}""")
                }
                request.method == "POST" && ruta == "/v1/collect/videos/$VIDEO/images" -> {
                    val n = llamadasImages.incrementAndGet()
                    if (n == imagesNumero401) {
                        return json(401, """{"error":{"codigo":"TOKEN_EXPIRADO","mensaje":"x","detalle":null}}""")
                    }
                    val imagenes = JsonParser.parseString(request.body.readUtf8()).asJsonObject.getAsJsonArray("imagenes")
                    val ordenes = imagenes.map { it.asJsonObject.get("orden").asInt }
                    lotes += ordenes
                    val items = ordenes.joinToString(",") { o ->
                        if (o in yaSubidas || o in enS3) {
                            """{"orden":$o,"id":"img-$o","estado":"subida","subida":null}"""
                        } else {
                            val url = servidor.url("/s3/dataset/$VIDEO/img-$o.jpg").toString() + "?X-Amz-Signature=$FIRMA"
                            """{"orden":$o,"id":"img-$o","estado":"pendiente_subida","subida":{"metodo":"PUT","url":"$url",""" +
                                """"encabezados":{"Content-Type":"image/jpeg"},"expira_en":"2026-10-25T20:15:00Z"}}"""
                        }
                    }
                    json(200, """{"imagenes":[$items]}""")
                }
                request.method == "PUT" && ruta.startsWith("/s3/dataset/$VIDEO/img-") -> {
                    val o = ruta.substringAfter("img-").substringBefore(".jpg").toInt()
                    putsIntentos.getOrPut(o) { AtomicInteger() }.incrementAndGet()
                    encabezadosPut += request.headers.toMap()
                    when {
                        // Con un Dispatcher propio, DISCONNECT_AT_START no aplica (MockWebServer lo mira en peek()):
                        // se corta tras leer la petición, sin respuesta → IOException en el cliente.
                        o in cortar -> MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST)
                        vencer403.remove(o) -> MockResponse().setResponseCode(403).setBody("<Code>AccessDenied</Code>")
                        else -> {
                            request.body.readByteArray()
                            putsOk.getOrPut(o) { AtomicInteger() }.incrementAndGet()
                            enS3 += o
                            MockResponse().setResponseCode(200)
                        }
                    }
                }
                request.method == "POST" && ruta == "/v1/collect/videos/$VIDEO/complete" -> {
                    completados.incrementAndGet()
                    val estado = if (completePendientes > 0) "pendiente" else "procesando"
                    json(200, """{"id":"$VIDEO","estado":"$estado","conteo":{"pendiente_subida":$completePendientes,"subida":${enS3.size},"procesada":0,"error":0}}""")
                }
                request.method == "GET" && ruta == "/v1/admin/videos/$VIDEO" -> json(
                    200,
                    """{"id":"$VIDEO","estado":"con_errores","conteo":{"pendiente_subida":0,"subida":0,"procesada":2,"error":1},
                      "fotos":[{"id":"img-1","video_id":"$VIDEO","orden":1,"lat":6.2,"lng":-75.5,"estado":"procesada"},
                               {"id":"img-2","video_id":"$VIDEO","orden":2,"lat":6.2,"lng":-75.5,"estado":"error","error":"lado menor 200 px (mínimo 320)"},
                               {"id":"img-3","video_id":"$VIDEO","orden":3,"lat":6.2,"lng":-75.5,"estado":"procesada"}]}""",
                )
                else -> json(404, """{"error":{"codigo":"NO_ENCONTRADO","mensaje":"$ruta","detalle":null}}""")
            }
        }

        fun totalPuts(): Int = putsIntentos.values.sumOf { it.get() }
    }

    private lateinit var backend: Backend

    /** Copia los bytes (el «JPEG re-codificado») y declara 1600×1200; falla con las fotos de [ilegibles]. */
    private class PreparadorFalso(val ilegibles: Set<String> = emptySet()) : PreparadorFoto {
        val preparadas = CopyOnWriteArrayList<String>()
        override fun preparar(original: File, destino: File): FotoPreparada {
            val id = original.nameWithoutExtension
            if (id in ilegibles) throw FotoIlegibleException("no se pudo leer ${original.name}")
            preparadas += id
            destino.parentFile?.mkdirs()
            original.copyTo(destino, overwrite = true)
            return FotoPreparada(destino.length(), 1600, 1200)
        }
    }

    /** Almacén de sesión en memoria (como el de `SesionVencidaTest`). */
    private class SesionEnMemoria(@Volatile var sesion: Sesion?) : AlmacenSesion {
        override fun leer(): Sesion? = sesion
        override fun escribir(sesion: Sesion) { this.sesion = sesion }
        override fun borrar() { sesion = null }
    }

    @Before
    fun preparar() {
        servidor = MockWebServer()
        backend = Backend()
        servidor.dispatcher = backend
        servidor.start()
        raiz = tmp.newFolder("recoleccion")
        almacen = AlmacenRecorridos(raiz)
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun subida(
        preparador: PreparadorFoto = PreparadorFalso(),
        conSesion: Boolean = true,
    ): SubidaRecorrido {
        val api = if (conSesion) {
            ClienteApi.crear(urlBase = servidor.url("/v1").toString(), token = { "tok" }, registrar = { lineasApi += it })
        } else {
            val vigilante = VigilanteSesion(SessionManager(SesionEnMemoria(null)), onSinSesion = {}, registrar = {})
            ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = { lineasApi += it }, vigilante = vigilante)
        }
        return SubidaRecorrido(
            almacen = almacen,
            api = api,
            s3 = SubidorS3(),
            preparador = preparador,
            dispositivo = "Xiaomi 23028RA60L / Android 14",
            appVersion = "1.0",
            registrar = { registro += it },
        )
    }

    private fun ejecutar(s: SubidaRecorrido, id: String = "rec_0001"): ResultadoSubida = runBlocking { s.ejecutar(id) {} }

    private fun sinSecretosEnRegistros() {
        for (linea in registro + lineasApi) {
            assertFalse("URL firmada en el registro: $linea", linea.contains(FIRMA) || linea.contains("X-Amz") || linea.contains("/s3/"))
            assertFalse("token en el registro: $linea", linea.contains("tok"))
        }
    }

    // ---- camino feliz -----------------------------------------------------------------------------------------

    @Test
    fun subida_60Fotos_dosLotes_putsConEncabezadosExactos_yCompleta() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 60)
        val resultado = ejecutar(subida())

        assertTrue(resultado.toString(), resultado is ResultadoSubida.Completada)
        assertEquals(1, backend.creados.get())
        val cuerpo = backend.cuerposCrear.single()
        assertEquals("rec_0001", cuerpo.get("ref_cliente").asString)
        assertEquals("Entrada norte", cuerpo.get("nombre").asString)
        assertEquals(60, cuerpo.get("total_fotos").asInt)
        assertEquals(0.0, cuerpo.getAsJsonObject("inicio").get("rumbo").asDouble, 0.0) // 359,99 → 0,0
        assertEquals("2026-10-25T15:00:00-05:00", cuerpo.get("iniciado_en").asString)
        assertEquals(512, cuerpo.get("duracion_s").asInt)
        assertEquals("Xiaomi 23028RA60L / Android 14", cuerpo.get("dispositivo").asString)
        assertEquals(listOf(50, 10), backend.lotes.map { it.size })
        assertEquals((1..60).toList(), backend.lotes.flatten())
        assertEquals(60, backend.totalPuts())
        assertTrue(backend.putsOk.values.all { it.get() == 1 })
        for (h in backend.encabezadosPut) {
            assertEquals("image/jpeg", h["Content-Type"])
            assertNull(h["X-Request-Id"])
            assertNull(h["Authorization"])
        }
        assertEquals(1, backend.completados.get())

        val r = almacen.leer("rec_0001")
        assertEquals(EstadoSubida.COMPLETADA, r.subida)
        assertEquals(VIDEO, r.remoteVideoId)
        assertTrue(r.fotos.all { it.subida && it.estado == EstadoFoto.SUBIDA })
        assertFalse(File(raiz, "rec_0001/subida").exists()) // copias borradas al completar
        assertTrue(r.fotos.all { it.preparada != null }) // queda el registro de lo subido
        sinSecretosEnRegistros()
    }

    @Test
    fun images_llevaOrdenBytesYRumboDelContrato() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 2)
        val cuerpos = CopyOnWriteArrayList<JsonObject>()
        val previo = backend
        servidor.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (request.requestUrl!!.encodedPath.endsWith("/images")) {
                    val copia = request.body.clone().readUtf8()
                    cuerpos += JsonParser.parseString(copia).asJsonObject
                }
                return previo.dispatch(request)
            }
        }
        assertTrue(ejecutar(subida()) is ResultadoSubida.Completada)
        val img = cuerpos.single().getAsJsonArray("imagenes")[0].asJsonObject
        assertEquals(1, img.get("orden").asInt)
        assertEquals(101L, img.get("bytes").asLong) // el tamaño de la copia que se sube
        assertEquals(37.5, img.get("rumbo").asDouble, 0.0)
        assertEquals("2026-10-25T15:01:00-05:00", img.get("capturada_en").asString)
    }

    // ---- retomar sin duplicar (C2) ----------------------------------------------------------------------------

    @Test
    fun retomar_conVideoRemotoYFotosSubidas_soloSubeLasPendientes() = runBlocking {
        ManifestPrueba.crear(
            raiz, fotos = 30, subidas = (1..20).toSet(), preparadas = (1..30).toSet(),
            extra = mapOf("remote_video_id" to "\"$VIDEO\"", "subida_estado" to "\"subiendo\""),
        )
        backend.enS3 += (1..20)
        val preparador = PreparadorFalso()
        val resultado = ejecutar(subida(preparador))

        assertTrue(resultado is ResultadoSubida.Completada)
        assertEquals(0, backend.creados.get()) // ya tenía remote_video_id
        assertEquals(listOf((21..30).toList()), backend.lotes)
        assertEquals(10, backend.totalPuts())
        assertTrue(preparador.preparadas.isEmpty()) // las copias de subida/ seguían valiendo
    }

    @Test
    fun fotoQueElBackendYaTiene_seMarcaSinPut() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 4)
        backend.yaSubidas += 3
        assertTrue(ejecutar(subida()) is ResultadoSubida.Completada)
        assertEquals(3, backend.totalPuts())
        assertNull(backend.putsIntentos[3])
        assertTrue(almacen.leer("rec_0001").fotos.all { it.subida })
    }

    @Test
    fun put403_pideUrlsDeNuevoSoloParaEsas() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 3)
        backend.vencer403 += 2
        assertTrue(ejecutar(subida()) is ResultadoSubida.Completada)
        assertEquals(listOf(listOf(1, 2, 3), listOf(2)), backend.lotes)
        assertEquals(2, backend.putsIntentos[2]!!.get())
        assertEquals(1, backend.putsOk[2]!!.get())
    }

    @Test
    fun corteDeRedEnUnPut_sinConexion_yAlReintentarCompletaSinDuplicar() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 8)
        backend.cortar += 5
        val primera = ejecutar(subida())
        assertTrue(primera.toString(), primera is ResultadoSubida.SinConexion)
        val aMedias = almacen.leer("rec_0001")
        assertEquals(EstadoSubida.SUBIENDO, aMedias.subida)
        assertEquals((1..4).map { "%04d".format(it) }, aMedias.fotos.filter { it.subida }.map { it.id })

        backend.cortar.clear() // vuelve la red
        val segunda = ejecutar(subida())
        assertTrue(segunda is ResultadoSubida.Completada)
        assertEquals(1, backend.creados.get() + 0) // el segundo intento reutiliza remote_video_id
        assertTrue("ninguna foto subida dos veces", backend.putsOk.values.all { it.get() == 1 })
        assertEquals(8, backend.putsOk.size)
        assertEquals((5..8).toList(), backend.lotes.last()) // solo las que faltaban
    }

    // ---- sesión -----------------------------------------------------------------------------------------------

    @Test
    fun sinSesion_esperaSesionSinLlamarAlBackend() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 3)
        val resultado = ejecutar(subida(conSesion = false))
        assertEquals(ResultadoSubida.EsperandoSesion("SIN_SESION_LOCAL"), resultado)
        assertEquals(0, servidor.requestCount)
        val r = almacen.leer("rec_0001")
        assertEquals(EstadoSubida.SUBIENDO, r.subida) // se retoma tras el login
        assertTrue(r.fotos.none { it.subida })
    }

    @Test
    fun tokenVencidoAMitad_esperaSesion_yConservaLoSubido() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 60)
        backend.imagesNumero401 = 2 // el segundo lote
        val resultado = ejecutar(subida())
        assertEquals(ResultadoSubida.EsperandoSesion("TOKEN_EXPIRADO"), resultado)
        assertEquals(50, almacen.leer("rec_0001").fotos.count { it.subida })
        assertEquals(0, backend.completados.get())
    }

    // ---- otros resultados -------------------------------------------------------------------------------------

    @Test
    fun completeConPendientes_quedaSubiendo() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 2)
        backend.completePendientes = 1
        val resultado = ejecutar(subida())
        assertTrue(resultado is ResultadoSubida.Pendiente)
        assertEquals(EstadoSubida.SUBIENDO, almacen.leer("rec_0001").subida)
    }

    @Test
    fun videoEliminadoEnElServidor_fallaSinReintento() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 2)
        backend.respuestaCrear = json(409, """{"error":{"codigo":"VIDEO_ELIMINADO","mensaje":"x","detalle":null}}""")
        val resultado = ejecutar(subida())
        assertTrue(resultado.toString(), resultado is ResultadoSubida.Fallida)
        assertTrue((resultado as ResultadoSubida.Fallida).motivo.contains("VIDEO_ELIMINADO"))
        assertEquals(0, backend.totalPuts())
    }

    @Test
    fun fotoIlegible_vuelveASinSubirSinLlamarAlBackend() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 3)
        val resultado = ejecutar(subida(PreparadorFalso(ilegibles = setOf("0002"))))
        assertEquals(ResultadoSubida.FotosIlegibles(listOf("0002")), resultado)
        assertEquals(0, servidor.requestCount)
        assertEquals(EstadoSubida.SIN_SUBIR, almacen.leer("rec_0001").subida)
    }

    @Test
    fun recorridoEnCurso_noSeSube() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 2, estado = "en_curso")
        assertTrue(ejecutar(subida()) is ResultadoSubida.Fallida)
        assertEquals(0, servidor.requestCount)
    }

    @Test
    fun actualizarEstados_escribeProcesadaYErrorPorOrden() = runBlocking {
        ManifestPrueba.crear(raiz, fotos = 3, subidas = setOf(1, 2, 3), extra = mapOf("remote_video_id" to "\"$VIDEO\""))
        val remoto = subida().actualizarEstados("rec_0001")
        assertEquals("con_errores", remoto!!.estado)
        assertEquals(ConteoRemoto(0, 0, 2, 1), remoto.conteo)
        val fotos = almacen.leer("rec_0001").fotos
        assertEquals(listOf(EstadoFoto.PROCESADA, EstadoFoto.ERROR, EstadoFoto.PROCESADA), fotos.map { it.estado })
        assertEquals("lado menor 200 px (mínimo 320)", fotos[1].error)
    }

    private fun json(codigo: Int, cuerpo: String): MockResponse =
        MockResponse().setResponseCode(codigo).setHeader("Content-Type", "application/json").setBody(cuerpo)

    private companion object {
        const val VIDEO = "6f1c2d3e-0000-4000-8000-000000000001"
        const val FIRMA = "FIRMA_SECRETA"
    }
}
