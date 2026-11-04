package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.FiltrosImagenes
import com.example.myapplication.domain.model.OrdenVideos
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * `RemoteVideoRepository` contra MockWebServer (FE-4.1; apoyo de C1: 7.11–7.14 con datos del backend; C2: el borrado
 * espera el `202` y avisa para que la Lista y la Galería se refresquen; C3: renombrar es un `PATCH` con el nombre). Los
 * cuerpos siguen los ejemplos del contrato del backend (§5.5, BE-4.1). La sesión pasa por un `VigilanteSesion` real.
 */
class RemoteVideoRepositoryTest {

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
    private val cambiosLugares = ContadorCambios()

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

    private fun repo() = RemoteVideoRepository(
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {}, vigilante = vigilante),
        cambios = cambios,
        cambiosLugares = cambiosLugares,
    )

    private fun videoJson(id: String, nombre: String, estado: String = "procesado", extra: String = "") =
        """{"id": "$id", "numero": 12, "nombre": "$nombre", "ref_cliente": "rec_0003", "estado": "$estado",
            "creado_en": "2026-10-27T15:04:05Z", "iniciado_en": "2026-10-27T14:00:00Z",
            "finalizado_en": "2026-10-27T14:08:32Z", "duracion_s": 512, "distancia_m": 340.5, "pasos": 470,
            "inicio": {"lat": 6.2001, "lng": -75.5786, "rumbo": 90.0}, "total_fotos": 120,
            "conteo": {"pendiente_subida": 1, "subida": 2, "procesada": 3, "error": 4},
            "creado_por": {"id": "u1", "nombre": "Alejandro Gómez"}$extra}"""

    private fun imagenJson(id: String, video: String, orden: Int, miniatura: String? = "https://s3/t_$id.jpg") =
        """{"id": "$id", "video_id": "$video", "orden": $orden, "lat": 6.2003, "lng": -75.5788, "rumbo": 182.0,
            "capturada_en": "2026-10-20T14:01:10Z", "estado": "procesada", "error": null, "calidad": "alta",
            "lugar": {"id": "lugar-1", "nombre": "Biblioteca Central"}, "notas": null,
            "url": "https://s3/$id.jpg?X-Amz-Signature=x", "url_miniatura": ${miniatura?.let { "\"$it\"" } ?: "null"},
            "url_expira_en": "2026-10-23T16:0$orden:05Z"}"""

    @Test
    fun todosLosVideos_pideTodasLasPaginasConQyOrden_yMapeaLasFilas() {
        servidor.enqueue(
            MockResponse().setBody(
                """{"items": [${videoJson("v1", "Entrada norte")}, ${videoJson("v2", "Bloque 19", "pendiente")}],
                    "total": 3, "pagina": 1, "por_pagina": 100}""",
            ),
        )
        servidor.enqueue(
            MockResponse().setBody("""{"items": [${videoJson("v3", "Biblioteca", "con_errores")}], "total": 3, "pagina": 2, "por_pagina": 100}"""),
        )

        val p = runBlocking { repo().todosLosVideos("  entrada ", OrdenVideos.NOMBRE) }

        val r1 = servidor.takeRequest()
        assertEquals("GET", r1.method)
        assertEquals("/v1/admin/videos?q=entrada&orden=nombre&dir=asc&pagina=1&por_pagina=100", r1.path)
        assertEquals("Bearer token-1", r1.getHeader("Authorization"))
        assertEquals("/v1/admin/videos?q=entrada&orden=nombre&dir=asc&pagina=2&por_pagina=100", servidor.takeRequest().path)
        assertEquals(3, p.total)
        assertEquals(listOf("v1", "v2", "v3"), p.items.map { it.id })
        val v1 = p.items[0]
        assertEquals("Entrada norte", v1.nombre)
        assertEquals(10, v1.fotos) // la suma del conteo (las registradas), no total_fotos
        assertEquals(340.5, v1.distanciaMetros!!, 0.0)
        assertEquals(512L, v1.duracionSegundos)
        assertEquals("2026-10-27T14:08:32Z", v1.finalizadoEn)
        assertEquals(EstadoVideo.PROCESADO, v1.estado)
        assertEquals(EstadoVideo.SUBIDA_A_MEDIAS, p.items[1].estado)
        assertEquals(EstadoVideo.CON_ERRORES, p.items[2].estado)
        assertEquals(false, v1.local)
        assertEquals(0, cambios.version.value) // leer no avisa
    }

    @Test
    fun todosLosVideos_sinQ_noLoEnvia_yUnaPaginaBasta() {
        servidor.enqueue(MockResponse().setBody("""{"items": [], "total": 0, "pagina": 1, "por_pagina": 100}"""))

        val p = runBlocking { repo().todosLosVideos(" ", OrdenVideos.RECIENTES) }

        assertEquals("/v1/admin/videos?orden=fecha&dir=desc&pagina=1&por_pagina=100", servidor.takeRequest().path)
        assertEquals(0, p.total)
        assertEquals(1, servidor.requestCount)
    }

    @Test
    fun detalle_mapeaFotosConUrls_miniaturaDeRespaldo_yVencimientoMasTemprano() {
        val fotos = """, "fotos": [${imagenJson("img-2", "v1", 2, miniatura = null)}, ${imagenJson("img-1", "v1", 1)}]"""
        servidor.enqueue(MockResponse().setBody(videoJson("v1", "Entrada norte", extra = fotos)))

        val v = runBlocking { repo().detalle("v1") }!!

        assertEquals("/v1/admin/videos/v1", servidor.takeRequest().path)
        assertEquals(listOf("img-1", "img-2"), v.fotos.map { it.id }) // por orden
        assertEquals("https://s3/t_img-1.jpg", v.fotos[0].urlMiniatura)
        assertEquals("https://s3/img-2.jpg?X-Amz-Signature=x", v.fotos[1].urlMiniatura) // sin miniatura: la original
        assertEquals("img-2.jpg", v.fotos[1].nombreArchivo) // sin la firma
        assertEquals("lugar-1", v.fotos[0].lugarId)
        assertEquals(1, v.fotos[0].orden)
        assertEquals(MapeoDatosApi.isoAMilis("2026-10-23T16:01:05Z"), v.urlsVencenEnMs)
        assertEquals("2026-10-27T14:08:32Z", v.finalizadoEn)
        assertEquals(false, v.local)
    }

    @Test
    fun detalle_404o422_esNull() {
        servidor.enqueue(
            MockResponse().setResponseCode(404)
                .setBody("""{"error": {"codigo": "NO_ENCONTRADO", "mensaje": "No existe", "detalle": null}}"""),
        )
        servidor.enqueue(
            MockResponse().setResponseCode(422)
                .setBody("""{"error": {"codigo": "VALIDACION", "mensaje": "id", "detalle": {"campos": [{"campo": "id", "motivo": "uuid"}]}}}"""),
        )

        assertNull(runBlocking { repo().detalle("v-borrado") })
        assertNull(runBlocking { repo().detalle("no-es-uuid") })
    }

    @Test
    fun renombrar_enviaPatchConElNombreRecortado_yAvisa() {
        servidor.enqueue(MockResponse().setBody(videoJson("v1", "validacion-4-1-renombrado")))

        val r = runBlocking { repo().renombrar("v1", "  validacion-4-1-renombrado ") }

        val peticion = servidor.takeRequest()
        assertEquals("PATCH", peticion.method)
        assertEquals("/v1/admin/videos/v1", peticion.path)
        assertEquals("Bearer token-1", peticion.getHeader("Authorization"))
        val cuerpo = JsonParser.parseString(peticion.body.readUtf8()).asJsonObject
        assertEquals(setOf("nombre"), cuerpo.keySet())
        assertEquals("validacion-4-1-renombrado", cuerpo["nombre"].asString)
        assertEquals("validacion-4-1-renombrado", r.nombre)
        assertEquals(1, cambios.version.value)
        assertEquals(0, cambiosLugares.version.value) // renombrar no cambia los conteos de los lugares
    }

    @Test
    fun renombrar_422_esValidacion_yNoAvisa() {
        servidor.enqueue(
            MockResponse().setResponseCode(422).setBody(
                """{"error": {"codigo": "VALIDACION", "mensaje": "Revisa los datos", "detalle": {"campos": [{"campo": "nombre", "motivo": "vacío"}]}}}""",
            ),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().renombrar("v1", "x") } }

        assertTrue(e.fallo is FalloApi.Validacion)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun eliminar_esperaEl202_devuelveFotosRetiradas_yAvisaVideosYLugares() {
        servidor.enqueue(
            MockResponse().setResponseCode(202)
                .setBody("""{"id": "v1", "estado": "eliminado", "fotos_retiradas": 120, "purga": "programada"}"""),
        )

        val fotos = runBlocking { repo().eliminar("v1") }

        val peticion = servidor.takeRequest()
        assertEquals("DELETE", peticion.method)
        assertEquals("/v1/admin/videos/v1", peticion.path)
        assertEquals(120, fotos)
        assertEquals(1, cambios.version.value)
        assertEquals(1, cambiosLugares.version.value)
    }

    @Test
    fun eliminar_404CuentaComoHecho_ySinRedLanzaSinAvisar() {
        servidor.enqueue(
            MockResponse().setResponseCode(404)
                .setBody("""{"error": {"codigo": "NO_ENCONTRADO", "mensaje": "No existe", "detalle": null}}"""),
        )
        assertEquals(0, runBlocking { repo().eliminar("v1") })
        assertEquals(1, cambios.version.value)

        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        assertThrows(SinConexionException::class.java) { runBlocking { repo().eliminar("v2") } }
        assertEquals(1, cambios.version.value) // un error no avisa
    }

    @Test
    fun eliminar_500_lanzaApiException() {
        servidor.enqueue(
            MockResponse().setResponseCode(500).setHeader("X-Request-Id", "rid-1")
                .setBody("""{"error": {"codigo": "ERROR_INTERNO", "mensaje": "falta SQS_URL_PURGA", "detalle": null}}"""),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().eliminar("v1") } }

        assertEquals(FalloApi.Desconocido(500, "ERROR_INTERNO"), e.fallo)
        assertEquals("rid-1", e.requestId)
        assertEquals(0, cambios.version.value)
    }

    @Test
    fun eliminarImagen_204_y404SonHechos() {
        servidor.enqueue(MockResponse().setResponseCode(204))
        servidor.enqueue(
            MockResponse().setResponseCode(404)
                .setBody("""{"error": {"codigo": "NO_ENCONTRADO", "mensaje": "No existe", "detalle": null}}"""),
        )

        runBlocking {
            repo().eliminarImagen("img-1")
            repo().eliminarImagen("img-1") // repetido: 404, ya estaba borrada
        }

        val peticion = servidor.takeRequest()
        assertEquals("DELETE", peticion.method)
        assertEquals("/v1/admin/images/img-1", peticion.path)
        assertEquals(2, cambios.version.value)
        assertEquals(2, cambiosLugares.version.value)
    }

    @Test
    fun imagenes_pasaLosFiltrosDelServidor_yMapeaLaPagina() {
        servidor.enqueue(
            MockResponse().setBody(
                """{"items": [${imagenJson("img-1", "v1", 1)}, ${imagenJson("img-2", "v1", 2)}], "total": 50, "pagina": 2, "por_pagina": 24}""",
            ),
        )

        val p = runBlocking {
            repo().imagenes(
                FiltrosImagenes(q = " norte ", videoId = "v1", lugarId = "lugar-1", estado = EstadoFoto.PENDIENTE, calidad = CalidadFoto.ALTA),
                pagina = 2,
                porPagina = 24,
            )
        }

        assertEquals(
            "/v1/admin/images?video_id=v1&lugar_id=lugar-1&estado=pendiente_subida&calidad=alta&q=norte&pagina=2&por_pagina=24",
            servidor.takeRequest().path,
        )
        assertEquals(50, p.total)
        assertEquals(2, p.pagina)
        assertEquals(listOf("img-1", "img-2"), p.fotos.map { it.id })
        assertEquals("", p.fotos[0].videoNombre) // lo pone la Galería
        assertEquals("Biblioteca Central", p.fotos[0].lugar)
        assertEquals(MapeoDatosApi.isoAMilis("2026-10-23T16:01:05Z"), p.vencenEnMs)
    }

    @Test
    fun imagenes_sinTotal_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setBody("""{"items": []}"""))

        assertThrows(RespuestaInesperadaException::class.java) {
            runBlocking { repo().imagenes(FiltrosImagenes(), 1, 24) }
        }
    }

    @Test
    fun lote_reasignarSinLugar_enviaLugarIdNullExplicito_yDevuelveLasFallidas() {
        servidor.enqueue(
            MockResponse().setBody("""{"procesadas": 1, "fallidas": [{"id": "img-2", "codigo": "NO_ENCONTRADO"}]}"""),
        )

        val r = runBlocking { repo().lote(AccionLote.REASIGNAR, listOf("img-1", "img-2", "img-1"), null) }

        val peticion = servidor.takeRequest()
        assertEquals("POST", peticion.method)
        assertEquals("/v1/admin/images/lote", peticion.path)
        assertTrue(peticion.getHeader("Content-Type")!!.startsWith("application/json"))
        val texto = peticion.body.readUtf8()
        assertTrue(texto, texto.contains("\"lugar_id\":null"))
        val cuerpo = JsonParser.parseString(texto).asJsonObject
        assertEquals("reasignar", cuerpo["accion"].asString)
        assertEquals(listOf("img-1", "img-2"), cuerpo["ids"].asJsonArray.map { it.asString }) // sin repetidos
        assertEquals(1, r.procesadas)
        assertEquals("NO_ENCONTRADO", r.fallidas.single().codigo)
        assertEquals(1, cambios.version.value)
        assertEquals(1, cambiosLugares.version.value)
    }

    @Test
    fun lote_eliminarDeMasDe200_seEnviaEnPartes_ySinLugarId() {
        servidor.enqueue(MockResponse().setBody("""{"procesadas": 200, "fallidas": []}"""))
        servidor.enqueue(MockResponse().setBody("""{"procesadas": 49, "fallidas": [{"id": "img-249", "codigo": "ERROR_INTERNO"}]}"""))
        val ids = (0 until 250).map { "img-$it" }

        val r = runBlocking { repo().lote(AccionLote.ELIMINAR, ids, "ignorado") }

        val primero = JsonParser.parseString(servidor.takeRequest().body.readUtf8()).asJsonObject
        val segundo = JsonParser.parseString(servidor.takeRequest().body.readUtf8()).asJsonObject
        assertEquals(200, primero["ids"].asJsonArray.size())
        assertEquals(50, segundo["ids"].asJsonArray.size())
        assertEquals(setOf("accion", "ids"), primero.keySet()) // eliminar no lleva lugar_id
        assertEquals(249, r.procesadas)
        assertEquals(1, r.fallidas.size)
        assertEquals(1, cambios.version.value)
    }

    @Test
    fun sinSesion_noLlegaAlServidor() {
        almacenSesion.sesion = null

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().eliminar("v1") } }

        assertTrue(e.fallo is FalloApi.SesionVencida)
        assertEquals(0, servidor.requestCount)
        assertEquals(0, cambios.version.value)
    }
}
