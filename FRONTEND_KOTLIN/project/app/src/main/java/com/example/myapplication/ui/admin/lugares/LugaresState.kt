package com.example.myapplication.ui.admin.lugares

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarAdmin
import com.example.myapplication.domain.usecase.BuscarLugares

/** Vista de la lista 7.6: lista de filas o mapa con los mismos lugares filtrados. */
enum class ModoLugares { LISTA, MAPA }

/** Estado de la vista 7.6 (FE-3.4). */
data class LugaresUiState(
    val cargando: Boolean = true,
    /** Error al cargar (con «Reintentar»); `null` sin error. */
    val error: String? = null,
    val todos: List<LugarAdmin> = emptyList(),
    val busqueda: String = "",
    val categoria: CategoriaLugar? = null,
    val modo: ModoLugares = ModoLugares.LISTA,
    /** Lugar del diálogo «¿Eliminar…?»; `null` = cerrado. */
    val confirmandoBorrar: LugarAdmin? = null,
    val borrando: Boolean = false,
    /** Aviso corto (««X» eliminado.», error al borrar); se descarta al tocarlo. */
    val aviso: String? = null,
) {
    /** Los lugares que pasan la búsqueda y la categoría, en el orden del backend (por nombre). */
    val visibles: List<LugarAdmin> get() = filtrarLugares(todos, busqueda, categoria)
    val hayFiltros: Boolean get() = busqueda.isNotBlank() || categoria != null
}

/**
 * Filtro de 7.6 (lógica pura): categoría exacta y el buscador de 6.4 (`BuscarLugares.filtrar`: cada palabra contenida
 * en el nombre, un alias o la etiqueta de la categoría).
 */
internal fun filtrarLugares(todos: List<LugarAdmin>, busqueda: String, categoria: CategoriaLugar?): List<LugarAdmin> {
    val porCategoria = if (categoria == null) todos else todos.filter { it.lugar.categoria == categoria }
    if (busqueda.isBlank()) return porCategoria
    val ids = BuscarLugares.filtrar(porCategoria.map { it.lugar }, busqueda).map { it.id }.toSet()
    return porCategoria.filter { it.id in ids }
}

/** Acciones de la vista 7.6 (`{}` por defecto, para los `@Preview`). */
data class LugaresAcciones(
    val onVolver: () -> Unit = {},
    val onNuevo: () -> Unit = {},
    val onEditar: (id: String) -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onBusqueda: (String) -> Unit = {},
    val onCategoria: (CategoriaLugar?) -> Unit = {},
    val onLimpiarFiltros: () -> Unit = {},
    val onModo: (ModoLugares) -> Unit = {},
    val onPedirBorrar: (LugarAdmin) -> Unit = {},
    val onConfirmarBorrar: () -> Unit = {},
    val onCancelarBorrar: () -> Unit = {},
    val onDescartarAviso: () -> Unit = {},
    /** FE-4.1: «Ver fotos» del menú ⋮ (abre la Galería filtrada por ese lugar). */
    val onVerFotos: (id: String) -> Unit = {},
)
