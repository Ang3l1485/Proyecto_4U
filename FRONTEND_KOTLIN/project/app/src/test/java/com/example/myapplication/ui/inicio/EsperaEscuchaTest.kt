package com.example.myapplication.ui.inicio

import com.example.myapplication.ui.inicio.EsperaEscucha.Companion.ESPERA_MINIMA_ESCUCHA_MS
import com.example.myapplication.ui.inicio.EsperaEscucha.Companion.MAX_REINTENTOS_ESCUCHA
import com.example.myapplication.ui.inicio.EsperaEscucha.Companion.PAUSA_REINTENTO_ESCUCHA_MS
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 0.19.0: espera mínima de 3 s antes de «no entendí» (decisión del usuario del 2026-10-28), con un reloj falso. */
class EsperaEscuchaTest {

    private var ahora = 1_000L
    private val reloj = { ahora }

    @Test
    fun antesDeTresSegundosReintentaYDespuesNoEntendi() {
        val espera = EsperaEscucha(reloj)
        ahora += 400 // el reconocedor dice «sin coincidencia» al instante
        assertTrue(espera.reintentar(FinSinTexto.SIN_COINCIDENCIA))
        ahora += 1_500
        assertTrue(espera.reintentar(FinSinTexto.TIEMPO_AGOTADO))
        ahora += 1_099 // 2999 ms: todavía dentro
        assertTrue(espera.reintentar(FinSinTexto.RESULTADO_VACIO))
        assertEquals(3, espera.reintentos)
        ahora += 1 // 3000 ms: ya cumplió la espera mínima
        assertFalse(espera.reintentar(FinSinTexto.SIN_COINCIDENCIA))
        assertEquals(3, espera.reintentos)
        assertEquals(ESPERA_MINIMA_ESCUCHA_MS, espera.transcurridoMs())
    }

    @Test
    fun soloLosFinesReintentablesSeReintentan() {
        val reintentables = FinSinTexto.entries.filter { it.reintentable }.toSet()
        assertEquals(
            setOf(
                FinSinTexto.SIN_COINCIDENCIA,
                FinSinTexto.TIEMPO_AGOTADO,
                FinSinTexto.RESULTADO_VACIO,
                FinSinTexto.OCUPADO,
                FinSinTexto.CLIENTE,
                FinSinTexto.VOZ_HABLANDO,
            ),
            reintentables,
        )
        // Sin permiso, red o audio: falla ya, aunque sea al primer milisegundo.
        val espera = EsperaEscucha(reloj)
        assertFalse(espera.reintentar(FinSinTexto.OTRO))
        assertEquals(0, espera.reintentos)
    }

    @Test
    fun unReconocedorQueFallaAlInstanteNoHaceBucleInfinito() {
        // Cada intento falla en 0 ms (peor caso: el reloj no avanza): el tope corta.
        val espera = EsperaEscucha(reloj)
        var vueltas = 0
        while (espera.reintentar(FinSinTexto.OCUPADO)) vueltas++
        assertEquals(MAX_REINTENTOS_ESCUCHA, vueltas)
        assertEquals(MAX_REINTENTOS_ESCUCHA, espera.reintentos)
        // El tope es lo que cabe en la espera con la pausa entre intentos.
        assertEquals(ESPERA_MINIMA_ESCUCHA_MS / PAUSA_REINTENTO_ESCUCHA_MS, MAX_REINTENTOS_ESCUCHA.toLong())
    }

    @Test
    fun conLaPausaRealCabenComoMuchoLosReintentosDeLaEspera() {
        // Fallo instantáneo + pausa de 300 ms antes de cada reintento: «no entendí» a los ≥ 3 s y no antes.
        val espera = EsperaEscucha(reloj)
        while (espera.reintentar(FinSinTexto.SIN_COINCIDENCIA)) ahora += PAUSA_REINTENTO_ESCUCHA_MS
        assertTrue(espera.transcurridoMs() >= ESPERA_MINIMA_ESCUCHA_MS)
        assertTrue(espera.reintentos <= MAX_REINTENTOS_ESCUCHA)
    }

    @Test
    fun laReglaSinEstado() {
        assertTrue(EsperaEscucha.debeReintentar(FinSinTexto.VOZ_HABLANDO, 0, 0))
        assertFalse(EsperaEscucha.debeReintentar(FinSinTexto.VOZ_HABLANDO, ESPERA_MINIMA_ESCUCHA_MS, 0))
        assertFalse(EsperaEscucha.debeReintentar(FinSinTexto.CLIENTE, 10, MAX_REINTENTOS_ESCUCHA))
        assertFalse(EsperaEscucha.debeReintentar(FinSinTexto.OTRO, 10, 0))
    }
}
