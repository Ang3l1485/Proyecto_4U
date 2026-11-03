package com.example.myapplication.data.local

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

/**
 * FE-2.1, criterio C2 (ARCHITECTURE §5.10, «Subida y sesión»): la cola retoma lo que quedó `subiendo`, espera la
 * sesión sin reintentar en bucle, reintenta lo transitorio con espera y no repite en la misma pasada un fallo
 * permanente. El ejecutor es un doble que responde lo que dice el guion de cada recorrido.
 */
class ColaSubidaTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val raiz: File by lazy { tmp.newFolder("recoleccion") }
    private val almacen by lazy { AlmacenRecorridos(raiz) }
    private val alcance = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** Responde por recorrido lo que diga [guion] (en orden; el último se repite) y marca `completada` si toca. */
    private inner class EjecutorGuion(val guion: Map<String, List<ResultadoSubida>>) : EjecutorSubida {
        val llamadas = CopyOnWriteArrayList<String>()
        override suspend fun ejecutar(videoId: String, alProgreso: (ProgresoSubida) -> Unit): ResultadoSubida {
            llamadas += videoId
            alProgreso(ProgresoSubida(FaseSubida.SUBIENDO, 1, 2))
            val lista = guion.getValue(videoId)
            val r = lista[minOf(llamadas.count { it == videoId } - 1, lista.lastIndex)]
            when (r) {
                is ResultadoSubida.Completada -> almacen.cambiarEstadoSubida(videoId, EstadoSubida.COMPLETADA)
                is ResultadoSubida.FotosIlegibles -> almacen.cambiarEstadoSubida(videoId, EstadoSubida.SIN_SUBIR)
                else -> almacen.cambiarEstadoSubida(videoId, EstadoSubida.SUBIENDO)
            }
            return r
        }
    }

    private fun cola(ejecutor: EjecutorSubida, sesion: Boolean = true, registro: MutableList<String> = mutableListOf()) =
        ColaSubida(almacen, ejecutor, haySesion = { sesion }, alcance = alcance, registrar = { registro += it }, esperasMs = listOf(1, 1, 1))

    @After
    fun cerrar() {
        alcance.cancel()
    }

    private val completada = ResultadoSubida.Completada(ConteoRemoto(0, 3, 0, 0))

    @Test
    fun reanudar_retomaSoloLosFinalizadosSubiendo() = runBlocking {
        ManifestPrueba.crear(raiz, id = "rec_0001", extra = mapOf("subida_estado" to "\"subiendo\""))
        ManifestPrueba.crear(raiz, id = "rec_0002") // sin_subir: «Guardar y subir después»
        ManifestPrueba.crear(raiz, id = "rec_0003", extra = mapOf("subida_estado" to "\"subiendo\""))
        ManifestPrueba.crear(raiz, id = "rec_0004", estado = "en_curso", extra = mapOf("subida_estado" to "\"subiendo\""))
        val ejecutor = EjecutorGuion(mapOf("rec_0001" to listOf(completada), "rec_0003" to listOf(completada)))
        val c = cola(ejecutor)
        c.procesar()
        assertEquals(listOf("rec_0001", "rec_0003"), ejecutor.llamadas)
        assertEquals(FaseCola.COMPLETADA, c.estado.value.fase)
        assertEquals("rec_0003", c.estado.value.videoId)
    }

    @Test
    fun sinSesion_noLlamaAlEjecutorYEsperaSesion() = runBlocking {
        ManifestPrueba.crear(raiz, extra = mapOf("subida_estado" to "\"subiendo\""))
        val ejecutor = EjecutorGuion(mapOf("rec_0001" to listOf(completada)))
        val c = cola(ejecutor, sesion = false)
        c.procesar()
        assertTrue(ejecutor.llamadas.isEmpty())
        assertEquals(FaseCola.ESPERANDO_SESION, c.estado.value.fase)
        assertEquals(EstadoSubida.SUBIENDO, almacen.leer("rec_0001").subida)
    }

    @Test
    fun sesionPerdidaAMitad_paraSinReintentar() = runBlocking {
        ManifestPrueba.crear(raiz, id = "rec_0001", extra = mapOf("subida_estado" to "\"subiendo\""))
        ManifestPrueba.crear(raiz, id = "rec_0002", extra = mapOf("subida_estado" to "\"subiendo\""))
        val ejecutor = EjecutorGuion(
            mapOf("rec_0001" to listOf(ResultadoSubida.EsperandoSesion("TOKEN_EXPIRADO")), "rec_0002" to listOf(completada)),
        )
        val c = cola(ejecutor)
        c.procesar()
        assertEquals(listOf("rec_0001"), ejecutor.llamadas) // ni rec_0002 ni otro intento
        assertEquals(FaseCola.ESPERANDO_SESION, c.estado.value.fase)
    }

    @Test
    fun transitorio_reintentaConEsperaHastaCompletar() = runBlocking {
        ManifestPrueba.crear(raiz, extra = mapOf("subida_estado" to "\"subiendo\""))
        val registro = mutableListOf<String>()
        val ejecutor = EjecutorGuion(
            mapOf(
                "rec_0001" to listOf(
                    ResultadoSubida.SinConexion("SinConexionException"),
                    ResultadoSubida.Pendiente(ConteoRemoto(1, 2, 0, 0)),
                    completada,
                ),
            ),
        )
        val c = cola(ejecutor, registro = registro)
        c.procesar()
        assertEquals(3, ejecutor.llamadas.size)
        assertEquals(FaseCola.COMPLETADA, c.estado.value.fase)
        assertEquals(2, registro.count { it.startsWith("cola: reintento") })
    }

    @Test
    fun fallaPermanente_noSeRepiteEnLaPasada_yOtroReanudarLoIntentaUnaVezMas() = runBlocking {
        ManifestPrueba.crear(raiz, extra = mapOf("subida_estado" to "\"subiendo\""))
        val ejecutor = EjecutorGuion(mapOf("rec_0001" to listOf(ResultadoSubida.Fallida("409 VIDEO_ELIMINADO"))))
        val c = cola(ejecutor)
        c.procesar()
        assertEquals(1, ejecutor.llamadas.size)
        assertEquals(FaseCola.ERROR, c.estado.value.fase)
        assertEquals("409 VIDEO_ELIMINADO", c.estado.value.mensaje)
        c.procesar() // otra apertura del Panel o de 7.5
        assertEquals(2, ejecutor.llamadas.size)
    }

    @Test
    fun subir_unRecorridoSinSubir_loProcesaEnSegundoPlano() = runBlocking {
        ManifestPrueba.crear(raiz) // sin_subir
        val ejecutor = EjecutorGuion(mapOf("rec_0001" to listOf(completada)))
        val c = cola(ejecutor)
        c.subir("rec_0001")
        withTimeout(5_000) { c.estado.first { it.fase == FaseCola.COMPLETADA } }
        assertEquals(listOf("rec_0001"), ejecutor.llamadas)
        assertEquals(EstadoSubida.COMPLETADA, almacen.leer("rec_0001").subida)
    }

    @Test
    fun fotosIlegibles_avisaConLosIdsYNoReintenta() = runBlocking {
        ManifestPrueba.crear(raiz)
        val ejecutor = EjecutorGuion(mapOf("rec_0001" to listOf(ResultadoSubida.FotosIlegibles(listOf("0002")))))
        val c = cola(ejecutor)
        c.subir("rec_0001")
        val estado = withTimeout(5_000) { c.estado.first { it.fase == FaseCola.FOTOS_ILEGIBLES } }
        assertEquals(listOf("0002"), estado.fotosIlegibles)
        assertEquals(1, ejecutor.llamadas.size)
    }

    @Test
    fun cambios_subeConElProgresoYConCadaRecorrido() = runBlocking {
        ManifestPrueba.crear(raiz, extra = mapOf("subida_estado" to "\"subiendo\""))
        val c = cola(EjecutorGuion(mapOf("rec_0001" to listOf(completada))))
        c.procesar()
        assertTrue(c.cambios.value >= 2) // progreso + fin del intento
        assertEquals(1, c.cambiosVideos.value)
    }
}
