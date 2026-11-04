package com.example.myapplication.data.remote

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.local.FotoPreparada
import com.example.myapplication.data.local.PreparadorFoto
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.ResultadoFrame
import com.google.gson.JsonParser
import kotlinx.coroutines.runBlocking
import okhttp3.MultipartReader
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * FE-5.3: `RemoteFrameRepository` contra MockWebServer: el `multipart/form-data` de `POST /v1/localize/frame` (backend
 * §5.3: una parte `foto` y `metadatos`), el mapeo de la respuesta y los errores (sin red, `503`, `400`, respuesta rota).
 */
class RemoteFrameRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var servidor: MockWebServer

    private val preparador = PreparadorFoto { original, destino ->
        destino.writeText("copia de ${original.name}")
        FotoPreparada(destino.length(), 1024, 768)
    }

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun repo(appVersion: String? = "1.0", prep: PreparadorFoto = preparador) = RemoteFrameRepository(
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), token = { "token-que-no-debe-salir" }, registrar = {}),
        preparador = prep,
        appVersion = appVersion,
    )

    private fun foto(): File = File(tmp.newFolder(), "guia_1.jpg").apply { writeText("original") }

    private val ok = """
        {"resultado": "ok", "posicion": {"lat": 6.200104, "lng": -75.578612, "radio_m": 5.0}, "confianza": 0.86,
         "nivel": "alta", "distancia_previa_m": 11.6, "radio_busqueda_m": 40.0, "imagenes_en_radio": 37,
         "lugar_cercano": {"id": "3f2a", "nombre": "Biblioteca Central", "distancia_m": 12.4},
         "referencias": [], "version_vector": "dinov2-vits14/pp-v1", "latencia_ms": 240}
    """.trimIndent()

    private val sin = """
        {"resultado": "sin_coincidencias", "posicion": null, "confianza": 0, "nivel": null, "distancia_previa_m": null,
         "radio_busqueda_m": 40.0, "imagenes_en_radio": 0, "lugar_cercano": null, "referencias": [],
         "version_vector": "dinov2-vits14/pp-v1", "latencia_ms": 120}
    """.trimIndent()

    private fun partes(peticion: RecordedRequest): List<List<String?>> {
        val tipo = peticion.getHeader("Content-Type")!!
        assertTrue(tipo, tipo.startsWith("multipart/form-data; boundary="))
        val lector = MultipartReader(peticion.body, tipo.substringAfter("boundary="))
        val salida = mutableListOf<List<String?>>()
        while (true) {
            val parte = lector.nextPart() ?: break
            val disposicion = parte.headers["Content-Disposition"].orEmpty()
            val nombre = Regex("""name="([^"]*)"""").find(disposicion)?.groupValues?.get(1)
            val archivo = Regex("""filename="([^"]*)"""").find(disposicion)?.groupValues?.get(1)
            salida += listOf(nombre, archivo, parte.headers["Content-Type"], parte.body.readUtf8())
        }
        return salida
    }

    @Test
    fun unaParteFotoYMetadatos_respuestaMapeada_copiaBorrada() {
        servidor.enqueue(MockResponse().setBody(ok))
        val f = foto()
        val r = runBlocking { repo().localizarFrame(f, 84.54, 6.20018, -75.57854, 40.0) }

        val peticion = servidor.takeRequest()
        assertEquals("POST", peticion.method)
        assertEquals("/v1/localize/frame", peticion.path)
        assertNull(peticion.getHeader("Authorization"))
        val p = partes(peticion)
        assertEquals(2, p.size)
        assertEquals(listOf("foto", "envio_guia_1.jpg", "image/jpeg", "copia de guia_1.jpg"), p[0])
        assertEquals("metadatos", p[1][0])
        assertTrue(p[1][2]!!.startsWith("application/json"))
        assertEquals(
            JsonParser.parseString(
                """{"rumbo": 84.5, "posicion_previa": {"lat": 6.20018, "lng": -75.57854}, "radio_m": 40.0, "app_version": "1.0"}""",
            ),
            JsonParser.parseString(p[1][3]),
        )
        assertEquals(ResultadoFrame.Ubicado(6.200104, -75.578612, 5.0, 0.86, NivelConfianza.ALTA, 11.6, 40.0, 37), r)
        // La copia re-codificada se borra; el original es de quien llama.
        assertFalse(File(f.parentFile, "envio_guia_1.jpg").exists())
        assertTrue(f.isFile)
    }

    @Test
    fun rumboNuloSiempreVa_radioRecortado_sinAppVersion() {
        servidor.enqueue(MockResponse().setBody(sin))
        val r = runBlocking { repo(appVersion = "  ").localizarFrame(foto(), Double.NaN, 6.2, -75.5, 250.0) }
        val meta = partes(servidor.takeRequest())[1][3]
        assertEquals(
            JsonParser.parseString("""{"rumbo": null, "posicion_previa": {"lat": 6.2, "lng": -75.5}, "radio_m": 100.0}"""),
            JsonParser.parseString(meta),
        )
        assertEquals(ResultadoFrame.SinCoincidencias(40.0, 0), r)

        servidor.enqueue(MockResponse().setBody(sin))
        runBlocking { repo(appVersion = null).localizarFrame(foto(), 359.96, 6.2, -75.5, null) }
        assertEquals(
            JsonParser.parseString("""{"rumbo": 0.0, "posicion_previa": {"lat": 6.2, "lng": -75.5}}"""),
            JsonParser.parseString(partes(servidor.takeRequest())[1][3]),
        )
    }

    @Test
    fun errores() {
        servidor.enqueue(
            MockResponse().setResponseCode(503).setHeader("X-Request-Id", "rid-503")
                .setBody("""{"error": {"codigo": "EMBEDDING_NO_DISPONIBLE", "mensaje": "m", "detalle": null}}"""),
        )
        val e503 = assertThrows(ApiException::class.java) { runBlocking { repo().localizarFrame(foto(), null, 6.2, -75.5, null) } }
        assertEquals(FalloApi.EmbeddingNoDisponible, e503.fallo)
        assertEquals("rid-503", e503.requestId)

        servidor.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"error": {"codigo": "FOTOS_INVALIDAS", "mensaje": "m", "detalle": {"indice": 0, "motivo": "falta la parte foto"}}}"""),
        )
        val e400 = assertThrows(ApiException::class.java) { runBlocking { repo().localizarFrame(foto(), null, 6.2, -75.5, null) } }
        assertEquals(FalloApi.FotosInvalidas(0, "falta la parte foto"), e400.fallo)

        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        assertThrows(SinConexionException::class.java) { runBlocking { repo().localizarFrame(foto(), null, 6.2, -75.5, null) } }

        servidor.enqueue(MockResponse().setBody("""{"resultado": "ok", "radio_busqueda_m": 40.0, "imagenes_en_radio": 3}"""))
        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().localizarFrame(foto(), null, 6.2, -75.5, null) } }

        servidor.enqueue(MockResponse().setBody(ok.replace("\"alta\"", "\"altísima\"")))
        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().localizarFrame(foto(), null, 6.2, -75.5, null) } }
    }

    @Test
    fun fotoIlegibleNoLlamaAlBackend() {
        val ilegible = PreparadorFoto { _, _ -> throw FotoIlegibleException("no se pudo decodificar") }
        assertThrows(FotoIlegibleException::class.java) {
            runBlocking { repo(prep = ilegible).localizarFrame(foto(), null, 6.2, -75.5, null) }
        }
        assertEquals(0, servidor.requestCount)
    }
}
