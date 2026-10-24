package com.example.myapplication.domain.model

/**
 * Punto de partida que el admin fija en la vista 7.3 antes de empezar a recolectar.
 *
 * Es lo que la vista 7.4 (Recolección en curso) recibe para arrancar el PDR y crear el video.
 */
data class InicioRecoleccion(
    /** Latitud WGS84. */
    val lat: Double,
    /** Longitud WGS84. */
    val lng: Double,
    /**
     * Hacia dónde mira, en grados 0…360 (0 = norte, sentido horario).
     * Ojo: si vino de la brújula del teléfono es norte **magnético** (ver 11.2).
     */
    val rumbo: Float,
    /** Nombre final del video: ya recortado y nunca vacío. */
    val nombreVideo: String,
    /** `true` si el punto salió de "Usar mi última posición" y no se movió después. */
    val continuaVideoAnterior: Boolean,
)