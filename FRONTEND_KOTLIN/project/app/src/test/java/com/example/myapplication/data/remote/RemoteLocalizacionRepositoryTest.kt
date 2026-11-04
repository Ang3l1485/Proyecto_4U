package com.example.myapplication.data.remote

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.local.FotoPreparada
import com.example.myapplication.data.local.PreparadorFoto
import com.example.myapplication.data.repository.FotoEscaneo
import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ReferenciaLugar
import com.example.myapplication.domain.model.ResultadoUbicacion
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
 * `RemoteLocalizacionRepository` contra MockWebServer (FE-3.2, apoyo de C1 y C4): el `multipart/form-data` de
 * `POST /v1/localize` (backend §5.3) y el mapeo de su respuesta y sus errores. La re-codificación se sustituye por un
 * doble (la real usa `android.graphics`; sus límites los prueba `RecodificacionFotoTest`).
 */
class RemoteLocalizacionRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var servidor: MockWebServer
    private val preparadas = mutableListOf<Pair<String, String>>()

    /** Doble del `Recodificador`: escribe «copia de <original>» en el destino. */
    private val preparador = PreparadorFoto { original, destino ->
        preparadas += original.name to destino.name
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

    private fun repo(appVersion: String? = "1.0", prep: PreparadorFoto = preparador) = RemoteLocalizacionRepository(
        // Con un token: la ruta es pública y no debe llevar `Authorization` aunque haya uno.
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), token = { "token-que-no-debe-salir" }, registrar = {}),
        preparador = prep,
        appVersion = appVersion,
    )

    private fun fotos(rumbos: List<Double?>): List<FotoEscaneo> {
        val carpeta = tmp.newFolder() // una carpeta de escaneo nueva en cada llamada
        return rumbos.mapIndexed { i, r ->
            FotoEscaneo(File(carpeta, "escaneo_${i + 1}.jpg").apply { writeText("original ${i + 1}") }, r)
        }
    }

    private val ok = """
        {"resultado": "ok", "posicion": {"lat": 6.200104, "lng": -75.578612, "radio_m": 8.5}, "confianza": 0.78,
         "nivel": "alta", "correccion_rumbo_grados": -6.0,
         "lugar_cercano": {"id": "3f2a", "nombre": "Biblioteca Central", "distancia_m": 12.4},
         "referencias": [{"id": "9b0c", "nombre": "Bloque de los Trillizos", "distancia_m": 35.2, "rumbo_grados": 95.0}],
         "fotos_usadas": 5, "fotos_con_coincidencia": 4, "version_vector": "dinov2-vits14/pp-v1", "latencia_ms": 640}
    """.trimIndent()

    private fun error(http: Int, codigo: String, detalle: String = "null") = MockResponse()
        .setResponseCode(http)
        .setHeader("X-Request-Id", "rid-$http")
        .setBody("""{"error": {"codigo": "$codigo", "mensaje": "m", "detalle": $detalle}}""")

    /** Partes del multipart: (nombre, nombre de archivo, Content-Type, cuerpo), en orden. */
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
    fun cincoFotos_multipartEnOrden_conMetadatos_yRespuestaMapeada() {
        servidor.enqueue(MockResponse().setBody(ok))
        val lista = fotos(listOf(12.0, 84.5, 156.0, 228.3, 300.1))

        val r = runBlocking { repo().localizar(lista) }

        val peticion = servidor.takeRequest()
        assertEquals("POST", peticion.method)
        assertEquals("/v1/localize", peticion.path)
        assertNull(peticion.getHeader("Authorization"))
        val p = partes(peticion)
        assertEquals(6, p.size)
        for (i in 0 until 5) {
            assertEquals(listOf("fotos", "envio_${i + 1}.jpg", "image/jpeg", "copia de escaneo_${i + 1}.jpg"), p[i])
        }
        assertEquals("metadatos", p[5][0])
        assertNull(p[5][1])
        assertTrue(p[5][2]!!.startsWith("application/json"))
        assertEquals(
            JsonParser.parseString("""{"rumbos": [12.0, 84.5, 156.0, 228.3, 300.1], "origen": "escaneo", "app_version": "1.0"}"""),
            JsonParser.parseString(p[5][3]),
        )
        // Las copias quedan en la carpeta del escaneo (las borra FotosEscaneo.cerrar con los originales).
        assertEquals((1..5).map { "escaneo_$it.jpg" to "envio_$it.jpg" }, preparadas)
        assertTrue(File(lista[0].archivo.parentFile, "envio_1.jpg").isFile)

        assertEquals(
            ResultadoUbicacion.Ubicado(
                posicion = PosicionEstimada(6.200104, -75.578612, 8.5),
                confianza = 0.78,
                nivel = NivelConfianza.ALTA,
                correccionRumboGrados = -6.0,
                lugarCercano = LugarCercano("3f2a", "Biblioteca Central", 12.4),
                referencias = listOf(ReferenciaLugar("9b0c", "Bloque de los Trillizos", 35.2, 95.0)),
                fotosUsadas = 5,
                fotosConCoincidencia = 4,
            ),
            r,
        )
    }

    @Test
    fun rumbosNormalizados_nulos_ySinAppVersion() {
        servidor.enqueue(MockResponse().setBody("""{"resultado": "sin_coincidencias", "confianza": 0, "fotos_usadas": 3}"""))

        val r = runBlocking { repo(appVersion = "  ").localizar(fotos(listOf(359.96, null, -10.0))) }

        assertEquals(ResultadoUbicacion.SinCoincidencias(3), r)
        val metadatos = JsonParser.parseString(partes(servidor.takeRequest()).last()[3]).asJsonObject
        assertEquals(JsonParser.parseString("[0.0, null, 350.0]"), metadatos["rumbos"])
        assertFalse(metadatos.has("app_version"))
    }

    @Test
    fun appVersionLarga_seRecortaA40() {
        servidor.enqueue(MockResponse().setBody("""{"resultado": "sin_coincidencias", "fotos_usadas": 1}"""))
        runBlocking { repo(appVersion = "x".repeat(50)).localizar(fotos(listOf(10.0))) }
        val metadatos = JsonParser.parseString(partes(servidor.takeRequest()).last()[3]).asJsonObject
        assertEquals("x".repeat(40), metadatos["app_version"].asString)
    }

    @Test
    fun sinLugarCercano_lasReferenciasSeConservanEnOrden() {
        // Backend §5.3: con lugar_cercano = null, la primera referencia es el lugar más cercano.
        servidor.enqueue(
            MockResponse().setBody(
                """{"resultado": "ok", "posicion": {"lat": 6.2, "lng": -75.58, "radio_m": 5.0}, "confianza": 0.4,
                    "nivel": "baja", "correccion_rumbo_grados": null, "lugar_cercano": null,
                    "referencias": [{"id": "a", "nombre": "Auditorio", "distancia_m": 90.0, "rumbo_grados": 0.0},
                                    {"id": "b", "nombre": "Bloque 19", "distancia_m": 140.0, "rumbo_grados": 180.0}],
                    "fotos_usadas": 5, "fotos_con_coincidencia": 2}""",
            ),
        )
        val r = runBlocking { repo().localizar(fotos(listOf(1.0, 2.0, 3.0, 4.0, 5.0))) } as ResultadoUbicacion.Ubicado
        assertNull(r.lugarCercano)
        assertNull(r.correccionRumboGrados)
        assertEquals(NivelConfianza.BAJA, r.nivel)
        assertEquals(listOf("Auditorio", "Bloque 19"), r.referencias.map { it.nombre })
    }

    @Test
    fun embeddingNoDisponible503_esApiExceptionConSuRequestId() {
        servidor.enqueue(error(503, "EMBEDDING_NO_DISPONIBLE"))
        val e = assertThrows(ApiException::class.java) {
            runBlocking { repo().localizar(fotos(listOf(1.0, 2.0, 3.0, 4.0, 5.0))) }
        }
        assertEquals(FalloApi.EmbeddingNoDisponible, e.fallo)
        assertEquals(503, e.http)
        assertEquals("rid-503", e.requestId)
    }

    @Test
    fun fotosInvalidas400_traeIndiceYMotivo() {
        servidor.enqueue(error(400, "FOTOS_INVALIDAS", """{"indice": 2, "motivo": "embeddings la rechazó (IMAGEN_INVALIDA)"}"""))
        val e = assertThrows(ApiException::class.java) {
            runBlocking { repo().localizar(fotos(listOf(1.0, 2.0, 3.0))) }
        }
        assertEquals(FalloApi.FotosInvalidas(2, "embeddings la rechazó (IMAGEN_INVALIDA)"), e.fallo)
    }

    @Test
    fun validacion422DeMetadatos() {
        servidor.enqueue(error(422, "VALIDACION", """{"campos": [{"campo": "metadatos.rumbos.1", "motivo": "fuera de rango"}]}"""))
        val e = assertThrows(ApiException::class.java) {
            runBlocking { repo().localizar(fotos(listOf(1.0, 2.0))) }
        }
        assertEquals(
            FalloApi.Validacion(422, "VALIDACION", "m", listOf(CampoInvalido("metadatos.rumbos.1", "fuera de rango"))),
            e.fallo,
        )
    }

    @Test
    fun sinRed_esSinConexion() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        assertThrows(SinConexionException::class.java) {
            runBlocking { repo().localizar(fotos(listOf(1.0))) }
        }
    }

    @Test
    fun okIncompleto_oNivelDesconocido_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setBody("""{"resultado": "ok", "confianza": 0.9, "nivel": "alta", "fotos_usadas": 5}"""))
        servidor.enqueue(
            MockResponse().setBody(
                """{"resultado": "ok", "posicion": {"lat": 6.2, "lng": -75.58, "radio_m": 5.0}, "confianza": 0.9,
                    "nivel": "altisima", "fotos_usadas": 5}""",
            ),
        )
        servidor.enqueue(MockResponse().setBody("""{"resultado": "quizas", "fotos_usadas": 5}"""))
        repeat(3) {
            assertThrows(RespuestaInesperadaException::class.java) {
                runBlocking { repo().localizar(fotos(listOf(1.0))) }
            }
        }
    }

    @Test
    fun fotoIlegible_noLlamaAlBackend() {
        val malo = PreparadorFoto { o, _ -> throw FotoIlegibleException("no se pudo leer ${o.name}") }
        assertThrows(FotoIlegibleException::class.java) {
            runBlocking { repo(prep = malo).localizar(fotos(listOf(1.0, 2.0))) }
        }
        assertEquals(0, servidor.requestCount)
    }

    @Test
    fun ceroOMasDeCincoFotos_seRechazanSinLlamar() {
        assertThrows(IllegalArgumentException::class.java) { runBlocking { repo().localizar(emptyList()) } }
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo().localizar(fotos(List(6) { 1.0 })) }
        }
        assertEquals(0, servidor.requestCount)
    }
}
