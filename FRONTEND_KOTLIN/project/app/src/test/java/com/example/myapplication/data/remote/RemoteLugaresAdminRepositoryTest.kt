package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.DatosLugar
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.session.AlmacenSesion
import com.example.myapplication.session.MotivoSinSesion
import com.example.myapplication.session.SessionManager
import com.example.myapplication.session.VigilanteSesion
import com.google.gson.JsonParser
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

/**
 * `RemoteLugaresAdminRepository` contra MockWebServer (FE-3.4; apoyo de C1: un lugar creado en la app llega al backend
 * con lo que eligió la persona, y de C3: el `409 NOMBRE_DUPLICADO` llega como `FalloApi.Validacion`). Los cuerpos
 * siguen los ejemplos del contrato del backend (§5.5, `/v1/admin/places`). La sesión pasa por un `VigilanteSesion` real.
 */
class RemoteLugaresAdminRepositoryTest {

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
    private val cambios = ContadorCambios()
    private val registros = CopyOnWriteArrayList<String>()

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

    private fun repo() = RemoteLugaresAdminRepository(
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {}, vigilante = vigilante),
        cambios = cambios,
        registrar = { registros += it },
    )

    private fun lugarJson(
        id: String = "3f2a0000-0000-4000-8000-000000000001",
        nombre: String = "Biblioteca Central",
        categoria: String = "biblioteca",
        extra: String = """, "alias": ["biblioteca", "la biblioteca"], "descripcion": "Edificio de tres pisos…",
            "referencias": "Frente al lago…", "total_fotos": 4""",
    ) = """{"id": "$id", "nombre": "$nombre", "categoria": "$categoria", "lat": 6.2009, "lng": -75.5783,
        "imagen_url": null, "creado_en": "2026-10-25T20:11:00Z", "actualizado_en": "2026-10-25T20:11:00Z"$extra}"""

    private val datos = DatosLugar(
        nombre = "Bloque 19", categoria = CategoriaLugar.BLOQUE, lat = 6.200512, lng = -75.578311,
        alias = listOf("diecinueve"), descripcion = null, referencias = "Junto a la cafetería",
    )

    @Test
    fun listar_pideGetAdminPlacesConLaSesion_yMapeaTodosLosCampos() {
        servidor.enqueue(MockResponse().setBody("""{"items": [${lugarJson()}], "total": 1}"""))

        val lugares = runBlocking { repo().listar() }

        val peticion = servidor.takeRequest()
        assertEquals("GET", peticion.method)
        assertEquals("/v1/admin/places", peticion.path)
        assertEquals("Bearer token-1", peticion.getHeader("Authorization"))
        val l = lugares.single()
        assertEquals("3f2a0000-0000-4000-8000-000000000001", l.id)
        assertEquals("Biblioteca Central", l.nombre)
        assertEquals(CategoriaLugar.BIBLIOTECA, l.lugar.categoria)
        assertEquals(6.2009, l.lugar.lat, 0.0)
        assertEquals(-75.5783, l.lugar.lng, 0.0)
        assertEquals(listOf("biblioteca", "la biblioteca"), l.lugar.alias)
        assertNull(l.lugar.distanciaMetros)
        assertEquals("Edificio de tres pisos…", l.descripcion)
        assertEquals("Frente al lago…", l.referencias)
        assertEquals(4, l.totalFotos)
        assertEquals(0, cambios.version.value) // leer no avisa
    }

    @Test
    fun listar_descartaCategoriaDesconocidaEIdRepetido_conUnaLineaSinNombres_ySinAliasNiFotosUsaLosDefectos() {
        val sinOpcionales = lugarJson(id = "id-2", nombre = "Bloque 19", categoria = "bloque", extra = "")
        servidor.enqueue(
            MockResponse().setBody(
                """{"items": [${lugarJson(categoria = "parqueadero")}, $sinOpcionales, $sinOpcionales], "total": 3}""",
            ),
        )

        val lugares = runBlocking { repo().listar() }

        assertEquals(listOf("id-2"), lugares.map { it.id })
        assertEquals(emptyList<String>(), lugares[0].lugar.alias)
        assertEquals(0, lugares[0].totalFotos)
        assertNull(lugares[0].descripcion)
        assertEquals(2, registros.size)
        assertTrue(registros[0].contains("[parqueadero]"))
        assertFalse(registros.any { it.contains("Biblioteca") || it.contains("Bloque 19") })
    }

    @Test
    fun obtener_buscaPorIdEnLaLista_yNullSiNoEsta() {
        servidor.enqueue(MockResponse().setBody("""{"items": [${lugarJson()}], "total": 1}"""))
        servidor.enqueue(MockResponse().setBody("""{"items": [], "total": 0}"""))

        val r = repo()
        assertEquals("Biblioteca Central", runBlocking { r.obtener("3f2a0000-0000-4000-8000-000000000001") }?.nombre)
        assertNull(runBlocking { r.obtener("otro") })
    }

    @Test
    fun crear_enviaLugarEntradaExacto_yAvisaElCambio() {
        servidor.enqueue(
            MockResponse().setResponseCode(201)
                .setBody(lugarJson(id = "nuevo", nombre = "Bloque 19", categoria = "bloque", extra = """, "total_fotos": 0""")),
        )

        val l = runBlocking { repo().crear(datos) }

        val peticion = servidor.takeRequest()
        assertEquals("POST", peticion.method)
        assertEquals("/v1/admin/places", peticion.path)
        assertEquals("Bearer token-1", peticion.getHeader("Authorization"))
        val cuerpo = JsonParser.parseString(peticion.body.readUtf8()).asJsonObject
        assertEquals(setOf("nombre", "categoria", "lat", "lng", "alias", "referencias"), cuerpo.keySet())
        assertEquals("Bloque 19", cuerpo["nombre"].asString)
        assertEquals("bloque", cuerpo["categoria"].asString)
        assertEquals(6.200512, cuerpo["lat"].asDouble, 0.0)   // la coordenada del formulario, sin cambios
        assertEquals(-75.578311, cuerpo["lng"].asDouble, 0.0)
        assertEquals("diecinueve", cuerpo["alias"].asJsonArray.single().asString)
        assertEquals("nuevo", l.id)
        assertEquals(1, cambios.version.value)
    }

    @Test
    fun crear_nombreRepetido_esValidacion409_yNoAvisa() {
        servidor.enqueue(
            MockResponse().setResponseCode(409).setBody(
                """{"error": {"codigo": "NOMBRE_DUPLICADO", "mensaje": "Ya existe un lugar con ese nombre (sin distinguir mayúsculas ni tildes).", "detalle": null}}""",
            ),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().crear(datos) } }

        val fallo = e.fallo as FalloApi.Validacion
        assertEquals(409, fallo.http)
        assertEquals("NOMBRE_DUPLICADO", fallo.codigo)
        assertEquals(emptyList<CampoInvalido>(), fallo.campos)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun crear_422_traeLosCampos() {
        servidor.enqueue(
            MockResponse().setResponseCode(422).setBody(
                """{"error": {"codigo": "VALIDACION", "mensaje": "x", "detalle": {"campos": [{"campo": "nombre", "motivo": "Muy corto."}]}}}""",
            ),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().crear(datos) } }

        assertEquals(listOf(CampoInvalido("nombre", "Muy corto.")), (e.fallo as FalloApi.Validacion).campos)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun reemplazar_hacePutConElId_yAvisa() {
        servidor.enqueue(MockResponse().setBody(lugarJson(id = "id-7", nombre = "Bloque 19", categoria = "bloque")))

        val l = runBlocking { repo().reemplazar("id-7", datos.copy(descripcion = "Nueva")) }

        val peticion = servidor.takeRequest()
        assertEquals("PUT", peticion.method)
        assertEquals("/v1/admin/places/id-7", peticion.path)
        assertEquals("Nueva", JsonParser.parseString(peticion.body.readUtf8()).asJsonObject["descripcion"].asString)
        assertEquals("id-7", l.id)
        assertEquals(1, cambios.version.value)
    }

    @Test
    fun reemplazar_lugarBorrado_es404Desconocido() {
        servidor.enqueue(
            MockResponse().setResponseCode(404).setBody("""{"error": {"codigo": "NO_ENCONTRADO", "mensaje": "x", "detalle": null}}"""),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().reemplazar("id-7", datos) } }

        assertEquals(FalloApi.Desconocido(404, "NO_ENCONTRADO"), e.fallo)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun borrar_haceDelete204SinCuerpo_yAvisa() {
        servidor.enqueue(MockResponse().setResponseCode(204))

        runBlocking { repo().borrar("id-7") }

        val peticion = servidor.takeRequest()
        assertEquals("DELETE", peticion.method)
        assertEquals("/v1/admin/places/id-7", peticion.path)
        assertEquals("Bearer token-1", peticion.getHeader("Authorization"))
        assertEquals(1, cambios.version.value)
    }

    @Test
    fun sinSesion_noLlegaAlServidor_yEsSesionVencidaLocal() {
        almacenSesion.sesion = null

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().crear(datos) } }

        assertEquals(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), e.fallo)
        assertEquals(0, servidor.requestCount)
        assertEquals(listOf<MotivoSinSesion>(MotivoSinSesion.SinSesionLocal), eventos.toList())
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun sinRed_esSinConexion_ySinItemsEsRespuestaInesperada() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        servidor.enqueue(MockResponse().setBody("""{"total": 0}"""))

        assertThrows(SinConexionException::class.java) { runBlocking { repo().listar() } }
        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().listar() } }
    }
}
