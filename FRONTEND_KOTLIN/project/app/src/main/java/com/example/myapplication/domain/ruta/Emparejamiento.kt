package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.model.LugarDestino
import java.text.Normalizer
import java.util.Locale

/**
 * Un lugar del backend visto desde el grafo: [punto] es la proyección de sus coordenadas sobre la arista usable más
 * cercana (la meta de una ruta hacia él), o `null` si sus coordenadas no son válidas o el grafo no tiene aristas usables;
 * [lejos] = queda a más de [ParametrosRuta.fueraDelCaminoM] del grafo (la ruta llega al punto más cercano y la llegada
 * dice cuánto falta en línea recta).
 */
data class LugarEnGrafo(val lugar: LugarDestino, val punto: PuntoEnArista?, val lejos: Boolean)

/**
 * Empareja los lugares del backend con el grafo **por coordenadas** (FE-5.1, decisión del usuario del 2026-10-28; los
 * nombres de `lugar` del grafo son informativos). `EmparejamientoTest`.
 */
object EmparejarLugares {

    private val marcas = Regex("\\p{M}+")
    private val noAlfanumerico = Regex("[^a-z0-9]+")

    /**
     * Minúsculas, sin tildes y **solo letras y números** («Café Con.verso» → `cafeconverso`, «bloque 35» → `bloque35`).
     * La usa el destino de prueba por nombre del mapa (`Planificador.nodoConLugar`).
     */
    fun normalizar(texto: String): String =
        Normalizer.normalize(texto.lowercase(Locale.ROOT), Normalizer.Form.NFD)
            .replace(marcas, "")
            .replace(noAlfanumerico, "")

    /** Cada lugar con su punto más cercano en el grafo, en el orden de [lugares]. */
    fun emparejar(grafo: Grafo, lugares: List<LugarDestino>, p: ParametrosRuta = ParametrosRuta()): List<LugarEnGrafo> =
        lugares.map { l ->
            val valida = l.lat.isFinite() && l.lng.isFinite() && l.lat in -90.0..90.0 && l.lng in -180.0..180.0
            val punto = if (valida) Proyeccion.masCercana(grafo, l.lat, l.lng) else null
            LugarEnGrafo(l, punto, punto != null && punto.distanciaM > p.fueraDelCaminoM)
        }
}
