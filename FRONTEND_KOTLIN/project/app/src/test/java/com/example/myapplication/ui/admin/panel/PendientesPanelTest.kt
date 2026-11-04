package com.example.myapplication.ui.admin.panel

import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.ManifestPrueba
import com.example.myapplication.data.local.fotosPendientesDe
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.MapeoErroresApi
import com.example.myapplication.data.remote.RespuestaInesperadaException
import com.example.myapplication.data.remote.SinConexionException
import com.example.myapplication.domain.model.ResumenAdmin
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * «Fotos pendientes» del Panel (FE-2.2; apoyo de C2: el dato coincide con la cola local de subida). El Panel lo recalcula
 * al volver a la pantalla y con cada cambio de la cola (`resumenConPendientes`) con la misma regla que
 * `AlmacenRecorridos.contarFotosPendientes()` (la que usa `RemoteAdminRepository` al cargar), sobre recorridos reales
 * en una carpeta temporal (formato de `files/recoleccion/`, ARCHITECTURE §5.6 y §5.10).
 */
class PendientesPanelTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private val resumen = ResumenAdmin(2842, 48, 3, 12, 1_792_767_845_000L, fotosPendientes = 0)

    private fun cola(): AlmacenRecorridos {
        val raiz = tmp.newFolder("recoleccion")
        ManifestPrueba.crear(raiz, id = "rec_0001", fotos = 3, subidas = setOf(1)) // 2 pendientes
        ManifestPrueba.crear(raiz, id = "rec_0002", fotos = 4, nombre = "validacion-2-2") // «Guardar y subir después»: 4
        ManifestPrueba.crear(raiz, id = "rec_0003", fotos = 5, estado = "en_curso") // grabación sin terminar: no cuenta
        ManifestPrueba.crear(raiz, id = "rec_0004", fotos = 2, subidas = setOf(1, 2)) // subido entero: 0
        File(raiz, "rec_0005").mkdirs()
        File(raiz, "rec_0005/manifest.json").writeText("{roto") // ilegible: se salta
        return AlmacenRecorridos(raiz)
    }

    @Test
    fun laReglaDelPanel_esLaDeLaCola_soloFinalizadosSinSubir() = runBlocking {
        val almacen = cola()
        val recorridos = almacen.listar()

        assertEquals(6, fotosPendientesDe(recorridos))
        assertEquals(almacen.contarFotosPendientes(), fotosPendientesDe(recorridos))
    }

    @Test
    fun resumenConPendientes_soloCambiaFotosPendientes() = runBlocking {
        val recorridos = cola().listar()

        val nuevo = resumenConPendientes(resumen, recorridos)

        assertEquals(resumen.copy(fotosPendientes = 6), nuevo)
    }

    @Test
    fun resumenConPendientes_sinResumenOSinRecorridos_noInventaNada() {
        assertNull(resumenConPendientes(null, emptyList()))
        assertSame(resumen, resumenConPendientes(resumen, null)) // no se pudieron leer: se queda el dato anterior
        assertEquals(0, resumenConPendientes(resumen.copy(fotosPendientes = 9), emptyList())?.fotosPendientes)
    }

    @Test
    fun unaSubidaQueAvanza_bajaLasPendientes() = runBlocking {
        val almacen = cola()
        assertEquals(6, resumenConPendientes(resumen, almacen.listar())?.fotosPendientes)

        almacen.marcarSubidas("rec_0002", listOf("0001", "0002", "0003"))

        assertEquals(3, resumenConPendientes(resumen, almacen.listar())?.fotosPendientes)
        assertEquals(3, almacen.contarFotosPendientes())
    }

    @Test
    fun errorVisible_salvoSesionPerdida() {
        assertFalse(
            errorVisibleDelResumen(ApiException(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), 401, null)),
        )
        assertFalse(errorVisibleDelResumen(ApiException(FalloApi.SesionVencida("TOKEN_EXPIRADO"), 401, "rid")))
        assertTrue(errorVisibleDelResumen(SinConexionException()))
        assertTrue(errorVisibleDelResumen(ApiException(FalloApi.Desconocido(500, "ERROR_INTERNO"), 500, "rid")))
        assertTrue(errorVisibleDelResumen(RespuestaInesperadaException("falta total_fotos")))
    }
}
