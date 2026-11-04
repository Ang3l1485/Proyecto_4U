package com.example.myapplication.hu02

import com.example.myapplication.ui.inicio.Comando
import com.example.myapplication.ui.inicio.ComandoParser
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * HU-02 / Inicio (vista 6.1): interpreta el comando hablado.
 * "uno" = ubicarme (escaneo 360°), "dos" = ir a un lugar, más sus sinónimos.
 * Lógica pura (`ComandoParser` no usa Android): corre en JVM.
 */
class ComandoParserTest {

    private fun c(texto: String) = ComandoParser.parse(texto)

    // ------------------------------------------------------------------ camino feliz

    @Test
    fun uno_y_1_significan_ubicarme() {
        assertEquals(Comando.UBICARME, c("uno"))
        assertEquals(Comando.UBICARME, c("1"))
        assertEquals(Comando.UBICARME, c("UNO"))
    }

    @Test
    fun dos_y_2_significan_ir_a_un_lugar() {
        assertEquals(Comando.IR_A_LUGAR, c("dos"))
        assertEquals(Comando.IR_A_LUGAR, c("2"))
        assertEquals(Comando.IR_A_LUGAR, c("DOS"))
    }

    @Test
    fun reconoce_sinonimos_de_ubicarme() {
        assertEquals(Comando.UBICARME, c("ubícame"))
        assertEquals(Comando.UBICARME, c("¿dónde estoy"))
        assertEquals(Comando.UBICARME, c("quiero saber donde estamos"))
    }

    @Test
    fun reconoce_sinonimos_de_ir_a_un_lugar() {
        assertEquals(Comando.IR_A_LUGAR, c("quiero ir a un lugar"))
        assertEquals(Comando.IR_A_LUGAR, c("cambiar destino"))
        assertEquals(Comando.IR_A_LUGAR, c("quiero llegar"))
    }

    // ------------------------------------------------------------------ alternos

    @Test
    fun un_comando_ambiguo_no_se_interpreta() {
        assertEquals(Comando.NINGUNO, c("uno y dos"))
        assertEquals(Comando.NINGUNO, c("ubicarme en un lugar"))
    }

    @Test
    fun una_frase_sin_relacion_o_vacia_no_se_interpreta() {
        assertEquals(Comando.NINGUNO, c("hola"))
        assertEquals(Comando.NINGUNO, c(""))
    }

    @Test
    fun uno_y_dos_deben_ser_palabras_completas() {
        assertEquals(Comando.NINGUNO, c("tunos"))
        assertEquals(Comando.NINGUNO, c("dosis"))
    }
}
