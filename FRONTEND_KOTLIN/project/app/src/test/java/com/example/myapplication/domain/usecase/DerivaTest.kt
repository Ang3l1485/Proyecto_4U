package com.example.myapplication.domain.usecase

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * FE-2.3 C1: estimación provisional de la deriva del PDR (indicador «Calidad del seguimiento» de 7.4; ARCHITECTURE
 * §5.7). Deriva = 4 % de la distancia desde el último ancla; precisión mostrada = 25 % de la deriva, mínimo 1 m;
 * nivel ALTA < 15 m ≤ MEDIA < 30 m ≤ BAJA (de deriva, no de distancia).
 */
class DerivaTest {

    private val delta = 1e-9

    @Test
    fun recien_anclado_deriva_cero_precision_minima_y_calidad_alta() {
        val e = Deriva.estimar(0.0)
        assertEquals(0.0, e.derivaM, delta)
        assertEquals(1.0, e.precisionM, delta)
        assertEquals(NivelCalidad.ALTA, e.nivel)
    }

    @Test
    fun deriva_es_el_4_por_ciento_de_la_distancia_desde_el_ancla() {
        assertEquals(0.04, Deriva.FACTOR, delta)
        assertEquals(4.0, Deriva.estimar(100.0).derivaM, delta)
        assertEquals(8.0, Deriva.estimar(200.0).derivaM, delta)
        assertEquals(2 * Deriva.estimar(123.0).derivaM, Deriva.estimar(246.0).derivaM, delta)
    }

    @Test
    fun precision_es_un_cuarto_de_la_deriva_con_minimo_de_1_m() {
        assertEquals(1.0, Deriva.estimar(50.0).precisionM, delta) // deriva 2 m → 0,5 → mínimo 1
        assertEquals(1.0, Deriva.estimar(100.0).precisionM, delta) // deriva 4 m → 1
        assertEquals(2.0, Deriva.estimar(200.0).precisionM, delta) // deriva 8 m → 2
        assertEquals(10.0, Deriva.estimar(1000.0).precisionM, delta) // deriva 40 m → 10
    }

    @Test
    fun niveles_por_deriva_15_y_30_m() {
        assertEquals(15.0, Deriva.UMBRAL_MEDIA_M, delta)
        assertEquals(30.0, Deriva.UMBRAL_BAJA_M, delta)
        assertEquals(NivelCalidad.ALTA, Deriva.estimar(374.0).nivel) // 14,96 m
        assertEquals(NivelCalidad.MEDIA, Deriva.estimar(376.0).nivel) // 15,04 m
        assertEquals(NivelCalidad.MEDIA, Deriva.estimar(749.0).nivel) // 29,96 m
        assertEquals(NivelCalidad.BAJA, Deriva.estimar(751.0).nivel) // 30,04 m
        assertEquals(NivelCalidad.BAJA, Deriva.estimar(5_000.0).nivel)
    }

    @Test
    fun distancia_negativa_se_trata_como_cero() {
        val e = Deriva.estimar(-20.0)
        assertEquals(0.0, e.derivaM, delta)
        assertEquals(1.0, e.precisionM, delta)
        assertEquals(NivelCalidad.ALTA, e.nivel)
    }

    @Test
    fun etiquetas_de_los_niveles() {
        assertEquals(listOf("Alta", "Media", "Baja"), NivelCalidad.entries.map { it.etiqueta })
    }
}
