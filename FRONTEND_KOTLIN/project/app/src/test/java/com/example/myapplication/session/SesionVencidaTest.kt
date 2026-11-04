package com.example.myapplication.session

import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.data.remote.EstadisticasAdminDto
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.LugarPublicoDto
import com.example.myapplication.data.remote.MapeoErroresApi
import com.example.myapplication.data.remote.VideoResumenDto
import com.example.myapplication.data.remote.llamar
import com.example.myapplication.data.repository.CredencialesInvalidasException
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import java.util.concurrent.CopyOnWriteArrayList

/**
 * FE-1.2, criterio C3 (ARCHITECTURE §5.3 y §5.10): un `401 TOKEN_EXPIRADO`, `TOKEN_INVALIDO` o `NO_AUTENTICADO` en una
 * ruta `/v1/admin/…` o `/v1/collect/…` cierra la sesión (`SessionManager.cerrarSesion()`) y emite `onSinSesion`; una
 * sesión con `expira_en` pasado es «sin sesión» y la petición no llega al servidor. Cada caso comprueba las tres cosas:
 * la sesión borrada (y cuántas veces se llamó a `cerrarSesion`), el evento `onSinSesion` y lo que recibió el servidor.
 */
class SesionVencidaTest {

    /** Rutas de prueba: las protegidas de los lotes siguientes y una pública. */
    private interface Rutas {
        @GET("admin/stats")
        suspend fun estadisticas(): Response<EstadisticasAdminDto>

        @POST("collect/videos")
        suspend fun crearVideo(@Body cuerpo: Map<String, String>): Response<VideoResumenDto>

        @GET("admin/videos/{id}")
        suspend fun video(@Path("id") id: String): Response<VideoResumenDto>

        @GET("places")
        suspend fun lugares(): Response<List<LugarPublicoDto>>
    }

    /** Almacén en memoria que cuenta las llamadas a `borrar()` (= `SessionManager.cerrarSesion()`). */
    private class AlmacenPrueba : AlmacenSesion {
        @Volatile var sesion: Sesion? = null
        @Volatile var borrados = 0
        override fun leer(): Sesion? = sesion
        override fun escribir(sesion: Sesion) { this.sesion = sesion }
        override fun borrar() { sesion = null; borrados++ }
    }

    private lateinit var servidor: MockWebServer
    private val almacen = AlmacenPrueba()
    private var ahora = 1_800_000_000_000L
    private val session = SessionManager(almacen, reloj = { ahora })
    private val eventos = CopyOnWriteArrayList<MotivoSinSesion>()
    private val registro = CopyOnWriteArrayList<String>()
    private val vigilante = VigilanteSesion(session, onSinSesion = { eventos += it }, registrar = { registro += it })
    private lateinit var rutas: Rutas

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
        rutas = Retrofit.Builder()
            .baseUrl(servidor.url("/v1/"))
            .client(ClienteApi.okHttp(registrar = {}, vigilante = vigilante))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(Rutas::class.java)
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun sesion(token: String = "token-1", expiraEnMs: Long = ahora + HORA) = Sesion(
        token = token,
        usuario = Usuario("u1", "Alejandro Gómez", "admin@campus.edu.co", Rol.ADMIN),
        expiraEnMs = expiraEnMs,
    )

    private fun error401(codigo: String) = MockResponse()
        .setResponseCode(401)
        .setHeader("WWW-Authenticate", "Bearer")
        .setBody("""{"error": {"codigo": "$codigo", "mensaje": "x", "detalle": null}}""")

    /** `llamar` lanza `ApiException(SesionVencida(codigo))`; devuelve el código. */
    private fun <T : Any> sesionVencida(peticion: suspend () -> Response<T>): String {
        val e = assertThrows(ApiException::class.java) { runBlocking { llamar<T>(peticion) } }
        val fallo = e.fallo
        assertTrue("fallo = $fallo", fallo is FalloApi.SesionVencida)
        return (fallo as FalloApi.SesionVencida).codigo
    }

    private fun comprobarSesionCerrada(motivo: MotivoSinSesion) {
        assertNull("la sesión debe quedar borrada", almacen.sesion)
        assertNull(session.obtener())
        assertEquals("cerrarSesion() una vez", 1, almacen.borrados)
        assertEquals("onSinSesion una vez", listOf(motivo), eventos.toList())
        assertTrue("el registro no lleva el token", registro.none { "token-1" in it })
    }

    @Test
    fun tokenExpirado_enAdmin_cierraLaSesionYEmiteOnSinSesion() {
        session.guardar(sesion())
        servidor.enqueue(error401("TOKEN_EXPIRADO"))

        assertEquals("TOKEN_EXPIRADO", sesionVencida { rutas.estadisticas() })

        val recibida = servidor.takeRequest()
        assertEquals("/v1/admin/stats", recibida.path)
        assertEquals("Bearer token-1", recibida.getHeader("Authorization"))
        comprobarSesionCerrada(MotivoSinSesion.Rechazada("TOKEN_EXPIRADO"))
    }

    @Test
    fun tokenInvalido_enCollect_cierraLaSesionYEmiteOnSinSesion() {
        session.guardar(sesion())
        servidor.enqueue(error401("TOKEN_INVALIDO"))

        assertEquals("TOKEN_INVALIDO", sesionVencida { rutas.crearVideo(mapOf("ref_cliente" to "rec_0001")) })

        val recibida = servidor.takeRequest()
        assertEquals("POST", recibida.method)
        assertEquals("/v1/collect/videos", recibida.path)
        assertEquals("Bearer token-1", recibida.getHeader("Authorization"))
        comprobarSesionCerrada(MotivoSinSesion.Rechazada("TOKEN_INVALIDO"))
    }

    @Test
    fun noAutenticado_enSubrutaDeAdmin_cierraLaSesionYEmiteOnSinSesion() {
        session.guardar(sesion())
        servidor.enqueue(error401("NO_AUTENTICADO"))

        assertEquals("NO_AUTENTICADO", sesionVencida { rutas.video("2b9f0000-0000-4000-8000-000000000002") })

        assertEquals("/v1/admin/videos/2b9f0000-0000-4000-8000-000000000002", servidor.takeRequest().path)
        comprobarSesionCerrada(MotivoSinSesion.Rechazada("NO_AUTENTICADO"))
    }

    @Test
    fun sesionConExpiraEnPasado_esSinSesion_yNoLlamaAlBackend() {
        session.guardar(sesion(expiraEnMs = ahora - 1))

        assertEquals(MapeoErroresApi.SIN_SESION_LOCAL, sesionVencida { rutas.estadisticas() })

        assertEquals("el servidor no recibió nada", 0, servidor.requestCount)
        comprobarSesionCerrada(MotivoSinSesion.SinSesionLocal)
    }

    @Test
    fun sesionQueVenceJustoAhora_tambienEsSinSesion() {
        session.guardar(sesion(expiraEnMs = ahora))

        assertNull(session.obtener())
        assertFalse(session.esAdmin())
        assertNull(almacen.sesion)
        assertEquals(1, almacen.borrados)
        assertEquals(0, servidor.requestCount)
    }

    @Test
    fun sinSesionGuardada_rutaProtegida_noLlamaAlBackend() {
        assertEquals(MapeoErroresApi.SIN_SESION_LOCAL, sesionVencida { rutas.crearVideo(emptyMap()) })

        assertEquals(0, servidor.requestCount)
        assertEquals(listOf<MotivoSinSesion>(MotivoSinSesion.SinSesionLocal), eventos.toList())
    }

    @Test
    fun otrosErrores_noCierranLaSesion() {
        session.guardar(sesion())
        servidor.enqueue(
            MockResponse().setResponseCode(403)
                .setBody("""{"error": {"codigo": "SIN_PERMISOS", "mensaje": "x", "detalle": null}}"""),
        )
        servidor.enqueue(
            MockResponse().setResponseCode(401)
                .setBody("""{"error": {"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "x", "detalle": null}}"""),
        )
        servidor.enqueue(MockResponse().setResponseCode(500).setBody("""{"message": "Internal Server Error"}"""))

        val e403 = assertThrows(ApiException::class.java) {
            runBlocking { llamar<EstadisticasAdminDto> { rutas.estadisticas() } }
        }
        assertEquals(FalloApi.SinPermisos, e403.fallo)
        assertThrows(CredencialesInvalidasException::class.java) {
            runBlocking { llamar<VideoResumenDto> { rutas.video("x") } }
        }
        assertThrows(java.io.IOException::class.java) {
            runBlocking { llamar<EstadisticasAdminDto> { rutas.estadisticas() } }
        }
        assertEquals(3, servidor.requestCount)

        assertNotNull(almacen.sesion)
        assertEquals(0, almacen.borrados)
        assertTrue(eventos.isEmpty())
    }

    @Test
    fun rutaPublica_conSesionVencida_seEnviaSinTokenYSinEvento() {
        session.guardar(sesion(expiraEnMs = ahora - 1))
        servidor.enqueue(MockResponse().setBody("[]"))

        runBlocking { llamar { rutas.lugares() } }

        val recibida = servidor.takeRequest()
        assertEquals("/v1/places", recibida.path)
        assertNull(recibida.getHeader("Authorization"))
        assertTrue(eventos.isEmpty())
    }

    @Test
    fun rechazoDeUnTokenAnterior_noCierraUnaSesionNueva() {
        session.guardar(sesion(token = "token-viejo"))
        // Mientras la petición con el token viejo está en el servidor, el admin vuelve a iniciar sesión.
        servidor.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                session.guardar(sesion(token = "token-nuevo"))
                return error401("TOKEN_EXPIRADO")
            }
        }

        assertEquals("TOKEN_EXPIRADO", sesionVencida { rutas.estadisticas() })

        assertEquals("Bearer token-viejo", servidor.takeRequest().getHeader("Authorization"))
        assertEquals("token-nuevo", almacen.sesion?.token)
        assertEquals(0, almacen.borrados)
        assertTrue(eventos.isEmpty())
    }

    private companion object {
        const val HORA = 60 * 60 * 1000L
    }
}
