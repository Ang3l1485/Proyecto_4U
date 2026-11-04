package com.example.myapplication.domain.usecase

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CalibracionPasoTest {
    @Test fun distanciaMenorAlMinimo_rechazaTramoCorto() {
        assertEquals(
            ResultadoCalibracion.Invalido(MotivoInvalido.TRAMO_CORTO),
            CalibracionPaso.calcular(9.99, 20, 20.0)
        )
    }

    @Test fun pasosMenoresAlMinimo_rechazaPocosPasos() {
        assertEquals(
            ResultadoCalibracion.Invalido(MotivoInvalido.POCOS_PASOS),
            CalibracionPaso.calcular(10.0, 14, 20.0)
        )
    }

    @Test fun medicionDentroDeRango_devuelveLongitudCalculada() {
        val resultado = CalibracionPaso.calcular(10.0, 20, 10.0)
        assertTrue(resultado is ResultadoCalibracion.Valido)
        resultado as ResultadoCalibracion.Valido
        assertEquals(0.5, resultado.longitudPasoM, 1e-9)
        assertEquals(20, resultado.pasos)
        assertEquals(120.0, resultado.cadenciaPpm, 1e-9)
        assertEquals(1.0, resultado.velocidadMps, 1e-9)
    }

    @Test fun longitudIgualAlMinimo_seAcepta() {
        val resultado = CalibracionPaso.calcular(10.0, 25, 30.0)
        assertTrue(resultado is ResultadoCalibracion.Valido)
        assertEquals(0.4, (resultado as ResultadoCalibracion.Valido).longitudPasoM, 1e-9)
    }

    @Test fun longitudMayorAlMaximo_rechazaPasoMuyLargo() {
        val resultado = CalibracionPaso.calcular(18.1, 15, 20.0)
        assertEquals(MotivoInvalido.PASO_MUY_LARGO, (resultado as ResultadoCalibracion.Invalido).motivo)
        assertEquals(18.1 / 15.0, resultado.longitudPasoM!!, 1e-9)
    }

    @Test fun duracionCero_noDividePorCeroEnMetricasInformativas() {
        val resultado = CalibracionPaso.calcular(10.0, 20, 0.0)
        assertTrue(resultado is ResultadoCalibracion.Valido)
        resultado as ResultadoCalibracion.Valido
        assertEquals(0.0, resultado.cadenciaPpm, 1e-9)
        assertEquals(0.0, resultado.velocidadMps, 1e-9)
    }
}
