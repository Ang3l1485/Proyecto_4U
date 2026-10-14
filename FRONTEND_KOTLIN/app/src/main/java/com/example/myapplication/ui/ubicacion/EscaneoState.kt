package com.example.myapplication.ui.ubicacion

/*
 * Modelo de estado de la pantalla de escaneo.
 * La UI solo LEE EscaneoUiState y el ViewModel es el único que lo escribe.
 */

/** Etapa general del escaneo. */
enum class Fase {
    PREPARANDO,   // se están diciendo las instrucciones por voz
    ESCANEANDO,   // el usuario gira y se capturan fotos
    ANALIZANDO,   // 5 fotos listas, esperando al backend
    ERROR,        // algo falló; se muestra el mensaje y "Repetir"
}

/** Instrucción que se muestra (y se dice) mientras escanea. */
enum class Instruccion(val texto: String) {
    GIRAR("Gira lentamente\nhacia la derecha"),
    MAS_DESPACIO("Más despacio"),
    VERTICAL("Mantén el celular vertical"),
}

/** Errores posibles; [mensaje] se muestra y se lee en voz alta. */
enum class ErrorEscaneo(val mensaje: String) {
    SIN_CONEXION("Sin conexión con el servidor"),
    TIEMPO_AGOTADO("El análisis tardó demasiado"),
    VUELTA_INCOMPLETA("No completaste la vuelta"),
    SIN_SENSOR("Este teléfono no tiene sensor de giro"),
}

/** Estado completo que dibuja la pantalla. */
data class EscaneoUiState(
    val fase: Fase = Fase.PREPARANDO,
    val progreso: Float = 0f,          // grados girados, 0..360
    val fotos: Int = 0,                // fotos aceptadas hasta ahora
    val inclinacionOk: Boolean = true, // celular suficientemente vertical
    val instruccion: Instruccion = Instruccion.GIRAR,
    val error: ErrorEscaneo? = null,
)

/** Eventos de una sola vez ViewModel -> pantalla (no son estado). */
sealed interface EscaneoEvento {
    /** Pide a la pantalla que dispare la cámara (la pantalla es dueña de CameraX). */
    data object Capturar : EscaneoEvento

    /** Las 5 fotos se analizaron bien: hay que navegar al Resultado. */
    data object Completado : EscaneoEvento
}