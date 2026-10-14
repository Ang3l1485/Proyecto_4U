package com.example.myapplication.hu02

import com.example.myapplication.ui.inicio.BackendHealthStub
import com.example.myapplication.ui.ubicacion.EscaneoBackendStub
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * HU-02: servicios que hoy están SIMULADOS (el backend real aún no existe).
 *
 * Estos tests no validan el backend: documentan cómo se comportan los stubs de los que depende
 * el resto de la HU, para que un cambio de contrato se note.
 */
class ServiciosSimuladosTest {

    @Test
    fun el_stub_del_backend_de_inicio_siempre_responde_en_linea() {
        assertEquals(true, runBlocking { BackendHealthStub.estaEnLinea() })
    }

    @Test
    fun el_stub_de_ubicacion_acepta_las_cinco_fotos_y_tarda_los_2_5_segundos_simulados() {
        val fotos = (1..5).map { File("escaneo_$it.jpg") } // no se leen: el stub solo espera
        val inicio = System.nanoTime()
        runBlocking { EscaneoBackendStub.analizar(fotos) }
        val ms = (System.nanoTime() - inicio) / 1_000_000
        // `delay(2500)` nunca termina antes de tiempo; el margen cubre el redondeo del reloj.
        assertTrue("Tardó solo $ms ms", ms >= 2_400)
    }

    @Test
    fun el_stub_de_ubicacion_no_falla_con_una_lista_vacia() {
        // Hoy no valida nada; si el backend real lo hace, este test debe cambiar a "lanza error".
        runBlocking { EscaneoBackendStub.analizar(emptyList()) }
    }
}
