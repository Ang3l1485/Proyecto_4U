package com.example.myapplication.ui.ubicacion

import com.example.myapplication.domain.usecase.DescripcionUbicacion

/**
 * Estado de la vista 6.3 (Resultado de ubicación, FE-3.2). La UI solo lo lee; lo escribe `ResultadoUbicacionViewModel`.
 *
 * [descripcion]: textos de `DescribirUbicacion` (título, distancia, referencias, confianza, avisos y lo hablado).
 * [hayPosicion]: hay una ubicación con posición (cambia el botón a «Ir a un lugar desde aquí»).
 * [mapaDisponible] (FE-3.6): la ubicación es vigente (alta o media, ≤ 2 min): se ofrece «Caminar con el mapa», que abre
 * el mapa público con el seguimiento ya empezado en esta posición.
 * Las alertas cercanas (FE-3.6) van en `descripcion.alertas`.
 */
data class ResultadoUiState(
    val descripcion: DescripcionUbicacion,
    val hayPosicion: Boolean,
    val mapaDisponible: Boolean = false,
    // FE-5.3: hay ruta por el grafo hasta el destino: se muestra «Guiarme» (vista 6.5).
    val hayRuta: Boolean = false,
)

/**
 * Acciones de la vista 6.3 (todas con valor por defecto para las vistas previas). La pantalla no conoce el
 * `NavController`: `AppNav` conecta [onVolverAUbicarme], [onIrALugar], [onInicio] y, desde FE-3.6, [onVerMapa]
 * (ARCHITECTURE §5.8).
 */
data class ResultadoAcciones(
    val onRepetir: () -> Unit = {},
    val onVolverAUbicarme: () -> Unit = {},
    val onIrALugar: () -> Unit = {},
    val onInicio: () -> Unit = {},
    val onVerMapa: () -> Unit = {},
    val onGuiarme: () -> Unit = {},
)
