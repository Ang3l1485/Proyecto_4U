package com.example.myapplication.domain.model

/**
 * Respuesta `200` de `POST /v1/localize/frame` (backend §5.3; FE-5.3). [radioBusquedaM]: el radio usado;
 * [imagenesEnRadio]: cuántas imágenes del dataset había en él (0 = esa zona no tiene dataset).
 */
sealed interface ResultadoFrame {
    val radioBusquedaM: Double
    val imagenesEnRadio: Int

    /**
     * `resultado = ok`: la posición de la foto ([lat], [lng], dispersión [radioM]), [confianza] y [nivel] (los del
     * backend, sin recalcular) y [distanciaPreviaM] = de la `posicion_previa` enviada a esa posición.
     */
    data class Ubicado(
        val lat: Double,
        val lng: Double,
        val radioM: Double,
        val confianza: Double,
        val nivel: NivelConfianza,
        val distanciaPreviaM: Double,
        override val radioBusquedaM: Double,
        override val imagenesEnRadio: Int,
    ) : ResultadoFrame

    /** `resultado = sin_coincidencias`: no es un error; la guía sigue con los pasos. */
    data class SinCoincidencias(
        override val radioBusquedaM: Double,
        override val imagenesEnRadio: Int,
    ) : ResultadoFrame
}
