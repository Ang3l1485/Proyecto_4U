package com.example.myapplication.domain.usecase

import com.example.myapplication.sensors.PdrEngine
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-2.3 C1: calibración de la longitud de paso (7.3b, ARCHITECTURE §5.7) y su efecto en el PDR
 * (`distanciaMetros = pasos × longitud guardada`, §5.2). Lógica pura: corre en la JVM.
 */
class CalibracionPasoTest {

    private val delta = 1e-9

    // ── distanciaEntre (haversine) ──────────────────────────────────────────────

    @Test
    fun haversine_0_0003_grados_de_latitud_son_unos_33_4_m() {
        val d = CalibracionPaso.distanciaEntre(6.2000, -75.5780, 6.2003, -75.5780)
        assertEquals(33.36, d, 0.05)
    }

    @Test
    fun haversine_mismo_punto_es_cero_y_es_simetrica() {
        assertEquals(0.0, CalibracionPaso.distanciaEntre(6.2, -75.57, 6.2, -75.57), delta)
        val ida = CalibracionPaso.distanciaEntre(6.2000, -75.5780, 6.2004, -75.5776)
        val vuelta = CalibracionPaso.distanciaEntre(6.2004, -75.5776, 6.2000, -75.5780)
        assertEquals(ida, vuelta, delta)
    }

    // ── calcular: resultado válido ──────────────────────────────────────────────

    @Test
    fun longitud_es_distancia_entre_pasos_con_cadencia_y_velocidad() {
        val r = CalibracionPaso.calcular(distanciaM = 30.0, pasos = 42, duracionS = 25.0)
        assertTrue(r is ResultadoCalibracion.Valido)
        r as ResultadoCalibracion.Valido
        assertEquals(30.0 / 42, r.longitudPasoM, delta)
        assertEquals(42, r.pasos)
        assertEquals(30.0, r.distanciaM, delta)
        assertEquals(25.0, r.duracionS, delta)
        assertEquals(100.8, r.cadenciaPpm, delta) // 42 pasos × 60 / 25 s
        assertEquals(1.2, r.velocidadMps, delta) // 30 m / 25 s
    }

    @Test
    fun minimos_de_tramo_y_pasos_son_inclusivos() {
        val r = CalibracionPaso.calcular(CalibracionPaso.MIN_DISTANCIA_M, CalibracionPaso.MIN_PASOS, 10.0)
        assertTrue(r is ResultadoCalibracion.Valido)
    }

    @Test
    fun limites_de_longitud_0_40_y_1_20_son_validos() {
        val corto = CalibracionPaso.calcular(12.0, 30, 10.0) // 0,40 m
        val largo = CalibracionPaso.calcular(36.0, 30, 10.0) // 1,20 m
        assertEquals(0.40, (corto as ResultadoCalibracion.Valido).longitudPasoM, delta)
        assertEquals(1.20, (largo as ResultadoCalibracion.Valido).longitudPasoM, delta)
    }

    @Test
    fun duracion_cero_no_rompe_y_da_cadencia_y_velocidad_cero() {
        val r = CalibracionPaso.calcular(30.0, 40, 0.0) as ResultadoCalibracion.Valido
        assertEquals(0.0, r.cadenciaPpm, delta)
        assertEquals(0.0, r.velocidadMps, delta)
        assertEquals(0.75, r.longitudPasoM, delta)
    }

    // ── calcular: rechazos y su orden (tramo → pasos → rango) ───────────────────

    @Test
    fun tramo_corto_se_rechaza_sin_longitud() {
        val r = CalibracionPaso.calcular(9.99, 20, 10.0)
        assertEquals(ResultadoCalibracion.Invalido(MotivoInvalido.TRAMO_CORTO), r)
        assertNull((r as ResultadoCalibracion.Invalido).longitudPasoM)
    }

    @Test
    fun pocos_pasos_se_rechaza_sin_longitud() {
        val r = CalibracionPaso.calcular(30.0, CalibracionPaso.MIN_PASOS - 1, 10.0)
        assertEquals(ResultadoCalibracion.Invalido(MotivoInvalido.POCOS_PASOS), r)
    }

    @Test
    fun paso_muy_corto_y_muy_largo_traen_la_longitud_calculada() {
        val corto = CalibracionPaso.calcular(10.0, 30, 10.0) as ResultadoCalibracion.Invalido
        assertEquals(MotivoInvalido.PASO_MUY_CORTO, corto.motivo)
        assertEquals(10.0 / 30, corto.longitudPasoM!!, delta)

        val largo = CalibracionPaso.calcular(30.0, 20, 10.0) as ResultadoCalibracion.Invalido
        assertEquals(MotivoInvalido.PASO_MUY_LARGO, largo.motivo)
        assertEquals(1.5, largo.longitudPasoM!!, delta)
    }

    @Test
    fun orden_de_comprobacion_es_tramo_luego_pasos_luego_rango() {
        // Tramo corto y pocos pasos: gana el tramo.
        assertEquals(MotivoInvalido.TRAMO_CORTO, (CalibracionPaso.calcular(5.0, 3, 1.0) as ResultadoCalibracion.Invalido).motivo)
        // Pocos pasos y longitud fuera de rango (30 m / 10 = 3 m): ganan los pasos.
        assertEquals(MotivoInvalido.POCOS_PASOS, (CalibracionPaso.calcular(30.0, 10, 1.0) as ResultadoCalibracion.Invalido).motivo)
    }

    // ── Efecto en el PDR (7.3b → 7.4): distanciaMetros = pasos × longitud guardada ───

    @Test
    fun pdr_por_defecto_usa_0_72_m() {
        assertEquals(0.72, PdrEngine.LONGITUD_PASO_DEFECTO_M, delta)
        assertEquals(0.72, PdrEngine().longitudPasoM, delta)
    }

    @Test
    fun pdr_sin_posicion_inicial_no_cuenta_pasos() {
        val motor = PdrEngine(longitudPasoM = 0.68)
        assertFalse(motor.onPaso(1_000))
        assertEquals(0, motor.pasos)
        assertEquals(0.0, motor.distanciaMetros, delta)
    }

    @Test
    fun pdr_con_la_longitud_calibrada_recorre_pasos_por_longitud() {
        // Calibración en un tramo de ~33,4 m con 47 pasos.
        val tramo = CalibracionPaso.distanciaEntre(6.2000, -75.5780, 6.2003, -75.5780)
        val calibrada = (CalibracionPaso.calcular(tramo, 47, 30.0) as ResultadoCalibracion.Valido).longitudPasoM

        // Recolección con esa longitud: los mismos 47 pasos hacia el norte dan la misma distancia.
        val motor = PdrEngine(longitudPasoM = calibrada)
        motor.fijarPosicion(6.2000, -75.5780)
        motor.fijarRumboManual(0f)
        repeat(47) { i -> assertTrue(motor.onPaso(1_000L + i * 500)) }

        assertEquals(47, motor.pasos)
        assertEquals(47 * calibrada, motor.distanciaMetros, delta)
        assertEquals(tramo, motor.distanciaMetros, 1e-6)
        // La posición avanza esa distancia (PdrEngine usa 111 320 m por grado; haversine, el radio medio).
        val avanzado = CalibracionPaso.distanciaEntre(6.2000, -75.5780, motor.lat!!, motor.lng!!)
        assertEquals(tramo, avanzado, 0.1)
    }
}
