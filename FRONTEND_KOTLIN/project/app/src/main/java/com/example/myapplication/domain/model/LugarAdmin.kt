package com.example.myapplication.domain.model

/**
 * Un lugar tal como lo ve la administración (FE-3.4): `LugarAdmin` de `GET /v1/admin/places` (backend §5.5).
 *
 * No es un segundo modelo de lugar: envuelve el [LugarDestino] (id, nombre, categoría, coordenada, alias e `imagenUrl`;
 * `distanciaMetros` siempre `null`) y añade lo que solo usan 7.6 y 7.7.
 * [descripcion] es el texto que se le lee a la persona; [referencias], cómo describir los alrededores; [totalFotos], las
 * fotos de videos no eliminados con este lugar (0 hasta que BE-4.1 asigne lugares a las fotos).
 */
data class LugarAdmin(
    val lugar: LugarDestino,
    val descripcion: String? = null,
    val referencias: String? = null,
    val totalFotos: Int = 0,
) {
    val id: String get() = lugar.id
    val nombre: String get() = lugar.nombre

    /** Los datos que se reenvían con `PUT /v1/admin/places/{id}` si no se cambia nada. */
    fun datos(): DatosLugar = DatosLugar(
        nombre = lugar.nombre,
        categoria = lugar.categoria,
        lat = lugar.lat,
        lng = lugar.lng,
        alias = lugar.alias,
        descripcion = descripcion,
        referencias = referencias,
    )
}

/**
 * Lo que la app envía al crear (`POST /v1/admin/places`) o reemplazar (`PUT /v1/admin/places/{id}`) un lugar:
 * `LugarEntrada` del backend §5.5. El `PUT` reemplaza **todos** los campos: lo que no se envía vuelve a su valor por
 * defecto (`alias` = `[]`, `descripcion` y `referencias` = `null`), así que para mover un lugar hay que reenviar el resto
 * ([LugarAdmin.datos]). Los límites los comprueba `FormularioLugar` antes de enviar.
 */
data class DatosLugar(
    val nombre: String,
    val categoria: CategoriaLugar,
    val lat: Double,
    val lng: Double,
    val alias: List<String> = emptyList(),
    val descripcion: String? = null,
    val referencias: String? = null,
)
