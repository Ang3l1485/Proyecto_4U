package com.example.myapplication.sensors

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-2.3 (C5): el PDR solo lee sensores con el rastreo pedido y la app en primer plano (ARCHITECTURE §5.2). */
class InterruptorSensoresTest {

    @Test
    fun iniciar_y_detener_en_primer_plano() {
        val i = InterruptorSensores()
        assertEquals(CambioSensores.REGISTRAR, i.iniciar())
        assertTrue(i.registrados)
        assertEquals(CambioSensores.NINGUNO, i.iniciar()) // idempotente
        assertEquals(CambioSensores.QUITAR, i.detener())
        assertFalse(i.registrados)
        assertEquals(CambioSensores.NINGUNO, i.detener())
    }

    @Test
    fun segundo_plano_quita_y_primer_plano_vuelve_a_registrar() {
        val i = InterruptorSensores()
        i.iniciar()
        assertEquals(CambioSensores.QUITAR, i.alSegundoPlano())
        assertTrue(i.pedido) // el rastreo sigue pedido (PdrEstado.activo)
        assertFalse(i.registrados)
        assertEquals(CambioSensores.REGISTRAR, i.alPrimerPlano())
        assertTrue(i.registrados)
    }

    @Test
    fun detener_en_segundo_plano_no_vuelve_a_registrar_al_volver() {
        // Lo que hacen la recolección (pausa) y la calibración (cancela) en ON_STOP.
        val i = InterruptorSensores()
        i.iniciar()
        i.alSegundoPlano()
        assertEquals(CambioSensores.NINGUNO, i.detener())
        assertEquals(CambioSensores.NINGUNO, i.alPrimerPlano())
        assertFalse(i.registrados)
    }

    @Test
    fun detener_antes_del_segundo_plano_tampoco_vuelve() {
        val i = InterruptorSensores()
        i.iniciar()
        assertEquals(CambioSensores.QUITAR, i.detener())
        assertEquals(CambioSensores.NINGUNO, i.alSegundoPlano())
        assertEquals(CambioSensores.NINGUNO, i.alPrimerPlano())
        assertFalse(i.registrados)
    }

    @Test
    fun iniciar_en_segundo_plano_espera_al_primer_plano() {
        val i = InterruptorSensores(enPrimerPlano = false)
        assertEquals(CambioSensores.NINGUNO, i.iniciar())
        assertTrue(i.pedido)
        assertFalse(i.registrados)
        assertEquals(CambioSensores.REGISTRAR, i.alPrimerPlano())
    }

    @Test
    fun sin_rastreo_pedido_el_ciclo_de_vida_no_registra_nada() {
        val i = InterruptorSensores()
        assertEquals(CambioSensores.NINGUNO, i.alSegundoPlano())
        assertEquals(CambioSensores.NINGUNO, i.alPrimerPlano())
        assertFalse(i.registrados)
    }
}
