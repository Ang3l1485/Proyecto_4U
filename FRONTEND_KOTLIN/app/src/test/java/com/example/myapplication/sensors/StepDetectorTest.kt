package com.example.myapplication.sensors

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StepDetectorTest {
    @Test fun picoPorEncimaDelUmbral_cuentaUnPaso() {
        val detector = StepDetector()
        detector.procesar(0f, 0f, StepDetector.GRAVEDAD, 0L)
        assertTrue(detector.procesar(0f, 0f, StepDetector.GRAVEDAD + 10f, 1_000L))
    }

    @Test fun noVuelveAContarMientrasSigueSobreUmbral() {
        val detector = StepDetector()
        detector.procesar(0f, 0f, StepDetector.GRAVEDAD, 0L)
        assertTrue(detector.procesar(0f, 0f, StepDetector.GRAVEDAD + 10f, 1_000L))
        assertFalse(detector.procesar(0f, 0f, StepDetector.GRAVEDAD + 10f, 1_400L))
    }

    @Test fun detectarFalse_actualizaSinContarPaso() {
        val detector = StepDetector()
        val conto = detector.procesar(
            0f, 0f, StepDetector.GRAVEDAD + 10f, 1_000L, detectar = false
        )
        assertFalse(conto)
        assertTrue(detector.ultimaDesviacion > 0f)
    }

    @Test fun reiniciar_restableceEstadoDelDetector() {
        val detector = StepDetector()
        detector.procesar(0f, 0f, StepDetector.GRAVEDAD, 0L)
        assertTrue(detector.procesar(0f, 0f, StepDetector.GRAVEDAD + 10f, 1_000L))
        detector.reiniciar()
        assertEqualsZero(detector.ultimaDesviacion)
        detector.procesar(0f, 0f, StepDetector.GRAVEDAD, 2_000L)
        assertTrue(detector.procesar(0f, 0f, StepDetector.GRAVEDAD + 10f, 3_000L))
    }

    private fun assertEqualsZero(value: Float) {
        org.junit.Assert.assertEquals(0f, value, 0f)
    }
}
