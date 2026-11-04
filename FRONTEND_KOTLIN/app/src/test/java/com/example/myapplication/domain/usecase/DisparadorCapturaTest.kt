package com.example.myapplication.domain.usecase

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DisparadorCapturaTest {
    @Test fun primeraCaptura_seSolicitaInmediatamente() {
        assertTrue(DisparadorCaptura().debeCapturar(0.0, 0L))
    }

    @Test fun modoPorDistancia_esperaHastaAlcanzarIntervalo() {
        val disparador = DisparadorCaptura(ModoCaptura.PorDistancia(5.0))
        disparador.alCapturar(0.0, 0L)
        assertFalse(disparador.debeCapturar(4.99, 1_000L))
        assertTrue(disparador.debeCapturar(5.0, 1_000L))
    }

    @Test fun modoPorTiempo_esperaHastaAlcanzarIntervalo() {
        val disparador = DisparadorCaptura(ModoCaptura.PorTiempo(3))
        disparador.alCapturar(0.0, 1_000L)
        assertFalse(disparador.debeCapturar(100.0, 3_999L))
        assertTrue(disparador.debeCapturar(100.0, 4_000L))
    }

    @Test fun reiniciar_permiteCapturaInicialOtraVez() {
        val disparador = DisparadorCaptura()
        disparador.alCapturar(5.0, 1_000L)
        disparador.reiniciar()
        assertTrue(disparador.debeCapturar(5.0, 1_000L))
    }
}
