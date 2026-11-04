package com.example.myapplication.data.remote

import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.ManifestPrueba
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.session.AlmacenSesion
import com.example.myapplication.session.MotivoSinSesion
import com.example.myapplication.session.SessionManager
import com.example.myapplication.session.VigilanteSesion
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
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.concurrent.CopyOnWriteArrayList

/**
 * `RemoteAdminRepository` contra MockWebServer (FE-2.2; apoyo de C1: los cuatro datos del backend son los de
 * `GET /v1/admin/stats`, con la fecha ISO en milisegundos; y de C2: «fotos pendientes» sale de la cola local). Los
 * cuerpos siguen el ejemplo del contrato del backend (§5.5). La sesión pasa por un `VigilanteSesion` real, como en la app.
 */
class RemoteAdminRepositoryTest {

    @get:Rule
    val tmp = TemporaryFolder()

    /** Almacén de sesión en memoria (como el de `SesionVencidaTest`). */
    private class AlmacenPrueba : AlmacenSesion {
        @Volatile var sesion: Sesion? = null
        override fun leer(): Sesion? = sesion
        override fun escribir(sesion: Sesion) { this.sesion = sesion }
        override fun borrar() { sesion = null }
    }

    private lateinit var servidor: MockWebServer
    private val almacenSesion = AlmacenPrueba()
    private val ahora = 1_800_000_000_000L
    private val session = SessionManager(almacenSesion, reloj = { ahora })
    private val eventos = CopyOnWriteArrayList<MotivoSinSesion>()
    private val vigilante = VigilanteSesion(session, onSinSesion = { eventos += it })
    private var llamadasPendientes = 0

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
        almacenSesion.sesion = Sesion(
            token = "token-1",
            usuario = Usuario("u1", "Alejandro Gómez", "admin@campus.edu.co", Rol.ADMIN),
            expiraEnMs = ahora + 3_600_000L,
        )
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun repo(fotosPendientes: suspend () -> Int = { llamadasPendientes++; 7 }) = RemoteAdminRepository(
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {}, vigilante = vigilante),
        fotosPendientes = fotosPendientes,
    )

    private fun estadisticas(ultimoVideo: String = """{"numero": 12, "creado_en": "2026-10-23T15:04:05Z"}""") =
        MockResponse().setBody(
            """{"total_fotos": 2842, "total_lugares": 48, "alertas_activas": 3, "ultimo_video": $ultimoVideo}""",
        )

    @Test
    fun ok_pideGetAdminStatsConLaSesion_yMapeaLosCuatroDatosYLasPendientes() {
        servidor.enqueue(estadisticas())

        val r = runBlocking { repo().obtenerResumen() }

        val peticion = servidor.takeRequest()
        assertEquals("GET", peticion.method)
        assertEquals("/v1/admin/stats", peticion.path)
        assertEquals("Bearer token-1", peticion.getHeader("Authorization"))
        assertEquals(2842, r.totalFotos)
        assertEquals(48, r.totalLugares)
        assertEquals(3, r.alertasActivas)
        assertEquals(12, r.ultimoVideoNumero)
        assertEquals(1_792_767_845_000L, r.ultimoVideoFecha) // 2026-10-23T15:04:05Z
        assertEquals(7, r.fotosPendientes)
        assertEquals(1, llamadasPendientes)
    }

    @Test
    fun sinVideos_numeroYFechaNulos() {
        servidor.enqueue(estadisticas(ultimoVideo = "null"))

        val r = runBlocking { repo().obtenerResumen() }

        assertNull(r.ultimoVideoNumero)
        assertNull(r.ultimoVideoFecha)
        assertEquals(7, r.fotosPendientes)
    }

    @Test
    fun fechaConFraccion_seConvierte_yEnOtroFormato_quedaSinFechaConElNumero() {
        servidor.enqueue(estadisticas("""{"numero": 13, "creado_en": "2026-10-23T15:04:05.250Z"}"""))
        servidor.enqueue(estadisticas("""{"numero": 14, "creado_en": "2026-10-23T10:04:05-05:00"}"""))

        val conFraccion = runBlocking { repo().obtenerResumen() }
        val otroFormato = runBlocking { repo().obtenerResumen() }

        assertEquals(13, conFraccion.ultimoVideoNumero)
        assertEquals(1_792_767_845_000L, conFraccion.ultimoVideoFecha)
        assertEquals(14, otroFormato.ultimoVideoNumero)
        assertNull(otroFormato.ultimoVideoFecha) // el backend siempre da UTC con Z (§5.1): otra forma no se adivina
    }

    @Test
    fun ultimoVideoSinNumero_esRespuestaInesperada() {
        servidor.enqueue(estadisticas("""{"creado_en": "2026-10-23T15:04:05Z"}"""))

        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().obtenerResumen() } }
        assertEquals(0, llamadasPendientes)
    }

    @Test
    fun faltaUnTotal_esRespuestaInesperada_sinContarPendientes() {
        servidor.enqueue(MockResponse().setBody("""{"total_fotos": 2842, "total_lugares": 48, "ultimo_video": null}"""))

        val e = assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().obtenerResumen() } }
        assertTrue(e.message.orEmpty().contains("alertas_activas"))
        assertEquals(0, llamadasPendientes)
    }

    @Test
    fun sinSesion_noLlegaAlServidor_yEsSesionVencidaLocal() {
        almacenSesion.sesion = null

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().obtenerResumen() } }

        assertEquals(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), e.fallo)
        assertEquals(0, servidor.requestCount)
        assertEquals(listOf<MotivoSinSesion>(MotivoSinSesion.SinSesionLocal), eventos.toList())
        assertEquals(0, llamadasPendientes)
    }

    @Test
    fun tokenExpirado_cierraLaSesion_yEsSesionVencida() {
        servidor.enqueue(
            MockResponse().setResponseCode(401)
                .setBody("""{"error": {"codigo": "TOKEN_EXPIRADO", "mensaje": "x", "detalle": null}}"""),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().obtenerResumen() } }

        assertEquals(FalloApi.SesionVencida("TOKEN_EXPIRADO"), e.fallo)
        assertNull(almacenSesion.sesion)
        assertEquals(listOf<MotivoSinSesion>(MotivoSinSesion.Rechazada("TOKEN_EXPIRADO")), eventos.toList())
        assertEquals(0, llamadasPendientes)
    }

    @Test
    fun sinRed_esSinConexion_sinContarPendientes() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))

        assertThrows(SinConexionException::class.java) { runBlocking { repo().obtenerResumen() } }
        assertEquals(0, llamadasPendientes)
    }

    @Test
    fun cincoXxDeApiGateway_esSinConexion() {
        servidor.enqueue(MockResponse().setResponseCode(503).setBody("""{"message": "Service Unavailable"}"""))

        assertThrows(SinConexionException::class.java) { runBlocking { repo().obtenerResumen() } }
    }

    @Test
    fun errorInterno_esApiExceptionDesconocido_conSuRequestId() {
        servidor.enqueue(
            MockResponse().setResponseCode(500).setHeader("X-Request-Id", "rid-500")
                .setBody("""{"error": {"codigo": "ERROR_INTERNO", "mensaje": "x", "detalle": null}}"""),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().obtenerResumen() } }

        assertEquals(FalloApi.Desconocido(500, "ERROR_INTERNO"), e.fallo)
        assertEquals("rid-500", e.requestId)
    }

    @Test
    fun pendientes_vienenDeLaColaLocal_soloFinalizadosSinSubir() {
        val raiz = tmp.newFolder("recoleccion")
        ManifestPrueba.crear(raiz, id = "rec_0001", fotos = 3, subidas = setOf(1)) // 2 pendientes
        ManifestPrueba.crear(raiz, id = "rec_0002", fotos = 4) // 4 pendientes
        ManifestPrueba.crear(raiz, id = "rec_0003", fotos = 5, estado = "en_curso") // no cuenta (se retoma en 7.4)
        ManifestPrueba.crear(raiz, id = "rec_0004", fotos = 2, subidas = setOf(1, 2)) // ya subido: 0
        val almacen = AlmacenRecorridos(raiz)
        servidor.enqueue(estadisticas())

        val r = runBlocking { repo(fotosPendientes = { almacen.contarFotosPendientes() }).obtenerResumen() }

        assertEquals(6, r.fotosPendientes)
        assertEquals(2842, r.totalFotos)
    }
}
