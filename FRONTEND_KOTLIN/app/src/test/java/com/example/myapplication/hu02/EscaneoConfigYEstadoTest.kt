package com.example.myapplication.hu02

import com.example.myapplication.ui.ubicacion.EscaneoConfig
import com.example.myapplication.ui.ubicacion.EscaneoEvento
import com.example.myapplication.ui.ubicacion.EscaneoUiState
import com.example.myapplication.ui.ubicacion.ErrorEscaneo
import com.example.myapplication.ui.ubicacion.Fase
import com.example.myapplication.ui.ubicacion.Instruccion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HU-02 / "Ubicarme" (vista 6.2, escaneo 360°): parámetros y estado inicial.
 *
 * Fija los valores documentados en ARCHITECTURE_front.md §11.2 ("Parámetros (EscaneoConfig)" y
 * "Estado y eventos"): 5 fotos, una cada 72° a lo largo de 360°. Si alguien cambia un valor,
 * este test obliga a actualizar también la documentación.
 * `EscaneoConfig` es `internal`: es visible porque el test está en el mismo módulo.
 */
class EscaneoConfigYEstadoTest {

    // ------------------------------------------------------------------ parámetros

    @Test
    fun la_vuelta_se_reparte_en_cinco_fotos_de_72_grados() {
        assertEquals(5, EscaneoConfig.TOTAL_FOTOS)
        assertEquals(72f, EscaneoConfig.GRADOS_POR_FOTO, 0.0001f)
        assertEquals(360f, EscaneoConfig.GRADOS_POR_FOTO * EscaneoConfig.TOTAL_FOTOS, 0.0001f)
    }

    @Test
    fun los_limites_de_giro_inclinacion_y_tiempos_son_los_documentados() {
        assertEquals(45f, EscaneoConfig.VELOCIDAD_MAX, 0f)
        assertEquals(20f, EscaneoConfig.INCLINACION_MAX, 0f)
        assertEquals(20_000L, EscaneoConfig.INACTIVIDAD_MS)
        assertEquals(4_000L, EscaneoConfig.AVISO_CADA_MS)
        assertEquals(30_000L, EscaneoConfig.TIMEOUT_BACKEND_MS)
    }

    @Test
    fun el_aviso_hablado_es_mas_corto_que_la_inactividad_que_cancela_la_vuelta() {
        assertTrue(EscaneoConfig.AVISO_CADA_MS < EscaneoConfig.INACTIVIDAD_MS)
    }

    // ------------------------------------------------------------------ estado

    @Test
    fun el_escaneo_arranca_preparando_sin_progreso_ni_errores() {
        val s = EscaneoUiState()
        assertEquals(Fase.PREPARANDO, s.fase)
        assertEquals(0f, s.progreso, 0f)
        assertEquals(0, s.fotos)
        assertTrue(s.inclinacionOk)
        assertEquals(Instruccion.GIRAR, s.instruccion)
        assertNull(s.error)
    }

    @Test
    fun hay_exactamente_cuatro_fases() {
        assertEquals(
            listOf(Fase.PREPARANDO, Fase.ESCANEANDO, Fase.ANALIZANDO, Fase.ERROR),
            Fase.values().toList(),
        )
    }

    @Test
    fun las_instrucciones_tienen_el_texto_que_se_dice_y_se_muestra() {
        assertEquals("Gira lentamente\nhacia la derecha", Instruccion.GIRAR.texto)
        assertEquals("Más despacio", Instruccion.MAS_DESPACIO.texto)
        assertEquals("Mantén el celular vertical", Instruccion.VERTICAL.texto)
    }

    @Test
    fun cada_error_tiene_su_mensaje_para_leer_en_voz_alta() {
        assertEquals("Sin conexión con el servidor", ErrorEscaneo.SIN_CONEXION.mensaje)
        assertEquals("El análisis tardó demasiado", ErrorEscaneo.TIEMPO_AGOTADO.mensaje)
        assertEquals("No completaste la vuelta", ErrorEscaneo.VUELTA_INCOMPLETA.mensaje)
        assertEquals("Este teléfono no tiene sensor de giro", ErrorEscaneo.SIN_SENSOR.mensaje)
    }

    @Test
    fun los_mensajes_de_error_no_se_repiten() {
        val mensajes = ErrorEscaneo.values().map { it.mensaje }
        assertEquals(mensajes.size, mensajes.toSet().size)
    }

    @Test
    fun los_eventos_de_una_sola_vez_son_capturar_y_completado_y_son_distintos() {
        val eventos: List<EscaneoEvento> = listOf(EscaneoEvento.Capturar, EscaneoEvento.Completado)
        assertEquals(2, eventos.toSet().size)
    }
}
