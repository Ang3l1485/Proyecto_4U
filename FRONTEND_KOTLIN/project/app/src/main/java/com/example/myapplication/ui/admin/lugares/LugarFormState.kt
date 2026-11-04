package com.example.myapplication.ui.admin.lugares

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino

/** Estado de la vista 7.7 · Formulario de lugar (FE-3.4). */
data class LugarFormUiState(
    val esNuevo: Boolean = true,
    /** Editando: mientras se lee el lugar del backend. */
    val cargando: Boolean = false,
    /** Editando: no se pudo leer el lugar (o ya no existe); la pantalla ofrece «Reintentar» y «Volver». */
    val errorCarga: String? = null,
    val campos: CamposLugar = CamposLugar(),
    val errores: ErroresLugar = ErroresLugar.NINGUNO,
    /** Los demás lugares, como contexto en el mapa (vacío si no se pudieron leer: no impide crear). */
    val otros: List<LugarDestino> = emptyList(),
    val totalFotos: Int = 0,
    /** `POST`/`PUT`/`DELETE` en curso (y, tras un éxito, hasta salir: evita un segundo toque). */
    val guardando: Boolean = false,
    val confirmandoBorrar: Boolean = false,
) {
    /** «Punto: 6.200512, -75.578311» (o «sin elegir»): el pie de la pantalla; lo lee `validate34.py`. */
    val textoPunto: String get() = FormularioLugar.textoPunto(campos.punto)
}

/** Cosas de una sola vez de 7.7 (por `Channel`): la pantalla vuelve a 7.6. */
sealed interface LugarFormEvento {
    data class Guardado(val nombre: String) : LugarFormEvento
    data class Eliminado(val nombre: String) : LugarFormEvento
}

/** Acciones de 7.7 (`{}` por defecto, para los `@Preview`). */
data class LugarFormAcciones(
    val onVolver: () -> Unit = {},
    val onNombre: (String) -> Unit = {},
    val onAlias: (String) -> Unit = {},
    val onDescripcion: (String) -> Unit = {},
    val onCategoria: (CategoriaLugar) -> Unit = {},
    val onPunto: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    val onReferencias: (String) -> Unit = {},
    val onGuardar: () -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onPedirBorrar: () -> Unit = {},
    val onConfirmarBorrar: () -> Unit = {},
    val onCancelarBorrar: () -> Unit = {},
    /** FE-4.1: «Ver en la galería» de «Fotos asociadas» (solo al editar). */
    val onVerFotos: () -> Unit = {},
)
