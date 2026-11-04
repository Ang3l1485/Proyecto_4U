package com.example.myapplication.data.remote

import com.example.myapplication.data.local.AlmacenCacheAlertasArchivo
import com.example.myapplication.data.local.AlmacenCacheAlertasMemoria
import com.example.myapplication.data.local.CachePublica
import com.example.myapplication.data.local.ReglasCacheAlertas
import com.example.myapplication.domain.model.Alerta
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Caché de alertas públicas (FE-3.6; apoyo de C1 —una alerta creada en el backend llega en la siguiente sincronización
 * y al borrarla desaparece— y de C2 —tras una sincronización la caché sigue en disco sin red—). `GET /v1/alerts` según
 * backend §5.3 contra MockWebServer; el almacén en memoria o en una carpeta temporal.
 */
class CacheAlertasPublicasTest {

    @get:Rule
    val carpeta = TemporaryFolder()

    private lateinit var servidor: MockWebServer
    private val registros = CopyOnWriteArrayList<String>()
    private var reloj = 1_000_000L
    private val almacen = AlmacenCacheAlertasMemoria()

    private val idA = "1d6e0000-0000-4000-8000-00000000000a"
    private val idB = "1d6e0000-0000-4000-8000-00000000000b"
    private val idC = "1d6e0000-0000-4000-8000-00000000000c"

    @Before
    fun preparar() {
        servidor = MockWebServer()
        servidor.start()
    }

    @After
    fun cerrar() {
        servidor.shutdown()
    }

    private fun cache(a: com.example.myapplication.data.local.AlmacenCacheAlertas = almacen) = CacheAlertasPublicas(
        almacen = a,
        api = ClienteApi.crear(urlBase = servidor.url("/v1").toString(), registrar = {}),
        reloj = { reloj },
        registrar = { registros += it },
    )

    private fun alertaJson(id: String, mensaje: String, activa: Boolean = true, version: Int = 1) =
        """{"id": "$id", "lat": 6.2011, "lng": -75.579, "mensaje": "$mensaje", "tipo": "agua", "prioridad": "alta",
            "radio_m": 20, "activa": $activa, "vigencia_desde": null, "vigencia_hasta": "2026-10-29T19:15:59Z",
            "actualizado_en": "2026-10-22T20:11:00Z", "version": $version}"""

    private fun respuesta(generado: String, completo: Boolean, alertas: List<String>, eliminadas: List<String> = emptyList()) =
        MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(
            """{"generado_en": "$generado", "completo": $completo, "alertas": [${alertas.joinToString(",")}],
                "eliminadas": [${eliminadas.joinToString(",") { "\"$it\"" }}]}""",
        )

    @Test
    fun primeraVezCompleta_despuesDiferenciasConDesdeTalCual() = runBlocking {
        val c = cache()
        servidor.enqueue(respuesta("2026-10-28T15:00:00Z", true, listOf(alertaJson(idA, "lago"), alertaJson(idB, "bancas"))))
        val r1 = c.sincronizar("arranque")!!
        assertEquals("/v1/alerts", servidor.takeRequest().path)
        assertTrue(r1.completa)
        assertEquals(listOf(idA, idB), c.estado.value.alertas.map { it.id })
        assertEquals("2026-10-28T15:00:00Z", almacen.guardada.generadoEn)
        assertEquals(20, c.estado.value.alertas.first().radio)
        assertNotNull(c.estado.value.alertas.first().vigenciaHastaMs)

        // Diferencias: A cambia, B llega inactiva (sale), C nueva y un id borrado que la caché no tenía.
        reloj += CacheAlertasPublicas.INTERVALO_MS
        servidor.enqueue(
            respuesta(
                "2026-10-28T15:06:00Z", false,
                listOf(alertaJson(idA, "lago grande", version = 2), alertaJson(idB, "bancas", activa = false), alertaJson(idC, "obra")),
                eliminadas = listOf("9c2b0000-0000-4000-8000-000000000000"),
            ),
        )
        val r2 = c.sincronizar("cada 5 min")!!
        val pedido = servidor.takeRequest()
        // Retrofit codifica «:» como %3A en la query; el valor que recibe el backend es el `generado_en` tal cual.
        assertEquals("/v1/alerts", pedido.requestUrl!!.encodedPath)
        assertEquals("2026-10-28T15:00:00Z", pedido.requestUrl!!.queryParameter("desde"))
        assertNull(pedido.getHeader("Authorization"))
        assertEquals(listOf(idA, idC), c.estado.value.alertas.map { it.id })
        assertEquals("lago grande", c.estado.value.alertas.first().mensaje)
        assertEquals("2026-10-28T15:00:00Z", r2.desde)
        assertEquals(
            "Alertas públicas sincronizadas (cada 5 min): diferencias desde 2026-10-28T15:00:00Z, 3 recibidas, " +
                "1 eliminadas, 2 en caché (generado_en 2026-10-28T15:06:00Z)",
            registros.last(),
        )
    }

    @Test
    fun borradaEnElBackend_desapareceEnLaSiguiente() = runBlocking {
        val c = cache()
        servidor.enqueue(respuesta("2026-10-28T15:00:00Z", true, listOf(alertaJson(idA, "validacion-3-6-c1"))))
        c.sincronizar("arranque")
        reloj += CacheAlertasPublicas.INTERVALO_MS
        servidor.enqueue(respuesta("2026-10-28T15:01:00Z", false, emptyList(), eliminadas = listOf(idA)))
        c.sincronizar("primer plano")
        assertTrue(c.estado.value.alertas.isEmpty())
        assertTrue(almacen.guardada.alertas.isEmpty())
        assertEquals("2026-10-28T15:01:00Z", almacen.guardada.generadoEn)
    }

    @Test
    fun comoMuchoUnaCada5Min_salvoForzar() = runBlocking {
        val c = cache()
        assertTrue(c.haceFalta())
        servidor.enqueue(respuesta("2026-10-28T15:00:00Z", true, emptyList()))
        assertNotNull(c.sincronizar("arranque"))
        reloj += CacheAlertasPublicas.INTERVALO_MS - 1
        assertNull(c.sincronizar("conexión"))
        assertEquals(1, servidor.requestCount)
        servidor.enqueue(respuesta("2026-10-28T15:04:00Z", false, emptyList()))
        assertNotNull(c.sincronizar("cada 5 min", forzar = true))
        assertEquals(2, servidor.requestCount)
    }

    @Test
    fun sinRed_lanzaYLaCacheQuedaComoEstaba_yVuelveAIntentar() = runBlocking {
        almacen.guardada = CachePublica(listOf(Alerta(idA, 6.2, -75.5, "lago")), "2026-10-28T15:00:00Z", cargada = true)
        val c = cache()
        servidor.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        assertThrows(IOException::class.java) { runBlocking { c.sincronizar("arranque") } }
        assertEquals(listOf(idA), c.estado.value.alertas.map { it.id })
        assertEquals(0, almacen.escrituras)
        // Un fallo no cuenta como sincronización correcta: «al volver la conexión» pide en el acto.
        assertTrue(c.haceFalta())
        servidor.enqueue(respuesta("2026-10-28T15:02:00Z", false, emptyList()))
        assertNotNull(c.sincronizar("conexión"))
    }

    @Test
    fun respuestaSinCampos_esInesperada_y422ConDesdePideLaFotoCompleta() = runBlocking {
        val c = cache()
        servidor.enqueue(MockResponse().setResponseCode(200).setBody("""{"completo": true, "alertas": []}"""))
        assertThrows(RespuestaInesperadaException::class.java) { runBlocking { c.sincronizar("arranque") } }

        almacen.guardada = CachePublica(emptyList(), "fecha-rara", cargada = true)
        val c2 = cache()
        servidor.enqueue(
            MockResponse().setResponseCode(422).setBody(
                """{"error": {"codigo": "VALIDACION", "mensaje": "desde", "detalle": {"campos": [{"campo": "desde", "motivo": "x"}]}}}""",
            ),
        )
        servidor.enqueue(respuesta("2026-10-28T15:00:00Z", true, listOf(alertaJson(idA, "lago"))))
        servidor.takeRequest() // la del primer caso
        val r = c2.sincronizar("arranque")!!
        assertEquals("fecha-rara", servidor.takeRequest().requestUrl!!.queryParameter("desde"))
        assertEquals("/v1/alerts", servidor.takeRequest().path)
        assertTrue(r.completa)
        assertEquals(listOf(idA), c2.estado.value.alertas.map { it.id })
    }

    @Test
    fun archivo_sobreviveAUnProcesoNuevo_yUnoDanadoSeAparta() = runBlocking {
        val archivo = File(carpeta.root, "alertas/publicas.json")
        val enDisco = AlmacenCacheAlertasArchivo(archivo)
        servidor.enqueue(respuesta("2026-10-28T15:00:00Z", true, listOf(alertaJson(idA, "Ten cuidado, «lago»"))))
        cache(enDisco).sincronizar("arranque")
        // Otro proceso (sin red): lee lo mismo del disco.
        val otra = cache(AlmacenCacheAlertasArchivo(archivo)).cargar()
        assertEquals(listOf("Ten cuidado, «lago»"), otra.alertas.map { it.mensaje })
        assertEquals("2026-10-28T15:00:00Z", otra.generadoEn)
        assertEquals(20, otra.alertas.single().radio)

        archivo.writeText("{roto")
        val avisos = mutableListOf<String>()
        val vacia = AlmacenCacheAlertasArchivo(archivo, registrar = { avisos += it }).leer()
        assertTrue(vacia.alertas.isEmpty())
        assertNull(vacia.generadoEn)
        assertTrue(File(carpeta.root, "alertas/publicas.json.danado").exists())
        assertEquals(1, avisos.size)
    }

    @Test
    fun reglas_completoSoloActivas_yDiferenciaRepetidaNoCambiaNada() {
        val a = Alerta(idA, 6.2, -75.5, "a")
        val b = Alerta(idB, 6.2, -75.5, "b", activa = false)
        assertEquals(listOf(a), ReglasCacheAlertas.aplicar(listOf(Alerta(idC, 0.0, 0.0, "c")), true, listOf(a, b, a), emptyList()))
        val una = ReglasCacheAlertas.aplicar(listOf(a), false, listOf(a.copy(mensaje = "a2")), listOf(idC))
        assertEquals(una, ReglasCacheAlertas.aplicar(una, false, listOf(a.copy(mensaje = "a2")), listOf(idC)))
        assertEquals("a2", una.single().mensaje)
    }
}
