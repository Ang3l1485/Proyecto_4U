package com.example.myapplication.sensors

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PdrEngineTest {
    @Test fun pasoSinPosicionInicial_noAvanza() {
        val engine = PdrEngine()
        assertFalse(engine.onPaso(1_000L))
        assertEquals(0, engine.pasos)
    }

    @Test fun pasoConRumboNorte_incrementaLatitudAproximadamente() {
        val engine = PdrEngine(longitudPasoM = 1.0)
        engine.fijarPosicion(6.2, -75.57)
        engine.fijarRumboManual(0f)
        assertTrue(engine.onPaso(1_000L))
        assertEquals(1, engine.pasos)
        assertTrue(engine.lat!! > 6.2)
        assertEquals(-75.57, engine.lng!!, 1e-7)
    }

    @Test fun rumboEste_incrementaLongitudAproximadamente() {
        val engine = PdrEngine(longitudPasoM = 1.0)
        engine.fijarPosicion(6.2, -75.57)
        engine.fijarRumboManual(90f)
        assertTrue(engine.onPaso(1_000L))
        assertEquals(6.2, engine.lat!!, 1e-7)
        assertTrue(engine.lng!! > -75.57)
    }

    @Test fun promedioCircularDe359Y1Grados_quedaCercaDelNorte() {
        val engine = PdrEngine(ventanaRumbo = 2)
        engine.onRumboSensor(359f)
        engine.onRumboSensor(1f)
        assertTrue(engine.rumbo < 0.1f || engine.rumbo > 359.9f)
    }

    @Test fun reiniciar_restablecePasosYPosicionInicial() {
        val engine = PdrEngine(longitudPasoM = 1.0)
        engine.fijarPosicion(6.2, -75.57)
        engine.fijarRumboManual(0f)
        engine.onPaso(1_000L)
        engine.onPaso(2_000L)
        engine.reiniciar()
        assertEquals(0, engine.pasos)
        assertEquals(6.2, engine.lat!!, 1e-9)
        assertEquals(-75.57, engine.lng!!, 1e-9)
        assertEquals(0.0, engine.velocidadMps, 1e-9)
    }
}
