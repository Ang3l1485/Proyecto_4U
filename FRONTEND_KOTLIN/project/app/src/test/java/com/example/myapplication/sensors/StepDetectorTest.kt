package com.example.myapplication.sensors

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random

/**
 * FE-2.3 C1: detector de pasos por acelerómetro (ARCHITECTURE §5.2, `StepDetector`), con señales sintéticas a 50 Hz
 * (como `SENSOR_DELAY_GAME`). La aceleración va en el eje z con la gravedad incluida: el detector usa la magnitud.
 *
 * Los tiempos empiezan en [T0] (como `elapsedRealtime`, nunca 0): el detector arranca con el último paso en t = 0 y
 * exige [StepDetector.PAUSA_MS] desde él, así que un paso en los primeros 250 ms de un reloj que empieza en 0 no
 * contaría (en el teléfono no pasa).
 */
class StepDetectorTest {

    private companion object {
        const val T0 = 100_000L
        const val MUESTRA_MS = 20L // 50 Hz
    }

    /** Pasa [segundos] de señal `desviacion(t en s)` (m/s² sobre la gravedad) y devuelve cuántos pasos contó. */
    private fun StepDetector.contar(segundos: Double, desde: Long = T0, detectar: Boolean = true, desviacion: (Double) -> Double): Int {
        var pasos = 0
        val muestras = (segundos * 1000 / MUESTRA_MS).toInt()
        for (i in 0 until muestras) {
            val tMs = desde + i * MUESTRA_MS
            val a = desviacion((i * MUESTRA_MS) / 1000.0)
            if (procesar(0f, 0f, (StepDetector.GRAVEDAD + a).toFloat(), tMs, detectar)) pasos++
        }
        return pasos
    }

    /** Caminata: un pico por paso, [pasosPorSegundo] pasos por segundo. */
    private fun caminata(amplitud: Double, pasosPorSegundo: Double = 2.0): (Double) -> Double =
        { t -> amplitud * sin(2 * PI * pasosPorSegundo * t) }

    @Test
    fun quieto_no_cuenta_pasos() {
        assertEquals(0, StepDetector().contar(10.0) { 0.0 })
    }

    @Test
    fun temblor_de_mano_y_ruido_no_cuentan_pasos() {
        assertEquals(0, StepDetector().contar(10.0) { t -> 0.5 * sin(2 * PI * 8 * t) })
        val azar = Random(42)
        assertEquals(0, StepDetector().contar(10.0) { azar.nextDouble(-0.6, 0.6) })
    }

    @Test
    fun caminata_normal_cuenta_un_paso_por_pico() {
        // 10 s a 2 pasos/s = 20 pasos.
        val pasos = StepDetector().contar(10.0, desviacion = caminata(3.0))
        assertTrue("contó $pasos", pasos in 19..21)
    }

    @Test
    fun caminata_suave_y_fuerte_tambien_cuentan_por_el_umbral_adaptativo() {
        val suave = StepDetector().contar(10.0, desviacion = caminata(1.8))
        val fuerte = StepDetector().contar(10.0, desviacion = caminata(6.0))
        assertTrue("suave contó $suave", suave in 19..21)
        assertTrue("fuerte contó $fuerte", fuerte in 19..21)
    }

    @Test
    fun umbral_arranca_en_1_4_y_se_adapta_dentro_de_sus_limites() {
        val d = StepDetector()
        assertEquals(StepDetector.UMBRAL, d.umbral, 1e-6f)

        d.contar(20.0, desviacion = caminata(20.0)) // picos recortados a PICO_MAX = 8
        assertEquals(StepDetector.UMBRAL_MAX, d.umbral, 0.05f)

        val suave = StepDetector()
        suave.contar(20.0, desviacion = caminata(1.5))
        assertTrue("umbral ${suave.umbral}", suave.umbral >= StepDetector.UMBRAL_MIN)
        assertTrue("umbral ${suave.umbral}", suave.umbral < StepDetector.UMBRAL)
    }

    @Test
    fun pausa_minima_de_250_ms_entre_pasos() {
        val d = StepDetector()
        var t = T0
        fun pulso(): Int {
            var pasos = 0
            // 2 muestras arriba (4 m/s²) y 3 abajo (−2 m/s²): sube y vuelve a armarse.
            for (a in listOf(4.0, 4.0, -2.0, -2.0, -2.0)) {
                if (d.procesar(0f, 0f, (StepDetector.GRAVEDAD + a).toFloat(), t)) pasos++
                t += MUESTRA_MS
            }
            return pasos
        }
        assertEquals(1, pulso()) // t0
        assertEquals(0, pulso()) // ~100 ms después: rebote, no cuenta
        assertEquals(0, pulso()) // ~200 ms
        assertEquals(1, pulso()) // ~300 ms: ya pasó la pausa
    }

    @Test
    fun cuenta_en_el_flanco_de_subida_con_latencia_de_una_muestra() {
        val d = StepDetector()
        var t = T0
        repeat(10) { assertFalse(d.procesar(0f, 0f, StepDetector.GRAVEDAD, t)); t += MUESTRA_MS }
        // Salto a +3 m/s²: la filtrada pasa a 1,5 (> 1,4) en la primera muestra.
        assertTrue(d.procesar(0f, 0f, StepDetector.GRAVEDAD + 3f, t))
    }

    @Test
    fun solo_cuentan_los_picos_positivos() {
        // Valles de −4 m/s² (p. ej. el teléfono que cae un poco) no son pasos.
        assertEquals(0, StepDetector().contar(5.0) { t -> -4.0 * maxOf(0.0, sin(2 * PI * 2 * t)) })
    }

    @Test
    fun usa_la_magnitud_de_los_tres_ejes() {
        val d = StepDetector()
        var t = T0
        // Teléfono en vertical: la gravedad cae en y.
        repeat(10) { d.procesar(0f, StepDetector.GRAVEDAD, 0f, t); t += MUESTRA_MS }
        // 3 m/s² en z (perpendicular) suben la magnitud solo ~0,45 m/s²: no es paso.
        assertFalse(d.procesar(0f, StepDetector.GRAVEDAD, 3f, t))
        t += MUESTRA_MS
        // 6 m/s² en z suben la magnitud ~1,7 m/s²: un paso (la filtrada cruza el umbral a la tercera muestra).
        var pasos = 0
        repeat(3) { if (d.procesar(0f, StepDetector.GRAVEDAD, 6f, t)) pasos++; t += MUESTRA_MS }
        assertEquals(1, pasos)
    }

    @Test
    fun detectar_false_solo_actualiza_la_desviacion() {
        val d = StepDetector()
        val pasos = d.contar(5.0, detectar = false, desviacion = caminata(3.0))
        assertEquals(0, pasos)
        assertTrue(d.ultimaDesviacion > 0f)
    }

    @Test
    fun reiniciar_vuelve_al_estado_inicial() {
        val d = StepDetector()
        d.contar(10.0, desviacion = caminata(8.0))
        assertTrue(d.umbral > StepDetector.UMBRAL)
        d.reiniciar()
        assertEquals(StepDetector.UMBRAL, d.umbral, 1e-6f)
        assertEquals(0f, d.ultimaDesviacion, 0f)
        // Y vuelve a contar normal.
        val pasos = d.contar(10.0, desde = T0 * 2, desviacion = caminata(3.0))
        assertTrue("contó $pasos", pasos in 19..21)
    }
}
