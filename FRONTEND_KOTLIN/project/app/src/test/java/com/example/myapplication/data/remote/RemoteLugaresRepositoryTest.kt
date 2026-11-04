package com.example.myapplication.data.remote

import com.example.myapplication.domain.model.CategoriaLugar
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
 * `RemoteLugaresRepository` contra MockWebServer (FE-3.1, apoyo de C1: Selección de destino muestra los lugares de
 * `GET /v1/places`). Los cuerpos siguen el ejemplo de `LugarPublico` del contrato del backend (§5.3).
 */
class RemoteLugaresRepositoryTest {

    private lateinit var servidor: MockWebServer
    private val lineasApi = mutableListOf<String>()
    private val registro = mutableListOf<String>()

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun repo(posicion: () -> Pair<Double, Double>? = { null }) = RemoteLugaresRepository(
        // Con un token: la ruta es pública y no debe llevar `Authorization` aunque haya uno.
        api = ClienteApi.crear(
            urlBase = servidor.url("/v1").toString(),
            token = { "token-que-no-debe-salir" },
            registrar = { lineasApi += it },
        ),
        posicion = posicion,
        registrar = { registro += it },
    )

    private fun lugar(
        id: String,
        nombre: String,
        categoria: String = "biblioteca",
        distancia: String = "null",
        imagen: String = "null",
    ) = """
        {"id": "$id", "nombre": "$nombre", "categoria": "$categoria", "lat": 6.2009, "lng": -75.5783,
         "alias": ["biblioteca", "la biblioteca"], "descripcion": "Edificio de tres pisos", "referencias": null,
         "imagen_url": $imagen, "distancia_m": $distancia}
    """.trimIndent()

    private fun lista(vararg lugares: String) =
        """{"items": [${lugares.joinToString(",")}], "total": ${lugares.size}}"""

    @Test
    fun sinPosicion_pideGetPlacesSinParametros_yMapeaEnElMismoOrden() {
        servidor.enqueue(
            MockResponse().setBody(
                lista(
                    lugar("3f2a", "Biblioteca Central"),
                    lugar("9b1c", "Cafetería Principal", categoria = "cafeteria", imagen = "\"https://s3/l.jpg\""),
                ),
            ),
        )

        val lugares = runBlocking { repo().obtenerLugares() }

        val peticion = servidor.takeRequest()
        assertEquals("GET", peticion.method)
        assertEquals("/v1/places", peticion.path)
        assertNull(peticion.getHeader("Authorization"))
        assertEquals(listOf("3f2a", "9b1c"), lugares.map { it.id })
        assertEquals(listOf("Biblioteca Central", "Cafetería Principal"), lugares.map { it.nombre })
        assertEquals(CategoriaLugar.CAFETERIA, lugares[1].categoria)
        assertEquals(listOf("biblioteca", "la biblioteca"), lugares[0].alias)
        assertNull(lugares[0].distanciaMetros)
        assertNull(lugares[0].imagenUrl)
        assertEquals("https://s3/l.jpg", lugares[1].imagenUrl)
        assertTrue(registro.isEmpty())
        assertEquals(1, lineasApi.count { it.startsWith("GET /v1/places -> 200") })
    }

    @Test
    fun conPosicion_enviaLatYLng_yRedondeaLaDistancia() {
        servidor.enqueue(
            MockResponse().setBody(
                lista(lugar("a", "Bloque 19", "bloque", distancia = "85.4"), lugar("b", "Entrada", "entrada", "120.5")),
            ),
        )

        val lugares = runBlocking { repo(posicion = { 6.2006 to -75.5783 }).obtenerLugares() }

        val peticion = servidor.takeRequest()
        assertEquals("/v1/places?lat=6.2006&lng=-75.5783", peticion.path)
        assertEquals(listOf(85, 121), lugares.map { it.distanciaMetros })
    }

    @Test
    fun categoriaDesconocida_seDescartaYQuedaEnElRegistro() {
        servidor.enqueue(MockResponse().setBody(lista(lugar("a", "Biblioteca"), lugar("b", "Piscina", "piscina"))))

        val lugares = runBlocking { repo().obtenerLugares() }

        assertEquals(listOf("a"), lugares.map { it.id })
        assertEquals(1, registro.size)
        assertTrue(registro[0], registro[0].contains("piscina"))
    }

    @Test
    fun idRepetido_seDescartaLaSegunda() {
        servidor.enqueue(MockResponse().setBody(lista(lugar("a", "Uno"), lugar("a", "Otro"), lugar("b", "Dos"))))

        val lugares = runBlocking { repo().obtenerLugares() }

        assertEquals(listOf("Uno", "Dos"), lugares.map { it.nombre })
        assertTrue(registro.single().contains("id repetido"))
    }

    @Test
    fun listaVacia_noEsUnError() {
        servidor.enqueue(MockResponse().setBody("""{"items": [], "total": 0}"""))

        assertTrue(runBlocking { repo().obtenerLugares() }.isEmpty())
    }

    @Test
    fun sinItems_esRespuestaInesperada() {
        servidor.enqueue(MockResponse().setBody("""{"total": 0}"""))

        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().obtenerLugares() } }
    }

    @Test
    fun lugarSinNombre_esRespuestaInesperada() {
        servidor.enqueue(
            MockResponse().setBody("""{"items": [{"id": "a", "categoria": "bano", "lat": 6.2, "lng": -75.5}]}"""),
        )

        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { repo().obtenerLugares() } }
    }

    @Test
    fun error503DelBackend_esApiException() {
        servidor.enqueue(
            MockResponse().setResponseCode(503).setBody(
                """{"error": {"codigo": "BASE_NO_DISPONIBLE", "mensaje": "La base no responde", "detalle": null}}""",
            ),
        )

        val e = assertThrows(ApiException::class.java) { runBlocking { repo().obtenerLugares() } }
        assertEquals(503, e.http)
        assertEquals(FalloApi.Desconocido(503, "BASE_NO_DISPONIBLE"), e.fallo)
    }

    @Test
    fun sinRed_esSinConexion_unaIOException() {
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))

        val e = assertThrows(IOException::class.java) { runBlocking { repo().obtenerLugares() } }
        assertTrue(e is SinConexionException)
    }
}
