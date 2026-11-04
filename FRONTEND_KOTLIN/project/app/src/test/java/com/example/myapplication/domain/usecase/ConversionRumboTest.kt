package com.example.myapplication.domain.usecase

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.2, criterio C2 (ARCHITECTURE §5.10, «Rumbo»; backend ADR-BE-12): el acimut **magnético** del escaneo, en
 * (−180, 180], pasa a rumbo **verdadero** en [0, 360) sumando la declinación (positiva hacia el este), con −180, 180, 0
 * y declinaciones positivas y negativas; lo que el redondeo a 0,1° lleve a 360 sale como 0.
 */
class ConversionRumboTest {

    private val delta = 1e-9

    @Test
    fun sinDeclinacion_menos180_180_y_0() {
        assertEquals(180.0, ConversionRumbo.magneticoAVerdadero(-180.0, 0.0), delta)
        assertEquals(180.0, ConversionRumbo.magneticoAVerdadero(180.0, 0.0), delta)
        assertEquals(0.0, ConversionRumbo.magneticoAVerdadero(0.0, 0.0), delta)
        assertEquals(270.0, ConversionRumbo.magneticoAVerdadero(-90.0, 0.0), delta)
        assertEquals(90.0, ConversionRumbo.magneticoAVerdadero(90.0, 0.0), delta)
    }

    @Test
    fun declinacionPositiva_esteSumaYCruzaElNorte() {
        assertEquals(105.5, ConversionRumbo.magneticoAVerdadero(100.0, 5.5), delta)
        assertEquals(5.0, ConversionRumbo.magneticoAVerdadero(-10.0, 15.0), delta) // 350° magnético → 5° verdadero
        assertEquals(187.0, ConversionRumbo.magneticoAVerdadero(180.0, 7.0), delta)
        assertEquals(173.0, ConversionRumbo.magneticoAVerdadero(-180.0, -7.0), delta)
        assertEquals(7.0, ConversionRumbo.magneticoAVerdadero(0.0, 7.0), delta)
    }

    @Test
    fun declinacionNegativa_oesteRestaYCruzaElNorte() {
        // Medellín: ≈ −7° (oeste). 3° magnético → 355,4° verdadero.
        assertEquals(355.4, ConversionRumbo.magneticoAVerdadero(3.0, -7.6), delta)
        assertEquals(352.4, ConversionRumbo.magneticoAVerdadero(0.0, -7.6), delta)
        assertEquals(179.5, ConversionRumbo.magneticoAVerdadero(-179.5, -1.0), delta)
        assertEquals(172.4, ConversionRumbo.magneticoAVerdadero(180.0, -7.6), delta)
        assertEquals(82.4, ConversionRumbo.magneticoAVerdadero(90.0, -7.6), delta)
    }

    @Test
    fun resultadoSiempreEnElRangoDelContrato() {
        val declinaciones = listOf(-20.0, -7.6, 0.0, 7.6, 20.0)
        var acimut = -180.0
        while (acimut <= 180.0) {
            for (d in declinaciones) {
                val r = ConversionRumbo.magneticoAVerdadero(acimut, d)
                assertTrue("acimut $acimut, declinación $d → $r", r >= 0.0 && r < 360.0)
            }
            acimut += 0.37
        }
    }

    @Test
    fun normalizar_redondeaA01YNuncaDa360() {
        assertEquals(0.0, ConversionRumbo.normalizar(359.96), delta)
        assertEquals(0.0, ConversionRumbo.normalizar(-0.04), delta)
        assertEquals(0.0, ConversionRumbo.normalizar(360.0), delta)
        assertEquals(359.9, ConversionRumbo.normalizar(359.94), delta)
        assertEquals(5.5, ConversionRumbo.normalizar(725.5), delta)
        assertEquals(354.5, ConversionRumbo.normalizar(-365.5), delta)
    }

    @Test
    fun normalizar_rechazaNaNEInfinitos() {
        assertThrows(IllegalArgumentException::class.java) { ConversionRumbo.normalizar(Double.NaN) }
        assertThrows(IllegalArgumentException::class.java) { ConversionRumbo.normalizar(Double.POSITIVE_INFINITY) }
    }

    @Test
    fun diferencia_enMenos180_180() {
        assertEquals(20.0, ConversionRumbo.diferencia(10.0, 350.0), delta)
        assertEquals(-20.0, ConversionRumbo.diferencia(350.0, 10.0), delta)
        assertEquals(180.0, ConversionRumbo.diferencia(0.0, 180.0), delta)
        assertEquals(180.0, ConversionRumbo.diferencia(180.0, 0.0), delta)
        assertEquals(0.0, ConversionRumbo.diferencia(42.0, 42.0), delta)
    }
}
