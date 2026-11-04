package com.example.myapplication.ui.admin.lugares

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.DatosLugar
import com.example.myapplication.domain.model.LugarAdmin
import java.util.Locale

/** Lo que la persona escribió o eligió en el formulario 7.7, sin validar. */
data class CamposLugar(
    val nombre: String = "",
    /** Alias separados por comas (o saltos de línea), como se escriben en el campo. */
    val aliasTexto: String = "",
    val descripcion: String = "",
    val categoria: CategoriaLugar? = null,
    /** `(lat, lng)` ya redondeado a [FormularioLugar.DECIMALES]; `null` hasta tocar el mapa. */
    val punto: Pair<Double, Double>? = null,
    val referencias: String = "",
)

/** Un mensaje por campo del formulario (`null` = sin error) y uno general (sin red, lugar borrado, «Algo salió mal»). */
data class ErroresLugar(
    val nombre: String? = null,
    val alias: String? = null,
    val descripcion: String? = null,
    val categoria: String? = null,
    val punto: String? = null,
    val referencias: String? = null,
    val general: String? = null,
) {
    val hay: Boolean
        get() = listOf(nombre, alias, descripcion, categoria, punto, referencias, general).any { it != null }

    companion object {
        val NINGUNO = ErroresLugar()
    }
}

/**
 * Reglas del formulario de lugar (FE-3.4; lógica pura, se prueba en `FormularioLugarTest`). Los límites son los de
 * `LugarEntrada` del backend (§5.5; BE-3.1: `NOMBRE_MIN`, `NOMBRE_MAX`, `ALIAS_MAX_ELEMENTOS`, `ALIAS_MAX`,
 * `DESCRIPCION_MAX`, contados **tras recortar**). La unicidad del nombre **no** se comprueba aquí: la decide el backend
 * (`409 NOMBRE_DUPLICADO`, [ErroresLugar] de `ErroresLugarMapeo`), que es quien normaliza los nombres.
 */
internal object FormularioLugar {
    const val NOMBRE_MIN = 2
    const val NOMBRE_MAX = 80
    const val ALIAS_MAX_ELEMENTOS = 20
    const val ALIAS_MAX = 60
    const val TEXTO_MAX = 300

    /** Decimales de la coordenada que se muestra y se envía (~0,11 m): lo que se ve es exactamente lo que se guarda. */
    const val DECIMALES = 6

    const val SIN_PUNTO = "Punto: sin elegir (toca el mapa)"

    const val ERROR_NOMBRE_CORTO = "Escribe un nombre de al menos $NOMBRE_MIN caracteres."
    const val ERROR_NOMBRE_LARGO = "Máximo $NOMBRE_MAX caracteres."
    const val ERROR_CATEGORIA = "Elige una categoría."
    const val ERROR_PUNTO = "Toca el mapa para elegir el punto de llegada."
    const val ERROR_ALIAS_MUCHOS = "Máximo $ALIAS_MAX_ELEMENTOS alias."
    const val ERROR_ALIAS_LARGO = "Cada alias puede tener hasta $ALIAS_MAX caracteres."
    const val ERROR_TEXTO_LARGO = "Máximo $TEXTO_MAX caracteres."

    /** Grados a [DECIMALES] decimales (medio hacia arriba). */
    fun redondear(grados: Double): Double = Math.round(grados * 1_000_000.0) / 1_000_000.0

    /** «6.200512, -75.578311»: siempre con punto decimal ([Locale.ROOT]), sea cual sea el idioma del teléfono. */
    fun textoCoordenada(lat: Double, lng: Double): String = String.format(Locale.ROOT, "%.6f, %.6f", lat, lng)

    /** Texto fijo del pie del formulario: «Punto: 6.200512, -75.578311» o [SIN_PUNTO]. Lo lee `validate34.py`. */
    fun textoPunto(punto: Pair<Double, Double>?): String =
        punto?.let { "Punto: " + textoCoordenada(it.first, it.second) } ?: SIN_PUNTO

    /** Alias del campo de texto: separados por comas o saltos de línea, recortados, sin vacíos ni repetidos
     *  (sin distinguir mayúsculas; se queda el primero). */
    fun aliasDeTexto(texto: String): List<String> {
        val vistos = mutableSetOf<String>()
        return texto.split(',', '\n')
            .map { it.trim() }
            .filter { it.isNotEmpty() && vistos.add(it.lowercase(Locale.ROOT)) }
    }

    fun textoDeAlias(alias: List<String>): String = alias.joinToString(", ")

    /** Errores de los campos antes de enviar ([ErroresLugar.NINGUNO] si se puede guardar). */
    fun validar(c: CamposLugar): ErroresLugar {
        val nombre = c.nombre.trim()
        val alias = aliasDeTexto(c.aliasTexto)
        return ErroresLugar(
            nombre = when {
                nombre.length < NOMBRE_MIN -> ERROR_NOMBRE_CORTO
                nombre.length > NOMBRE_MAX -> ERROR_NOMBRE_LARGO
                else -> null
            },
            alias = when {
                alias.size > ALIAS_MAX_ELEMENTOS -> ERROR_ALIAS_MUCHOS
                alias.any { it.length > ALIAS_MAX } -> ERROR_ALIAS_LARGO
                else -> null
            },
            descripcion = if (c.descripcion.trim().length > TEXTO_MAX) ERROR_TEXTO_LARGO else null,
            categoria = if (c.categoria == null) ERROR_CATEGORIA else null,
            punto = if (c.punto == null) ERROR_PUNTO else null,
            referencias = if (c.referencias.trim().length > TEXTO_MAX) ERROR_TEXTO_LARGO else null,
        )
    }

    /** Lo que se envía al backend, o `null` si [validar] da algún error. Textos recortados; vacíos → `null`. */
    fun datos(c: CamposLugar): DatosLugar? {
        if (validar(c).hay) return null
        val punto = c.punto ?: return null
        val categoria = c.categoria ?: return null
        return DatosLugar(
            nombre = c.nombre.trim(),
            categoria = categoria,
            lat = redondear(punto.first),
            lng = redondear(punto.second),
            alias = aliasDeTexto(c.aliasTexto),
            descripcion = c.descripcion.trim().ifEmpty { null },
            referencias = c.referencias.trim().ifEmpty { null },
        )
    }

    /** Los campos de un lugar guardado, para editarlo en 7.7. */
    fun campos(l: LugarAdmin): CamposLugar = CamposLugar(
        nombre = l.lugar.nombre,
        aliasTexto = textoDeAlias(l.lugar.alias),
        descripcion = l.descripcion.orEmpty(),
        categoria = l.lugar.categoria,
        punto = redondear(l.lugar.lat) to redondear(l.lugar.lng),
        referencias = l.referencias.orEmpty(),
    )
}
