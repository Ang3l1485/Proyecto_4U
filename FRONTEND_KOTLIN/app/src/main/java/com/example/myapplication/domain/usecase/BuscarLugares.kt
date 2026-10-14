package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.LugarDestino
import java.text.Normalizer

/**
 * Coincidencia aproximada entre lo que dice la persona y los nombres de los lugares (vista 6.4).
 * Lógica pura (sin Android): ignora tildes, mayúsculas y muletillas ("quiero ir a la…").
 */
object BuscarLugares {

    private const val MINIMO = 0.70          // por debajo de esto no se considera coincidencia
    private const val MARGEN_EMPATE = 0.04   // lugares a menos de esto del mejor cuentan como empate
    private const val MAX_OPCIONES = 3
    private const val PENALIZACION_NOMBRE = 0.95 // un nombre parcial vale menos que un alias exacto

    private val MARCAS = Regex("\\p{Mn}+")
    private val NO_ALFANUMERICO = Regex("[^a-z0-9]+")

    private val RELLENO = setOf(
        "quiero", "ir", "a", "al", "la", "el", "los", "las", "de", "del", "un", "una",
        "llevame", "llevarme", "lleves", "vamos", "hacia", "hasta", "para", "por", "favor",
        "me", "en", "donde", "esta", "necesito", "busco", "buscar",
    )

    /** Minúsculas, sin tildes, solo letras y números, separado en palabras. */
    internal fun limpiar(texto: String): List<String> =
        Normalizer.normalize(texto.lowercase(), Normalizer.Form.NFD)
            .replace(MARCAS, "")
            .replace(NO_ALFANUMERICO, " ")
            .trim()
            .split(' ')
            .filter { it.isNotEmpty() }

    /** Como [limpiar], pero sin muletillas (salvo que no quede nada). */
    private fun claves(texto: String): List<String> {
        val todas = limpiar(texto)
        return todas.filter { it !in RELLENO }.ifEmpty { todas }
    }

    /**
     * Mejores coincidencias para lo dicho:
     *  - lista vacía: ningún lugar se parece;
     *  - un solo lugar: coincidencia clara;
     *  - 2 o 3 lugares: empate, hay que pedirle a la persona que elija.
     */
    fun mejores(consulta: String, lugares: List<LugarDestino>): List<LugarDestino> {
        val q = claves(consulta)
        if (q.isEmpty()) return emptyList()

        val puntuados = lugares
            .map { it to puntaje(q, it) }
            .filter { (_, p) -> p >= MINIMO }
            .sortedByDescending { (_, p) -> p }

        val mejor = puntuados.firstOrNull()?.second ?: return emptyList()
        return puntuados
            .filter { (_, p) -> p >= mejor - MARGEN_EMPATE }
            .take(MAX_OPCIONES)
            .map { it.first }
    }

    /** Filtro del buscador de la lista: cada palabra escrita debe aparecer en el nombre, alias o categoría. */
    fun filtrar(lugares: List<LugarDestino>, texto: String): List<LugarDestino> {
        val q = limpiar(texto)
        if (q.isEmpty()) return lugares
        return lugares.filter { lugar ->
            val palabras = limpiar((listOf(lugar.nombre, lugar.categoria.etiqueta) + lugar.alias).joinToString(" "))
            q.all { t -> palabras.any { it.contains(t) } }
        }
    }

    // --- Puntaje ------------------------------------------------------------

    private fun puntaje(q: List<String>, lugar: LugarDestino): Double {
        val consulta = q.joinToString(" ")
        var mejor = puntajeTexto(q, consulta, lugar.nombre, esAlias = false)
        for (alias in lugar.alias) {
            mejor = maxOf(mejor, puntajeTexto(q, consulta, alias, esAlias = true))
        }
        return mejor
    }

    private fun puntajeTexto(q: List<String>, consulta: String, candidato: String, esAlias: Boolean): Double {
        val c = claves(candidato)
        if (c.isEmpty()) return 0.0
        if (consulta == c.joinToString(" ")) return 1.0
        val promedio = q.sumOf { t -> c.maxOf { puntajeToken(t, it) } } / q.size
        return if (esAlias) promedio else promedio * PENALIZACION_NOMBRE
    }

    private fun puntajeToken(q: String, c: String): Double = when {
        q == c -> 1.0
        q.length >= 3 && c.startsWith(q) -> 0.9 // "cafe" -> "cafeteria"
        else -> {
            // Tolera errores del reconocimiento ("bibliotka").
            val similitud = 1.0 - distancia(q, c).toDouble() / maxOf(q.length, c.length)
            if (similitud >= 0.75) similitud * 0.9 else 0.0
        }
    }

    /** Distancia de Levenshtein (cuántas letras hay que cambiar para pasar de una palabra a otra). */
    private fun distancia(a: String, b: String): Int {
        var previa = IntArray(b.length + 1) { it }
        for (i in 1..a.length) {
            val actual = IntArray(b.length + 1)
            actual[0] = i
            for (j in 1..b.length) {
                val costo = if (a[i - 1] == b[j - 1]) 0 else 1
                actual[j] = minOf(actual[j - 1] + 1, previa[j] + 1, previa[j - 1] + costo)
            }
            previa = actual
        }
        return previa[b.length]
    }
}

enum class Respuesta { SI, NO, NINGUNA }

/** Interpreta un "sí" o un "no" dicho en voz alta (confirmación del destino). */
object InterpretarRespuesta {

    private val PALABRAS_SI = setOf(
        "si", "claro", "correcto", "dale", "ok", "okay", "vale", "confirmo",
        "afirmativo", "exacto", "listo", "vamos", "adelante",
    )
    private val PALABRAS_NO = setOf(
        "no", "nop", "nope", "cancela", "cancelar", "negativo", "incorrecto", "otro", "equivocado",
    )

    fun interpretar(texto: String): Respuesta {
        val palabras = BuscarLugares.limpiar(texto)
        val dicesSi = palabras.any { it in PALABRAS_SI }
        val dicesNo = palabras.any { it in PALABRAS_NO }
        return when {
            dicesSi && !dicesNo -> Respuesta.SI
            dicesNo && !dicesSi -> Respuesta.NO
            else -> Respuesta.NINGUNA
        }
    }
}
