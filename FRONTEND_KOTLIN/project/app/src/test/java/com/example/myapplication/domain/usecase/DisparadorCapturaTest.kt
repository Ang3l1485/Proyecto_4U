package com.example.myapplication.domain.usecase

import com.example.myapplication.sensors.PdrEngine
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.ceil

/**
 * FE-2.3 C1: cuándo se toma la siguiente foto de la recolección (7.4; ARCHITECTURE §5.2 «Flujo de captura de la
 * recolección» y §5.7). `DisparadorCaptura` no tiene reloj: recibe la distancia acumulada del PDR y la hora.
 */
class DisparadorCapturaTest {

    @Test
    fun la_primera_foto_es_inmediata() {
        assertTrue(DisparadorCaptura().debeCapturar(0.0, 0))
        assertTrue(DisparadorCaptura(ModoCaptura.PorTiempo(5)).debeCapturar(0.0, 123_456))
    }

    @Test
    fun por_distancia_dispara_al_recorrer_los_metros() {
        val d = DisparadorCaptura(ModoCaptura.PorDistancia(5.0))
        d.alCapturar(distanciaTotalM = 0.0, ahoraMs = 1_000)
        assertFalse(d.debeCapturar(4.99, 1_000_000)) // el tiempo no cuenta
        assertTrue(d.debeCapturar(5.0, 1_001))
        d.alCapturar(5.0, 1_001)
        assertFalse(d.debeCapturar(9.9, 2_000))
        assertTrue(d.debeCapturar(10.2, 2_000))
    }

    @Test
    fun por_tiempo_dispara_al_pasar_los_segundos() {
        val d = DisparadorCaptura(ModoCaptura.PorTiempo(3))
        d.alCapturar(0.0, 1_000)
        assertFalse(d.debeCapturar(500.0, 3_999)) // la distancia no cuenta
        assertTrue(d.debeCapturar(0.0, 4_000))
    }

    @Test
    fun si_la_foto_falla_sigue_diciendo_que_si() {
        // Sin alCapturar (la foto no se guardó) no avanza la referencia: quien lo usa pone su propia pausa.
        val d = DisparadorCaptura(ModoCaptura.PorDistancia(5.0))
        d.alCapturar(0.0, 0)
        assertTrue(d.debeCapturar(6.0, 10))
        assertTrue(d.debeCapturar(6.5, 20))
    }

    @Test
    fun cambiar_el_intervalo_no_dispara_y_cuenta_desde_la_ultima_foto() {
        val d = DisparadorCaptura()
        assertEquals(ModoCaptura.POR_DEFECTO, d.modo)
        d.alCapturar(10.0, 1_000)
        d.cambiarModo(ModoCaptura.PorDistancia(3.0))
        assertEquals(ModoCaptura.PorDistancia(3.0), d.modo)
        assertFalse(d.debeCapturar(12.9, 1_000))
        assertTrue(d.debeCapturar(13.0, 1_000))

        d.cambiarModo(ModoCaptura.PorTiempo(5))
        assertFalse(d.debeCapturar(50.0, 5_999))
        assertTrue(d.debeCapturar(10.0, 6_000))
    }

    @Test
    fun al_reanudar_el_tiempo_en_pausa_no_cuenta() {
        val d = DisparadorCaptura(ModoCaptura.PorTiempo(3))
        d.alCapturar(0.0, 1_000)
        d.alReanudar(10_000) // estuvo en pausa de 1 s a 10 s
        assertFalse(d.debeCapturar(0.0, 12_999))
        assertTrue(d.debeCapturar(0.0, 13_000))
    }

    @Test
    fun reanudar_antes_de_la_primera_foto_no_la_retrasa() {
        val d = DisparadorCaptura(ModoCaptura.PorTiempo(3))
        d.alReanudar(10_000)
        assertTrue(d.debeCapturar(0.0, 10_000))
    }

    @Test
    fun reiniciar_vuelve_a_pedir_la_primera_foto() {
        val d = DisparadorCaptura()
        d.alCapturar(3.0, 1_000)
        assertFalse(d.debeCapturar(3.0, 1_000))
        d.reiniciar()
        assertTrue(d.debeCapturar(3.0, 1_000))
    }

    @Test
    fun etiquetas_opciones_y_valor_por_defecto() {
        assertEquals(ModoCaptura.PorDistancia(5.0), ModoCaptura.POR_DEFECTO)
        assertEquals("Cada 5 m", ModoCaptura.PorDistancia(5.0).etiqueta)
        assertEquals("Cada 2.5 m", ModoCaptura.PorDistancia(2.5).etiqueta)
        assertEquals("Cada 3 s", ModoCaptura.PorTiempo(3).etiqueta)
        assertEquals(
            listOf("Cada 3 m", "Cada 5 m", "Cada 10 m", "Cada 3 s", "Cada 5 s"),
            ModoCaptura.OPCIONES.map { it.etiqueta },
        )
    }

    /**
     * Lo que pide FE-2.3 (C3): con la longitud calibrada, el disparador de 5 m dispara cada `ceil(5 / longitud)`
     * pasos (≈ `5 / longitud`), porque la distancia del PDR es `pasos × longitud`.
     */
    @Test
    fun con_el_pdr_dispara_cada_5_entre_longitud_pasos() {
        for (longitud in listOf(0.50, 0.68, 0.72, 0.75, 0.90)) {
            val motor = PdrEngine(longitudPasoM = longitud).apply { fijarPosicion(6.2, -75.578) }
            val disparador = DisparadorCaptura(ModoCaptura.PorDistancia(5.0))
            val pasosDeCadaFoto = mutableListOf<Int>()
            for (paso in 0..100) {
                if (paso > 0) motor.onPaso(1_000L + paso * 500)
                if (disparador.debeCapturar(motor.distanciaMetros, 0)) {
                    pasosDeCadaFoto += motor.pasos
                    disparador.alCapturar(motor.distanciaMetros, 0)
                }
            }
            val esperado = ceil(5.0 / longitud).toInt()
            val separaciones = pasosDeCadaFoto.zipWithNext { a, b -> b - a }
            assertEquals("longitud $longitud: primera foto en el paso 0", 0, pasosDeCadaFoto.first())
            assertTrue("longitud $longitud: $separaciones", separaciones.all { it == esperado })
            assertEquals("longitud $longitud", 100 / esperado + 1, pasosDeCadaFoto.size)
        }
    }
}
