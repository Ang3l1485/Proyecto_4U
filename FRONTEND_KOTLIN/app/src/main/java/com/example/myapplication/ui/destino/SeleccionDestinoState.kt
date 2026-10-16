package com.example.myapplication.ui.destino

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino

/*
 * Modelo de estado de la vista 6.4 (Selección de destino).
 * La UI solo LEE DestinoUiState y el ViewModel es el único que lo escribe.
 */

enum class OrdenLugares(val etiqueta: String) {
    CERCANIA("Ordenado por cercanía"),
    NOMBRE("Ordenado por nombre"),
}

enum class ErrorDestino { SIN_CONEXION, DESCONOCIDO }

/** Estado completo que dibuja la pantalla. */
data class DestinoUiState(
    val cargando: Boolean = true,
    val error: ErrorDestino? = null,
    val sinMicrofono: Boolean = false,
    val escuchando: Boolean = false,

    /** Lo último que entendió el reconocimiento de voz (tarjeta "Texto reconocido"). */
    val textoReconocido: String? = null,
    /** Lugar que espera un "sí" o un "no" (tarjeta de confirmación). */
    val candidato: LugarDestino? = null,
    /** Varias coincidencias posibles: hay que pedirle a la persona que elija. */
    val opciones: List<LugarDestino> = emptyList(),

    val busqueda: String = "",
    val categoria: CategoriaLugar? = null,
    val orden: OrdenLugares = OrdenLugares.CERCANIA,
    /** Lista ya filtrada y ordenada. */
    val lugares: List<LugarDestino> = emptyList(),
)

/** Eventos de una sola vez ViewModel -> pantalla (no son estado). */
sealed interface DestinoEvento {
    /** La persona confirmó el destino: hay que ubicarla (si hace falta) y empezar a guiarla. */
    data class Confirmado(val lugar: LugarDestino) : DestinoEvento
}
