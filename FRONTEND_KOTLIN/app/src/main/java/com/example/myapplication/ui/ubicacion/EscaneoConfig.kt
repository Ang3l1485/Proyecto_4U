package com.example.myapplication.ui.ubicacion

import androidx.compose.ui.graphics.Color

/**
 * Parámetros ajustables del escaneo 360°.
 * Se agrupan en un objeto para no chocar con otros archivos del paquete `ubicacion`.
 */
internal object EscaneoConfig {
    /** Fotos a capturar durante la vuelta (0°, 72°, 144°, 216°, 288°). */
    const val TOTAL_FOTOS = 5

    /** Grados entre foto y foto (72°). */
    const val GRADOS_POR_FOTO = 360f / TOTAL_FOTOS

    /** Velocidad angular máxima (°/s). Por encima se pide "Más despacio". */
    const val VELOCIDAD_MAX = 45f

    /** Desvío máximo (°) respecto a la vertical para considerar el celular derecho. */
    const val INCLINACION_MAX = 20f

    /** Sin avanzar este tiempo = vuelta incompleta. */
    const val INACTIVIDAD_MS = 20_000L

    /** Mínimo de tiempo entre avisos hablados (evita que la voz se encime). */
    const val AVISO_CADA_MS = 4_000L

    /** Tiempo máximo de espera de la respuesta del backend. */
    const val TIMEOUT_BACKEND_MS = 30_000L
}

/** Paleta de la pantalla (fondo oscuro, alto contraste). */
internal object EscaneoColores {
    val Fondo = Color(0xFF030712)
    val Panel = Color(0xFF0B1220)
    val Morado = Color(0xFF7C3AED)
    val MoradoBoton = Color(0xFF6D4AFF)
    val MoradoClaro = Color(0xFFA78BFA)
    val Pista = Color(0xFF2A2F45)
    val TextoSecundario = Color(0xFF9CA3AF)
    val Verde = Color(0xFF22E58B)
    val Rojo = Color(0xFFEF4444)
}