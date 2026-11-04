package com.example.myapplication.data.remote

import com.example.myapplication.ApiConfig
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.UUID

/** Encabezados de §5.10 (`X-Request-Id`, `Authorization`), `RemoteBackendHealth` y forma de `ApiConfig`. */
class ClienteApiTest {

    private lateinit var servidor: MockWebServer
    private val lineas = mutableListOf<String>()

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun api(token: () -> String? = { null }) =
        ClienteApi.crear(urlBase = servidor.url("/v1").toString(), token = token, registrar = { lineas += it })

    @Test
    fun apiConfig_esHttpsConV1SinBarraFinal() {
        assertTrue(ApiConfig.BASE_URL.startsWith("https://"))
        assertTrue(ApiConfig.BASE_URL.endsWith("/v1"))
        assertEquals(ApiConfig.API_BASE_URL + "/v1", ApiConfig.BASE_URL)
        assertFalse(ApiConfig.API_BASE_URL.endsWith("/"))
    }

    @Test
    fun salud_usaLaRutaConV1_yRegistraElRequestId() {
        servidor.enqueue(MockResponse().setBody("""{"estado":"ok","version":"0.1.0","commit":"abc1234"}"""))
        val enLinea = runBlocking { RemoteBackendHealth(api()).estaEnLinea() }
        assertTrue(enLinea)
        val peticion = servidor.takeRequest()
        assertEquals("/v1/health", peticion.path)
        val rid = peticion.getHeader(ENCABEZADO_REQUEST_ID)!!
        UUID.fromString(rid) // es un UUID
        assertNull(peticion.getHeader("Authorization")) // ruta pública
        assertEquals(1, lineas.size)
        assertTrue(lineas[0], lineas[0].startsWith("GET /v1/health -> 200 ("))
        assertTrue(lineas[0], lineas[0].endsWith("rid=$rid"))
    }

    @Test
    fun salud_estadoDistintoOError_esFalse() {
        servidor.enqueue(MockResponse().setBody("""{"estado":"degradado"}"""))
        servidor.enqueue(MockResponse().setResponseCode(500).setBody("""{"message":"Internal Server Error"}"""))
        val h = RemoteBackendHealth(api())
        assertFalse(runBlocking { h.estaEnLinea() })
        assertFalse(runBlocking { h.estaEnLinea() })
    }

    @Test
    fun cadaPeticionLlevaUnRequestIdNuevo() {
        servidor.enqueue(MockResponse().setBody("""{"estado":"ok"}"""))
        servidor.enqueue(MockResponse().setBody("""{"estado":"ok"}"""))
        val a = api()
        runBlocking { llamar { a.salud() }; llamar { a.salud() } }
        val r1 = servidor.takeRequest().getHeader(ENCABEZADO_REQUEST_ID)
        val r2 = servidor.takeRequest().getHeader(ENCABEZADO_REQUEST_ID)
        assertFalse(r1 == r2)
    }

    @Test
    fun authorization_soloEnAdminYCollect_yNuncaEnElLog() {
        val cliente: OkHttpClient = ClienteApi.okHttp(token = { "secreto-token" }, registrar = { lineas += it })
        for (ruta in listOf("/v1/admin/stats", "/v1/collect/videos", "/v1/health", "/v1/places", "/v1/administrar")) {
            servidor.enqueue(MockResponse().setBody("{}"))
            cliente.newCall(Request.Builder().url(servidor.url(ruta)).build()).execute().close()
        }
        val auth = (1..5).map { servidor.takeRequest().getHeader("Authorization") }
        assertEquals(listOf("Bearer secreto-token", "Bearer secreto-token", null, null, null), auth)
        assertTrue(lineas.none { "secreto-token" in it })
    }

    @Test
    fun authorization_sinToken_noSeEnvia() {
        val cliente = ClienteApi.okHttp(token = { null }, registrar = {})
        servidor.enqueue(MockResponse().setBody("{}"))
        cliente.newCall(Request.Builder().url(servidor.url("/v1/admin/stats")).build()).execute().close()
        assertNull(servidor.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun falloDeRed_tambienSeRegistraConRequestId() {
        val url = servidor.url("/v1").toString()
        servidor.shutdown()
        val a = ClienteApi.crear(urlBase = url, registrar = { lineas += it })
        assertFalse(runBlocking { RemoteBackendHealth(a).estaEnLinea() })
        assertEquals(1, lineas.size)
        assertTrue(lineas[0], Regex("GET /v1/health -> falla \\w+ \\(\\d+ ms\\) rid=[0-9a-f-]{36}").matches(lineas[0]))
        servidor = MockWebServer().also { it.start() }
    }
}
