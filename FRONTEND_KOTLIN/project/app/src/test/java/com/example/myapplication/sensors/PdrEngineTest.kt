package com.example.myapplication.sensors

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** `PdrEngine`: posición por pasos y rumbo, promedio circular del rumbo y velocidad. Lógica pura. */
class PdrEngineTest {

    private val delta = 1e-9

    @Test
    fun conPosicionYRumboNorte_onPaso_avanzaUnaLongitudDePasoAlNorte() {
        val motor = PdrEngine(longitudPasoM = 0.72)
        motor.fijarPosicion(6.2, -75.578)
        motor.fijarRumboManual(0f)

        val avanzo = motor.onPaso(1_000)

        assertTrue(avanzo)
        assertEquals(1, motor.pasos)
        assertEquals(0.72, motor.distanciaMetros, delta)
        assertEquals(6.2 + 0.72 / 111_320.0, motor.lat!!, delta)
        assertEquals(-75.578, motor.lng!!, delta)
    }

    @Test
    fun conRumboEste_onPaso_avanzaEnLongitudSinCambiarLatitud() {
        val motor = PdrEngine()
        motor.fijarPosicion(6.2, -75.578)
        motor.fijarRumboManual(90f)

        motor.onPaso(1_000)

        assertEquals(6.2, motor.lat!!, delta)
        assertTrue(motor.lng!! > -75.578)
    }

    @Test
    fun sinPosicionInicial_onPaso_devuelveFalseYNoCuenta() {
        val motor = PdrEngine()

        val avanzo = motor.onPaso(1_000)

        assertFalse(avanzo)
        assertEquals(0, motor.pasos)
        assertNull(motor.lat)
        assertNull(motor.lng)
    }

    @Test
    fun lecturasA350y10Grados_onRumboSensor_promedianCercaDe0YNoDe180() {
        val motor = PdrEngine()

        motor.onRumboSensor(350f)
        motor.onRumboSensor(10f)

        val distanciaANorte = minOf(motor.rumbo, 360f - motor.rumbo)
        assertTrue("rumbo=${motor.rumbo}", distanciaANorte < 0.01f)
    }

    @Test
    fun lecturaNaN_onRumboSensorYFijarRumboManual_seIgnoran() {
        val motor = PdrEngine()
        motor.fijarRumboManual(45f)

        motor.onRumboSensor(Float.NaN)
        motor.fijarRumboManual(Float.NaN)

        assertEquals(45f, motor.rumbo, 0f)
    }

    @Test
    fun rumboNegativoOMayorA360_fijarRumboManual_seNormalizaA0_360() {
        val motor = PdrEngine()

        motor.fijarRumboManual(-90f)
        assertEquals(270f, motor.rumbo, 0f)

        motor.fijarRumboManual(450f)
        assertEquals(90f, motor.rumbo, 0f)
    }

    @Test
    fun cincoPasosEnDosSegundos_onPaso_calculaLaVelocidad() {
        val motor = PdrEngine(longitudPasoM = 0.72)
        motor.fijarPosicion(6.2, -75.578)

        listOf(0L, 500L, 1_000L, 1_500L, 2_000L).forEach { motor.onPaso(it) }

        assertEquals(4 * 0.72 / 2.0, motor.velocidadMps, delta)
    }

    @Test
    fun unSoloPaso_onPaso_velocidadEsCero() {
        val motor = PdrEngine()
        motor.fijarPosicion(6.2, -75.578)

        motor.onPaso(1_000)

        assertEquals(0.0, motor.velocidadMps, delta)
    }

    @Test
    fun trasCaminar_reiniciar_vuelveAlPuntoDePartidaConContadoresEnCero() {
        val motor = PdrEngine()
        motor.fijarPosicion(6.2, -75.578)
        motor.onPaso(0)
        motor.onPaso(600)

        motor.reiniciar()

        assertEquals(0, motor.pasos)
        assertEquals(0.0, motor.velocidadMps, delta)
        assertEquals(6.2, motor.lat!!, delta)
        assertEquals(-75.578, motor.lng!!, delta)
    }
}
