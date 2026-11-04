package com.example.myapplication.ui.inicio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EsperaEscuchaTest {
    @Test
    fun reintenta_hasta_completar_la_espera_minima() {
        assertTrue(EsperaEscucha.debeReintentar(FinSinTexto.SIN_COINCIDENCIA, 6_999L, 23))
        assertFalse(EsperaEscucha.debeReintentar(FinSinTexto.SIN_COINCIDENCIA, 7_000L, 23))
    }

    @Test
    fun no_reintenta_mas_alla_del_tope() {
        assertFalse(EsperaEscucha.debeReintentar(FinSinTexto.SIN_COINCIDENCIA, 1_000L, 24))
    }
}
