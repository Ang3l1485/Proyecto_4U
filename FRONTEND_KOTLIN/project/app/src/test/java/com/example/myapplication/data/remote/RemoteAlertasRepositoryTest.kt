package com.example.myapplication.data.remote

import com.example.myapplication.data.local.AlmacenAlertasMemoria
import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.data.repository.ResultadoSincronizacion
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.session.AlmacenSesion
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
 * `RemoteAlertasRepository` contra MockWebServer (FE-3.3; apoyo de C1: una alerta creada en el teléfono llega con
 * `sincronizar` y queda en la lista del servidor; de C2: crear y borrar antes de sincronizar envía **solo** un
 * `eliminar`; de C3: la lista sale de `GET /v1/admin/alerts`). Cuerpos según backend §5.3 y §5.5; sesión con un
 * `VigilanteSesion` real, como `RemoteLugaresAdminRepositoryTest`.
 */
class RemoteAlertasRepositoryTest {

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
    private val vigilante = VigilanteSesion(session, onSinSesion = {})
    private val cambios = ContadorCambios()
    private val registros = CopyOnWriteArrayList<String>()
    private val almacen = AlmacenAlertasMemoria()

    private val idA = "1d6e0000-0000-4000-8000-00000000000a"
    private val idB = "1d6e0000-0000-4000-8000-00000000000b"

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
        almacenSesion.sesion = Sesion("token-1", Usuario("u1", "Alejandro", "admin@campus.edu.co", Rol.ADMIN), ahora + 3_600_000L)
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun repo() = RemoteAlertasRepository(
        almacen = almacen,
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {}, vigilante = vigilante),
        cambios = cambios,
        registrar = { registros += it },
    )

    private fun alertaJson(id: String, mensaje: String, version: Int = 1, activa: Boolean = true) =
        """{"id": "$id", "lat": 6.2011, "lng": -75.579, "mensaje": "$mensaje", "tipo": "agua", "prioridad": "alta",
            "radio_m": 20, "activa": $activa, "vigencia_desde": null, "vigencia_hasta": "2026-10-29T19:15:59Z",
            "actualizado_en": "2026-10-22T20:11:00Z", "version": $version, "creado_en": "2026-10-22T20:11:00Z",
            "creado_por": {"id": "u1", "nombre": "Alejandro"}, "actualizado_por": {"id": "u1", "nombre": "Alejandro"}}"""

    private fun lista(vararg items: String) = MockResponse().setBody("""{"items": [${items.joinToString(",")}], "total": ${items.size}}""")

    private fun resultados(vararg r: Triple<String, String, String>) = MockResponse().setBody(
        """{"generado_en": "2026-10-26T19:16:00Z", "resultados": [${
            r.joinToString(",") { (id, op, estado) ->
                """{"id": "$id", "op": "$op", "estado": "$estado", "codigo": ${if (estado == "error") "\"VALIDACION\"" else "null"}}"""
            }
        }]}""",
    )

    @Test
    fun refrescar_leeLaListaAdmin_conVigenciaYVersion() = runBlocking {
        servidor.enqueue(lista(alertaJson(idA, "Hay un lago", version = 3, activa = false)))
        val r = repo()

        r.refrescar()

        val req = servidor.takeRequest()
        assertEquals("GET", req.method)
        assertEquals("/v1/admin/alerts", req.path)
        assertEquals("Bearer token-1", req.getHeader("Authorization"))
        val a = r.estado.value.visibles.single()
        assertEquals(Alerta(idA, 6.2011, -75.579, "Hay un lago", "agua", "alta", 20, false, null, 1_793_301_359_000L, 3, 1_792_699_860_000L), a)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun crearYEditarEnLocal_sincronizaUnSoloUpsertConElCuerpoExacto_yRelee() = runBlocking {
        val r = repo()
        r.guardar(Alerta(idA, 6.200512, -75.578311, "uno"))
        r.guardar(Alerta(idA, 6.200512, -75.578311, "Ten cuidado, bancas", "mobiliario", "normal", 15, true, 1_793_150_000_000L, null))
        assertEquals(2, almacen.escrituras)
        assertEquals(0, servidor.requestCount)   // guardar no llama al backend

        servidor.enqueue(resultados(Triple(idA, "upsert", "ok")))
        servidor.enqueue(lista(alertaJson(idA, "Ten cuidado, bancas")))
        val res = r.sincronizar()

        val req = servidor.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/v1/admin/alerts/sincronizar", req.path)
        assertEquals("Bearer token-1", req.getHeader("Authorization"))
        assertEquals(
            JsonParser.parseString(
                """{"cambios": [{"op": "upsert", "alerta": {"id": "$idA", "lat": 6.200512, "lng": -75.578311,
                   "mensaje": "Ten cuidado, bancas", "tipo": "mobiliario", "prioridad": "normal", "radio_m": 15,
                   "activa": true, "vigencia_desde": "2026-10-28T01:13:20Z"}}]}""",
            ),
            JsonParser.parseString(req.body.readUtf8()),
        )
        assertEquals("/v1/admin/alerts", servidor.takeRequest().path)
        assertEquals(ResultadoSincronizacion(1, 1, emptyList(), true), res)
        assertTrue(r.estado.value.pendientes.isEmpty())
        assertEquals(1, r.estado.value.servidor.single().version)
        assertEquals(1, cambios.version.value)
    }

    @Test
    fun crearYBorrarAntesDeSincronizar_enviaSoloEliminar() = runBlocking {
        // C2: una sola operación por id, la última. El backend responde `ok` y no deja rastro (backend §4.11).
        val r = repo()
        r.guardar(Alerta(idA, 6.2, -75.57, "validacion-3-3-c2"))
        r.eliminar(idA)
        servidor.enqueue(resultados(Triple(idA, "eliminar", "ok")))
        servidor.enqueue(lista())

        r.sincronizar()

        assertEquals(
            JsonParser.parseString("""{"cambios": [{"op": "eliminar", "id": "$idA"}]}"""),
            JsonParser.parseString(servidor.takeRequest().body.readUtf8()),
        )
        assertTrue(r.estado.value.pendientes.isEmpty())
        assertTrue(r.estado.value.visibles.isEmpty())
    }

    @Test
    fun rechazadoPorValidacion_quedaPendienteYMarcado_yElOkSale() = runBlocking {
        val r = repo()
        r.guardar(Alerta(idA, 6.2, -75.57, "a"))
        r.guardar(Alerta(idB, 6.2, -75.57, "b"))
        servidor.enqueue(resultados(Triple(idA, "upsert", "error"), Triple(idB, "upsert", "ok")))
        servidor.enqueue(lista(alertaJson(idB, "b")))

        val res = r.sincronizar()

        assertEquals(listOf(idA), res.rechazados)
        assertEquals(1, res.aplicados)
        assertEquals(listOf(idA), r.estado.value.pendientes.map { it.id })
        assertEquals(setOf(idA), r.estado.value.rechazadas)
        // El pendiente se sigue viendo encima de la lista releída.
        assertEquals(setOf(idA, idB), r.estado.value.visibles.map { it.id }.toSet())
    }

    @Test
    fun masDeCienPendientes_vanEnDosLotes() = runBlocking {
        val r = repo()
        val ids = (1..101).map { "1d6e0000-0000-4000-8000-%012d".format(it) }
        ids.forEach { r.guardar(Alerta(it, 6.2, -75.57, "m")) }
        servidor.enqueue(resultados(*ids.take(100).map { Triple(it, "upsert", "ok") }.toTypedArray()))
        servidor.enqueue(resultados(Triple(ids.last(), "upsert", "ok")))
        servidor.enqueue(lista())

        val res = r.sincronizar()

        assertEquals(100, JsonParser.parseString(servidor.takeRequest().body.readUtf8()).asJsonObject.getAsJsonArray("cambios").size())
        assertEquals(1, JsonParser.parseString(servidor.takeRequest().body.readUtf8()).asJsonObject.getAsJsonArray("cambios").size())
        assertEquals(101, res.aplicados)
        assertTrue(r.estado.value.pendientes.isEmpty())
    }

    @Test
    fun sinRed_lanzaSinConexion_yLosPendientesQuedanIntactos() = runBlocking {
        val r = repo()
        r.guardar(Alerta(idA, 6.2, -75.57, "a"))
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))

        assertThrows(SinConexionException::class.java) { runBlocking { r.sincronizar() } }
        assertEquals(listOf<OperacionAlerta>(OperacionAlerta.Upsert(Alerta(idA, 6.2, -75.57, "a"))), r.estado.value.pendientes)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun sinSesion_noLlegaAlServidor_yLosPendientesQuedan() = runBlocking {
        almacenSesion.sesion = null
        val r = repo()
        r.eliminar(idA)

        val e = assertThrows(ApiException::class.java) { runBlocking { r.sincronizar() } }

        assertEquals(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), e.fallo)
        assertEquals(0, servidor.requestCount)
        assertEquals(1, r.estado.value.pendientes.size)
    }

    @Test
    fun releerFalla_noEsFalloDeLaSincronizacion() = runBlocking {
        val r = repo()
        r.guardar(Alerta(idA, 6.2, -75.57, "a"))
        servidor.enqueue(resultados(Triple(idA, "upsert", "ok")))
        servidor.enqueue(MockResponse().setResponseCode(503).setBody("""{"error": {"codigo": "BASE_NO_DISPONIBLE", "mensaje": "x", "detalle": null}}"""))

        val res = r.sincronizar()

        assertFalse(res.releida)
        assertTrue(r.estado.value.pendientes.isEmpty())
        assertEquals(listOf(idA), r.estado.value.servidor.map { it.id })   // lo confirmado ya está en la lista local
    }

    @Test
    fun refrescarPublicas_esPublica_yConservaLasInactivas() = runBlocking {
        servidor.enqueue(lista(alertaJson(idB, "inactiva", activa = false)))
        val r = repo()
        r.refrescar()
        servidor.takeRequest()
        servidor.enqueue(
            MockResponse().setBody(
                """{"generado_en": "2026-10-26T19:16:00Z", "completo": true, "alertas": [${alertaJson(idA, "activa")}], "eliminadas": []}""",
            ),
        )

        r.refrescarPublicas()

        val req = servidor.takeRequest()
        assertEquals("/v1/alerts", req.path)
        assertNull(req.getHeader("Authorization"))
        assertEquals(listOf(idA, idB), r.estado.value.visibles.map { it.id })
    }

    @Test
    fun moverUnaVisible_dejaUnUpsertConLaPosicionNueva() = runBlocking {
        servidor.enqueue(lista(alertaJson(idA, "a")))
        val r = repo()
        r.refrescar()

        r.mover(idA, 6.3, -75.6)
        r.mover("no-existe", 1.0, 1.0)

        val op = r.estado.value.pendientes.single() as OperacionAlerta.Upsert
        assertEquals(6.3 to -75.6, op.alerta.lat to op.alerta.lng)
        assertEquals("a", op.alerta.mensaje)
    }

    @Test
    fun sinItems_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setBody("""{"total": 0}"""))
        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().refrescar() } }
    }
}
