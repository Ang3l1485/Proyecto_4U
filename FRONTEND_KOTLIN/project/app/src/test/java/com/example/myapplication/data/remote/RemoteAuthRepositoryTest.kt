package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.CredencialesInvalidasException
import com.example.myapplication.domain.model.Rol
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * `RemoteAuthRepository` contra MockWebServer (FE-1.2, criterio C4: 200, 401 y error de red). Los cuerpos son los
 * ejemplos de `POST /v1/auth/login` del contrato del backend (§5.3).
 */
class RemoteAuthRepositoryTest {

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

    private fun repo() = RemoteAuthRepository(
        ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = { lineas += it }),
    )

    private fun respuesta200(rol: String = "admin", expiraEn: String? = "2026-10-24T03:04:05Z"): String {
        val expira = expiraEn?.let { "\"expira_en\": \"$it\"," } ?: ""
        return """
            {"token": "eyJhbGciOi.token.firma", $expira
             "usuario": {"id": "7c1e0000-0000-4000-8000-000000000001", "nombre": "Alejandro Gómez",
                         "correo": "admin@campus.edu.co", "rol": "$rol"}}
        """.trimIndent()
    }

    @Test
    fun login200_devuelveLaSesionConTokenUsuarioYExpiraEn() {
        servidor.enqueue(MockResponse().setBody(respuesta200()))

        val sesion = runBlocking { repo().login("admin@campus.edu.co", " clave con espacios ") }

        assertEquals("eyJhbGciOi.token.firma", sesion.token)
        assertEquals("7c1e0000-0000-4000-8000-000000000001", sesion.usuario.id)
        assertEquals("Alejandro Gómez", sesion.usuario.nombre)
        assertEquals("admin@campus.edu.co", sesion.usuario.correo)
        assertEquals(Rol.ADMIN, sesion.usuario.rol)
        assertEquals(1_792_811_045_000L, sesion.expiraEnMs) // 2026-10-24T03:04:05Z en milisegundos Unix
        // La petición: POST /v1/auth/login con el JSON del contrato, la contraseña sin recortar y sin Authorization.
        val peticion = servidor.takeRequest()
        assertEquals("POST", peticion.method)
        assertEquals("/v1/auth/login", peticion.path)
        assertTrue(peticion.getHeader("Content-Type")!!.startsWith("application/json"))
        assertEquals(
            """{"identificador":"admin@campus.edu.co","password":" clave con espacios "}""",
            peticion.body.readUtf8(),
        )
        assertNull(peticion.getHeader("Authorization"))
        // La única línea registrada no lleva ni la contraseña ni el token.
        assertEquals(1, lineas.size)
        assertTrue(lineas[0], lineas[0].startsWith("POST /v1/auth/login -> 200 ("))
        assertTrue(lineas.none { "clave" in it || "eyJ" in it })
    }

    @Test
    fun login200_deUnUser_devuelveLaSesionSinFiltrarElRol() {
        servidor.enqueue(MockResponse().setBody(respuesta200(rol = "user")))
        val sesion = runBlocking { repo().login("validacion+user@campus.edu.co", "x") }
        assertEquals(Rol.USER, sesion.usuario.rol)
    }

    @Test
    fun login401CredencialesInvalidas_lanzaCredencialesInvalidasException() {
        servidor.enqueue(
            MockResponse().setResponseCode(401).setHeader("WWW-Authenticate", "Bearer").setBody(
                """{"error": {"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "Correo o contraseña incorrectos.", "detalle": null}}""",
            ),
        )
        assertThrows(CredencialesInvalidasException::class.java) {
            runBlocking { repo().login("admin@campus.edu.co", "mala") }
        }
    }

    @Test
    fun loginSinRed_lanzaIOExceptionDeSinConexion() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        val e = assertThrows(IOException::class.java) {
            runBlocking { repo().login("admin@campus.edu.co", "clave") }
        }
        assertTrue(e.toString(), e is SinConexionException)
    }

    @Test
    fun login200SinExpiraEn_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setBody(respuesta200(expiraEn = null)))
        assertThrows(RespuestaInesperadaException::class.java) {
            runBlocking { repo().login("admin@campus.edu.co", "clave") }
        }
    }

    @Test
    fun login503ServicioOcupado_esApiExceptionDesconocido() {
        servidor.enqueue(
            MockResponse().setResponseCode(503).setHeader("Retry-After", "5").setBody(
                """{"error": {"codigo": "SERVICIO_OCUPADO", "mensaje": "Inténtalo de nuevo.", "detalle": null}}""",
            ),
        )
        val e = assertThrows(ApiException::class.java) {
            runBlocking { repo().login("admin@campus.edu.co", "clave") }
        }
        assertEquals(FalloApi.Desconocido(503, "SERVICIO_OCUPADO"), e.fallo)
    }
}
