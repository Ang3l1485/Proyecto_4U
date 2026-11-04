package com.example.myapplication.ui.ubicacion

import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.map.PruebaMapa

/**
 * Ubicación de prueba de «Ubicarme» (FE-3.6, ADR-FE-42): **solo** la usa `MainActivity` en el APK de depuración, en un
 * arranque nuevo y con una ruta de prueba (`--es ruta resultado|mapa --es ubicacion_prueba <lat>,<lng>`), para validar
 * en casa la 6.3 con alertas y el mapa que empieza en la posición de «Ubicarme», sin cámara ni `POST /v1/localize`.
 * El resultado se registra en `SesionDeNavegacion` como si fuera la respuesta del escaneo. El flujo real nunca la usa.
 */
object PruebaUbicacion {
    /** Radio (dispersión) de la posición de prueba, en metros: la incertidumbre con que se buscan las alertas. */
    const val RADIO_M = 5.0

    /**
     * `"6.201434,-75.578427"` → un `Ubicado` de confianza alta en ese punto (radio [RADIO_M], sin lugar cercano ni
     * referencias, sin corrección de rumbo, 0 fotos); `null` si el texto no son dos números en rango.
     */
    fun resultado(texto: String?): ResultadoUbicacion.Ubicado? {
        val (lat, lng) = PruebaMapa.leerPosicion(texto) ?: return null
        return ResultadoUbicacion.Ubicado(
            posicion = PosicionEstimada(lat, lng, RADIO_M),
            confianza = 0.9,
            nivel = NivelConfianza.ALTA,
            correccionRumboGrados = null,
            lugarCercano = null,
            referencias = emptyList(),
            fotosUsadas = 0,
            fotosConCoincidencia = 0,
        )
    }
}
