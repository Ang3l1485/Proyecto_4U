package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.CredencialesInvalidasException
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * Tabla «Errores → modelos de la app» de ARCHITECTURE §5.10, fila por fila (FE-1.1, C2). Las filas de red se prueban
 * de punta a punta con MockWebServer y [llamar]; el resto, con [MapeoErroresApi.clasificar].
 */
class MapeoErroresApiTest {

    private lateinit var servidor: MockWebServer
    private lateinit var api: CampusApi

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {})
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun error(codigo: String, detalle: String = "null") =
        """{"error": {"codigo": "$codigo", "mensaje": "m", "detalle": $detalle}}"""

    private fun llamarYCapturar(): Exception = runBlocking {
        try {
            llamar { api.salud() }
            fail("se esperaba una excepción")
            throw IllegalStateException()
        } catch (e: Exception) {
            e
        }
    }

    // Fila 1: sin red, timeout, 5xx de API Gateway → IOException («sin conexión»).

    @Test
    fun sinRed_esSinConexionException() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        val e = llamarYCapturar()
        assertTrue("$e", e is SinConexionException)
        assertTrue(e is IOException)
        assertEquals(FalloApi.SinConexion, MapeoErroresApi.deExcepcion(e))
    }

    @Test
    fun servidorApagado_esSinConexion() {
        val url = servidor.url("/v1").toString()
        servidor.shutdown()
        val apiSinServidor = ClienteApi.crear(urlBase = url, registrar = {})
        val e = runBlocking { runCatching { llamar { apiSinServidor.salud() } }.exceptionOrNull() }
        assertTrue("$e", e is SinConexionException)
        servidor = MockWebServer().also { it.start() } // para @After
    }

    @Test
    fun timeout_esSinConexion() {
        val apiLenta = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {})
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        // RemoteBackendHealth corta a los 200 ms; el resultado es «sin conexión» (false), no una espera de 30 s.
        val enLinea = runBlocking { RemoteBackendHealth(apiLenta, limiteMs = 200).estaEnLinea() }
        assertEquals(false, enLinea)
    }

    @Test
    fun cincoXXDeApiGateway_esSinConexion() {
        for (http in listOf(500, 502, 503, 504)) {
            assertEquals("HTTP $http", FalloApi.SinConexion,
                MapeoErroresApi.clasificar(http, """{"message":"Internal Server Error"}"""))
        }
        servidor.enqueue(MockResponse().setResponseCode(503).setBody("""{"message":"Service Unavailable"}"""))
        assertTrue(llamarYCapturar() is SinConexionException)
    }

    // Fila 2: 401 CREDENCIALES_INVALIDAS → CredencialesInvalidasException.

    @Test
    fun credencialesInvalidas() {
        assertEquals(FalloApi.CredencialesInvalidas, MapeoErroresApi.clasificar(401, error("CREDENCIALES_INVALIDAS")))
        servidor.enqueue(MockResponse().setResponseCode(401).setBody(error("CREDENCIALES_INVALIDAS")))
        assertTrue(llamarYCapturar() is CredencialesInvalidasException)
    }

    // Fila 3: 401 TOKEN_EXPIRADO / TOKEN_INVALIDO / NO_AUTENTICADO → sesión vencida.

    @Test
    fun tokens_sonSesionVencida() {
        for (codigo in listOf("TOKEN_EXPIRADO", "TOKEN_INVALIDO", "NO_AUTENTICADO")) {
            assertEquals(FalloApi.SesionVencida(codigo), MapeoErroresApi.clasificar(401, error(codigo)))
        }
    }

    // Fila 4: 403 SIN_PERMISOS.

    @Test
    fun sinPermisos() {
        assertEquals(FalloApi.SinPermisos, MapeoErroresApi.clasificar(403, error("SIN_PERMISOS")))
    }

    // Fila 5: 429 (de API Gateway, cuerpo {"message"}) → demasiados intentos.

    @Test
    fun demasiadosIntentos() {
        assertEquals(FalloApi.DemasiadosIntentos, MapeoErroresApi.clasificar(429, """{"message":"Too Many Requests"}"""))
        assertEquals(FalloApi.DemasiadosIntentos, MapeoErroresApi.clasificar(429, null))
    }

    // Fila 6: 503 EMBEDDING_NO_DISPONIBLE.

    @Test
    fun embeddingNoDisponible() {
        assertEquals(FalloApi.EmbeddingNoDisponible, MapeoErroresApi.clasificar(503, error("EMBEDDING_NO_DISPONIBLE")))
    }

    // FE-3.2: 400 FOTOS_INVALIDAS de POST /v1/localize → FotosInvalidas(detalle.indice, detalle.motivo).

    @Test
    fun fotosInvalidas400_conIndiceYMotivo() {
        val cuerpo = error("FOTOS_INVALIDAS", """{"indice": 2, "motivo": "embeddings la rechazó (IMAGEN_INVALIDA)"}""")
        assertEquals(
            FalloApi.FotosInvalidas(2, "embeddings la rechazó (IMAGEN_INVALIDA)"),
            MapeoErroresApi.clasificar(400, cuerpo),
        )
        assertEquals(FalloApi.FotosInvalidas(null, null), MapeoErroresApi.clasificar(400, error("FOTOS_INVALIDAS")))
        // Otro 400 sigue siendo Desconocido.
        assertEquals(
            FalloApi.Desconocido(400, "SOLICITUD_INVALIDA"),
            MapeoErroresApi.clasificar(400, error("SOLICITUD_INVALIDA")),
        )
    }

    // Fila 7: 409 / 422 → mensaje del campo (detalle.campos).

    @Test
    fun validacion422_conCampos() {
        val cuerpo = error("VALIDACION", """{"campos": [{"campo": "radio_m", "motivo": "fuera de rango"}]}""")
        val fallo = MapeoErroresApi.clasificar(422, cuerpo)
        assertEquals(
            FalloApi.Validacion(422, "VALIDACION", "m", listOf(CampoInvalido("radio_m", "fuera de rango"))),
            fallo,
        )
    }

    @Test
    fun conflicto409_sinCampos() {
        val fallo = MapeoErroresApi.clasificar(409, error("NOMBRE_DUPLICADO"))
        assertEquals(FalloApi.Validacion(409, "NOMBRE_DUPLICADO", "m", emptyList()), fallo)
    }

    // Fila 8: cualquier otro → «algo salió mal», con el X-Request-Id.

    @Test
    fun otros_sonDesconocido() {
        assertEquals(FalloApi.Desconocido(500, "ERROR_INTERNO"), MapeoErroresApi.clasificar(500, error("ERROR_INTERNO")))
        assertEquals(FalloApi.Desconocido(503, "BASE_NO_DISPONIBLE"),
            MapeoErroresApi.clasificar(503, error("BASE_NO_DISPONIBLE")))
        assertEquals(FalloApi.Desconocido(404, "NO_ENCONTRADO"), MapeoErroresApi.clasificar(404, error("NO_ENCONTRADO")))
        assertEquals(FalloApi.Desconocido(401, null), MapeoErroresApi.clasificar(401, "<html>no es json</html>"))
        assertEquals(FalloApi.Desconocido(403, null), MapeoErroresApi.clasificar(403, ""))
    }

    @Test
    fun otros_llevanElRequestIdDeLaRespuesta() {
        servidor.enqueue(
            MockResponse().setResponseCode(500).setHeader(ENCABEZADO_REQUEST_ID, "rid-123").setBody(error("ERROR_INTERNO")),
        )
        val e = llamarYCapturar()
        assertTrue("$e", e is ApiException)
        e as ApiException
        assertEquals("rid-123", e.requestId)
        assertEquals(500, e.http)
        assertEquals(FalloApi.Desconocido(500, "ERROR_INTERNO"), MapeoErroresApi.deExcepcion(e))
    }

    @Test
    fun cuerpo2xxRoto_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setResponseCode(200).setBody("{no es json"))
        assertTrue(llamarYCapturar() is RespuestaInesperadaException)
    }
}
