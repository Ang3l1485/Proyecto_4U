package com.example.myapplication.hu02

import com.example.myapplication.data.repository.LUGARES_DE_PRUEBA
import com.example.myapplication.ui.destino.DestinoEvento
import com.example.myapplication.ui.destino.DestinoUiState
import com.example.myapplication.ui.destino.ErrorDestino
import com.example.myapplication.ui.destino.OrdenLugares
import com.example.myapplication.ui.destino.SeleccionDestinoViewModel
import com.example.myapplication.ui.inicio.Comando
import com.example.myapplication.ui.inicio.ComandoParser
import com.example.myapplication.ui.inicio.InicioViewModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HU-02 / Selección de destino e Inicio: estado inicial y textos hablados.
 *
 * Los textos `BIENVENIDA` y `PREGUNTA` son `const val`: el compilador los copia al test, así que
 * se pueden leer en JVM sin crear los ViewModels (que necesitan Android).
 */
class DestinoEstadoYTextosTest {

    // ------------------------------------------------------------------ estado de Selección de destino

    @Test
    fun la_vista_arranca_cargando_sin_error_ni_filtros() {
        val s = DestinoUiState()
        assertTrue(s.cargando)
        assertNull(s.error)
        assertEquals(false, s.sinMicrofono)
        assertEquals(false, s.escuchando)
        assertNull(s.textoReconocido)
        assertNull(s.candidato)
        assertTrue(s.opciones.isEmpty())
        assertEquals("", s.busqueda)
        assertNull(s.categoria)
        assertEquals(OrdenLugares.CERCANIA, s.orden)
        assertTrue(s.lugares.isEmpty())
    }

    @Test
    fun el_orden_por_defecto_es_por_cercania_y_las_etiquetas_son_las_documentadas() {
        assertEquals("Ordenado por cercanía", OrdenLugares.CERCANIA.etiqueta)
        assertEquals("Ordenado por nombre", OrdenLugares.NOMBRE.etiqueta)
    }

    @Test
    fun los_errores_de_carga_son_sin_conexion_y_desconocido() {
        assertEquals(
            listOf(ErrorDestino.SIN_CONEXION, ErrorDestino.DESCONOCIDO),
            ErrorDestino.values().toList(),
        )
    }

    @Test
    fun el_evento_confirmado_lleva_el_lugar_elegido() {
        val lugar = LUGARES_DE_PRUEBA.first()
        assertEquals(lugar, (DestinoEvento.Confirmado(lugar)).lugar)
        assertEquals(DestinoEvento.Confirmado(lugar), DestinoEvento.Confirmado(lugar))
    }

    // ------------------------------------------------------------------ textos hablados

    @Test
    fun la_bienvenida_de_inicio_ensena_los_dos_comandos() {
        val b = InicioViewModel.BIENVENIDA
        assertEquals("Di uno para saber dónde estás, o dos para ir a un lugar.", b)
        assertTrue("uno" in b && "dos" in b)
    }

    @Test
    fun los_comandos_que_la_bienvenida_pide_decir_son_los_que_el_parser_entiende() {
        assertEquals(Comando.UBICARME, ComandoParser.parse("uno"))
        assertEquals(Comando.IR_A_LUGAR, ComandoParser.parse("dos"))
    }

    @Test
    fun la_pregunta_de_destino_es_la_documentada() {
        assertEquals("¿A dónde quieres ir? Di el nombre del lugar.", SeleccionDestinoViewModel.PREGUNTA)
    }
}
