package com.example.myapplication.hu02

import com.example.myapplication.domain.usecase.InterpretarRespuesta
import com.example.myapplication.domain.usecase.Respuesta
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * HU-02 / Selección de destino: confirmación por voz ("¿Quieres ir a X? Di sí o no.").
 *
 * `InterpretarRespuesta.interpretar` compara palabras completas tras normalizar
 * (ARCHITECTURE_front.md §11.7): solo sí -> SI · solo no -> NO · ambas o ninguna -> NINGUNA.
 * Lógica pura: corre en JVM.
 */
class InterpretarRespuestaTest {

    private fun r(texto: String) = InterpretarRespuesta.interpretar(texto)

    // ------------------------------------------------------------------ camino feliz

    @Test
    fun reconoce_las_palabras_de_afirmacion() {
        assertEquals(Respuesta.SI, r("sí"))
        assertEquals(Respuesta.SI, r("claro que sí"))
        assertEquals(Respuesta.SI, r("Dale"))
        assertEquals(Respuesta.SI, r("ok"))
        assertEquals(Respuesta.SI, r("vamos"))
    }

    @Test
    fun reconoce_las_palabras_de_negacion() {
        assertEquals(Respuesta.NO, r("no"))
        assertEquals(Respuesta.NO, r("no, cancela"))
        assertEquals(Respuesta.NO, r("otro"))
        assertEquals(Respuesta.NO, r("negativo"))
    }

    // ------------------------------------------------------------------ alternos

    @Test
    fun una_respuesta_contradictoria_no_es_ni_si_ni_no() {
        assertEquals(Respuesta.NINGUNA, r("sí pero no"))
    }

    @Test
    fun las_hipotesis_unidas_del_reconocedor_con_si_y_no_no_se_asumen() {
        // VoiceController.listen une hasta 3 hipótesis con espacios.
        assertEquals(Respuesta.NINGUNA, r("sí no sí"))
    }

    @Test
    fun una_frase_sin_palabras_clave_no_es_respuesta() {
        assertEquals(Respuesta.NINGUNA, r("tal vez"))
        assertEquals(Respuesta.NINGUNA, r("está bien"))
        assertEquals(Respuesta.NINGUNA, r("de acuerdo"))
    }

    @Test
    fun un_texto_vacio_no_es_respuesta() {
        assertEquals(Respuesta.NINGUNA, r(""))
        assertEquals(Respuesta.NINGUNA, r("   "))
    }

    @Test
    fun ignora_mayusculas_tildes_y_signos_de_puntuacion() {
        assertEquals(Respuesta.SI, r("¡SÍ!"))
        assertEquals(Respuesta.NO, r("¡NO!"))
    }
}
