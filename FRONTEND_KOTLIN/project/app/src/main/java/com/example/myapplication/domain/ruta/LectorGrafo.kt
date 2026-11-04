package com.example.myapplication.domain.ruta

import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/** Resultado de leer `grafo.json`: un grafo válido (con avisos que no lo invalidan) o la lista de errores. */
sealed interface CargaGrafo {
    data class Valido(val grafo: Grafo, val avisos: List<String> = emptyList()) : CargaGrafo
    data class Invalido(val errores: List<String>) : CargaGrafo
}

/**
 * Lee y valida `grafo.json` (formato 1; FE-5.1, ARCHITECTURE §5.7, «Grafo y rutas»). Lógica pura (Gson, sin Android):
 * la prueba `LectorGrafoTest`. Nunca lanza: un archivo roto o inválido da [CargaGrafo.Invalido] y la app desactiva las
 * rutas (lo registra `GrafoDeLaApp`).
 *
 * **Invalida el grafo:** JSON roto o que no es un objeto; `formato` distinto de [FORMATO]; sin `version` entera; sin
 * listas `nodos` o `aristas`; un nodo sin `id`, `lat`/`lng` numéricos (y en rango) o `tipo`; una arista sin `id`, `a` o
 * `b`; ids de nodo o de arista repetidos; una arista a un nodo inexistente o de un nodo a sí mismo; más de un
 * componente conexo (contando todas las aristas, también las bloqueadas: un nodo aislado es un componente).
 *
 * **Solo avisa:** un `tipo` de nodo que no es `cruce` ni `entrada`; `metros` ausente o ≤ 0 (se usa la distancia entre
 * los nodos). `lugar` es **opcional e informativo** en cualquier nodo (decisión del usuario del 2026-10-28: la meta de
 * una ruta sale de las coordenadas del destino, no del nombre): no se exige ni se comprueba. `contadores` (los
 * siguientes ids libres del editor que generó el archivo, no totales) se ignora.
 */
object LectorGrafo {

    const val FORMATO = 1

    fun leer(texto: String): CargaGrafo {
        val raiz: JsonElement = try {
            JsonParser.parseString(texto)
        } catch (e: Exception) {
            return CargaGrafo.Invalido(listOf("JSON ilegible (${e.javaClass.simpleName})"))
        }
        if (!raiz.isJsonObject) return CargaGrafo.Invalido(listOf("la raíz no es un objeto JSON"))
        val o = raiz.asJsonObject
        val errores = mutableListOf<String>()
        val avisos = mutableListOf<String>()

        val formato = entero(o, "formato")
        if (formato != FORMATO) errores += "formato ${formato ?: "ausente"} (se espera $FORMATO)"
        val version = entero(o, "version")
        if (version == null) errores += "sin version entera"
        val actualizado = texto(o, "actualizado")
        val nodosJson = o.get("nodos")?.takeIf { it.isJsonArray }?.asJsonArray
        val aristasJson = o.get("aristas")?.takeIf { it.isJsonArray }?.asJsonArray
        if (nodosJson == null) errores += "sin lista «nodos»"
        if (aristasJson == null) errores += "sin lista «aristas»"
        if (errores.isNotEmpty()) return CargaGrafo.Invalido(errores)

        val nodos = mutableListOf<Nodo>()
        nodosJson!!.forEachIndexed { i, el ->
            val n = el.takeIf { it.isJsonObject }?.asJsonObject
            val id = n?.let { texto(it, "id") }
            val lat = n?.let { numero(it, "lat") }
            val lng = n?.let { numero(it, "lng") }
            val tipo = n?.let { texto(it, "tipo") }
            if (n == null || id.isNullOrBlank() || lat == null || lng == null || tipo.isNullOrBlank()) {
                errores += "nodo #$i sin id, lat, lng o tipo"
                return@forEachIndexed
            }
            if (lat !in -90.0..90.0 || lng !in -180.0..180.0) errores += "nodo $id con coordenadas fuera de rango"
            if (tipo != TiposNodo.CRUCE && tipo != TiposNodo.ENTRADA) avisos += "nodo $id de tipo desconocido «$tipo»"
            val lugar = texto(n, "lugar")?.trim()?.takeIf { it.isNotEmpty() }
            nodos += Nodo(id, lat, lng, tipo, lugar)
        }

        val porId = nodos.associateBy { it.id }
        val aristas = mutableListOf<Arista>()
        aristasJson!!.forEachIndexed { i, el ->
            val a = el.takeIf { it.isJsonObject }?.asJsonObject
            val id = a?.let { texto(it, "id") }
            val desde = a?.let { texto(it, "a") }
            val hasta = a?.let { texto(it, "b") }
            if (a == null || id.isNullOrBlank() || desde.isNullOrBlank() || hasta.isNullOrBlank()) {
                errores += "arista #$i sin id, a o b"
                return@forEachIndexed
            }
            var metros = numero(a, "metros")
            val na = porId[desde]
            val nb = porId[hasta]
            if (metros == null || metros <= 0.0) {
                if (na != null && nb != null) {
                    metros = Geo.distancia(na.lat, na.lng, nb.lat, nb.lng)
                    avisos += "arista $id sin metros válidos: se usa la distancia entre sus nodos"
                } else {
                    metros = 0.0
                }
            }
            aristas += Arista(
                id = id,
                a = desde,
                b = hasta,
                metros = metros,
                tipo = texto(a, "tipo") ?: "camino",
                accesible = booleano(a, "accesible") ?: true,
                bloqueada = booleano(a, "bloqueada") ?: false,
            )
        }

        errores += validar(nodos, aristas)
        if (errores.isNotEmpty()) return CargaGrafo.Invalido(errores)
        return CargaGrafo.Valido(Grafo(formato!!, version!!, actualizado, nodos, aristas), avisos)
    }

    /**
     * Las reglas de estructura (ids repetidos, aristas a nodos inexistentes o a sí mismas, más de un componente).
     * Lista vacía = válido.
     */
    fun validar(nodos: List<Nodo>, aristas: List<Arista>): List<String> {
        val errores = mutableListOf<String>()
        repetidos(nodos.map { it.id }).forEach { errores += "id de nodo repetido: $it" }
        repetidos(aristas.map { it.id }).forEach { errores += "id de arista repetido: $it" }
        val ids = nodos.map { it.id }.toSet()
        for (ar in aristas) {
            if (ar.a !in ids) errores += "arista ${ar.id}: nodo inexistente ${ar.a}"
            if (ar.b !in ids) errores += "arista ${ar.id}: nodo inexistente ${ar.b}"
            if (ar.a == ar.b) errores += "arista ${ar.id} une un nodo consigo mismo"
        }
        if (nodos.isEmpty()) errores += "sin nodos"
        val comps = componentes(nodos, aristas)
        if (comps.size > 1) {
            val aislados = comps.drop(1).flatten().sorted()
            errores += "el grafo tiene ${comps.size} componentes; fuera del principal: ${aislados.take(10).joinToString()}" +
                if (aislados.size > 10) " (y ${aislados.size - 10} más)" else ""
        }
        return errores
    }

    /**
     * Componentes conexos (todas las aristas, también las bloqueadas; se ignoran las que apuntan a nodos inexistentes),
     * el más grande primero.
     */
    fun componentes(nodos: List<Nodo>, aristas: List<Arista>): List<Set<String>> {
        val ids = nodos.map { it.id }.toSet()
        val vecinos = HashMap<String, MutableList<String>>()
        for (ar in aristas) {
            if (ar.a !in ids || ar.b !in ids) continue
            vecinos.getOrPut(ar.a) { mutableListOf() }.add(ar.b)
            vecinos.getOrPut(ar.b) { mutableListOf() }.add(ar.a)
        }
        val visto = HashSet<String>()
        val resultado = mutableListOf<Set<String>>()
        for (n in nodos) {
            if (!visto.add(n.id)) continue
            val comp = linkedSetOf(n.id)
            val pila = ArrayDeque(listOf(n.id))
            while (pila.isNotEmpty()) {
                val actual = pila.removeLast()
                for (v in vecinos[actual].orEmpty()) {
                    if (visto.add(v)) {
                        comp += v
                        pila.addLast(v)
                    }
                }
            }
            resultado += comp
        }
        return resultado.sortedByDescending { it.size }
    }

    private fun repetidos(ids: List<String>): List<String> =
        ids.groupingBy { it }.eachCount().filter { it.value > 1 }.keys.sorted()

    private fun primitivo(o: JsonObject, clave: String) =
        o.get(clave)?.takeIf { it.isJsonPrimitive }?.asJsonPrimitive

    private fun texto(o: JsonObject, clave: String): String? =
        primitivo(o, clave)?.takeIf { it.isString }?.asString

    private fun numero(o: JsonObject, clave: String): Double? =
        primitivo(o, clave)?.takeIf { it.isNumber }?.asDouble?.takeIf { it.isFinite() }

    private fun entero(o: JsonObject, clave: String): Int? =
        numero(o, clave)?.takeIf { it == Math.floor(it) && it in Int.MIN_VALUE.toDouble()..Int.MAX_VALUE.toDouble() }
            ?.toInt()

    private fun booleano(o: JsonObject, clave: String): Boolean? =
        primitivo(o, clave)?.takeIf { it.isBoolean }?.asBoolean
}
