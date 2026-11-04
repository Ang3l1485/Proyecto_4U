package com.example.myapplication.domain.model

/**
 * Categorías de lugares.
 * [etiqueta] va en singular (fila de la lista); [etiquetaPlural], en el chip de filtro.
 */
enum class CategoriaLugar(val etiqueta: String, val etiquetaPlural: String) {
    BIBLIOTECA("Biblioteca", "Biblioteca"),
    CAFETERIA("Cafetería", "Cafetería"),
    BANO("Baño", "Baños"),
    BLOQUE("Bloque", "Bloques"),
    AUDITORIO("Auditorio", "Auditorios"),
    DEPORTES("Deportes", "Deportes"),
    ADMINISTRACION("Administración", "Administración"),
    ENTRADA("Entrada", "Entradas");

    companion object {
        /** Las que tienen chip propio en la vista 6.4; el resto va en el menú "Más". */
        val DESTACADAS: List<CategoriaLugar> = listOf(BIBLIOTECA, CAFETERIA, BANO, BLOQUE)
        val OTRAS: List<CategoriaLugar> = values().filter { it !in DESTACADAS }
    }
}

/**
 * Lugar del campus: el único modelo de lugar de la app (FE-3.4 lo unificó con el antiguo `Lugar` del editor de mapa).
 * Lo usan Selección de destino (6.4), el Resultado (6.3, `SesionDeNavegacion`), el editor de mapa (7.8) y, dentro de
 * [LugarAdmin], la lista y el formulario de lugares (7.6, 7.7).
 *
 * [alias] son otros nombres que la persona puede decir ("biblioteca", "los trillizos").
 * [distanciaMetros] es la distancia desde la posición actual; es null si aún no hay ubicación.
 * [imagenUrl] es la foto de referencia (URL o `file:///android_asset/...`); si es null se muestra un ícono.
 */
data class LugarDestino(
    val id: String,
    val nombre: String,
    val categoria: CategoriaLugar,
    val lat: Double,
    val lng: Double,
    val alias: List<String> = emptyList(),
    val distanciaMetros: Int? = null,
    val imagenUrl: String? = null,
)
