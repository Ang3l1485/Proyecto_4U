package com.example.myapplication.data.local

import com.example.myapplication.data.repository.EstadoAlertas
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParseException
import com.google.gson.JsonParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/** Dónde guarda el teléfono las alertas del editor y sus pendientes (FE-3.3, ADR-FE-33). */
interface AlmacenAlertas {
    /** Lo guardado; sin archivo, vacío. Nunca devuelve `cargado = false`. */
    suspend fun leer(): EstadoAlertas

    /** Reemplaza lo guardado (escritura atómica). Lanza `IOException` si no puede. */
    suspend fun guardar(estado: EstadoAlertas)
}

/**
 * [AlmacenAlertas] en un archivo JSON (`files/alertas/editor.json`), como los manifests de la recolección (ADR-FE-17,
 * ADR-FE-19): Gson, temporal `editor.json.tmp` + renombrar, sin dependencias nuevas y probado en la JVM
 * (`AlmacenAlertasTest`). Un archivo dañado se aparta como `editor.json.danado` (para revisarlo a mano) y se empieza
 * vacío; [registrar] lo anota.
 *
 * Forma (versión 1): `{"version": 1, "servidor": [Alerta…], "pendientes": [{"op": "upsert", "alerta": {…}} |
 * {"op": "eliminar", "id": "…"}], "rechazadas": ["…"]}` con cada alerta en las claves de [Alerta] (`radio`,
 * `vigencia_desde_ms`, `vigencia_hasta_ms`, `version`, `actualizado_en_ms`; las nulas se omiten).
 */
class AlmacenAlertasArchivo(
    private val archivo: File,
    private val registrar: (String) -> Unit = {},
) : AlmacenAlertas {

    override suspend fun leer(): EstadoAlertas = withContext(Dispatchers.IO) {
        if (!archivo.exists()) return@withContext EstadoAlertas(cargado = true)
        try {
            desdeJson(JsonParser.parseString(archivo.readText()).asJsonObject)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // JSON roto, claves que faltan o de otro tipo (Gson lanza IllegalStateException, NullPointerException…).
            val apartado = File(archivo.parentFile, "${archivo.name}.danado")
            apartado.delete()
            archivo.renameTo(apartado)
            registrar("Alertas: ${archivo.name} ilegible (${e.javaClass.simpleName}); se apartó y se empieza vacío")
            EstadoAlertas(cargado = true)
        }
    }

    override suspend fun guardar(estado: EstadoAlertas) {
        withContext(Dispatchers.IO) {
            archivo.parentFile?.mkdirs()
            val tmp = File(archivo.parentFile, "${archivo.name}.tmp")
            tmp.writeText(GSON.toJson(aJson(estado)))
            if (!tmp.renameTo(archivo)) {
                archivo.delete()
                if (!tmp.renameTo(archivo)) throw IOException("No se pudo guardar ${archivo.name}")
            }
        }
    }

    companion object {
        private val GSON = GsonBuilder().disableHtmlEscaping().create()
        const val VERSION = 1

        fun aJson(e: EstadoAlertas): JsonObject = JsonObject().apply {
            addProperty("version", VERSION)
            add("servidor", JsonArray().also { a -> e.servidor.forEach { a.add(alertaJson(it)) } })
            add("pendientes", JsonArray().also { a ->
                e.pendientes.forEach { op ->
                    a.add(JsonObject().apply {
                        when (op) {
                            is OperacionAlerta.Upsert -> { addProperty("op", "upsert"); add("alerta", alertaJson(op.alerta)) }
                            is OperacionAlerta.Eliminar -> { addProperty("op", "eliminar"); addProperty("id", op.id) }
                        }
                    })
                }
            })
            add("rechazadas", JsonArray().also { a -> e.rechazadas.forEach { a.add(it) } })
        }

        fun desdeJson(o: JsonObject): EstadoAlertas = EstadoAlertas(
            servidor = o.getAsJsonArray("servidor")?.map { alertaDe(it.asJsonObject) }.orEmpty(),
            pendientes = o.getAsJsonArray("pendientes")?.map { el ->
                val p = el.asJsonObject
                when (val op = p.get("op").asString) {
                    "upsert" -> OperacionAlerta.Upsert(alertaDe(p.getAsJsonObject("alerta")))
                    "eliminar" -> OperacionAlerta.Eliminar(p.get("id").asString)
                    else -> throw JsonParseException("op desconocida: $op")
                }
            }.orEmpty(),
            rechazadas = o.getAsJsonArray("rechazadas")?.mapTo(LinkedHashSet()) { it.asString }.orEmpty(),
            cargado = true,
        )

        /** Una alerta en las claves del archivo (también las usa la caché pública de FE-3.6, `AlmacenCacheAlertasArchivo`). */
        internal fun alertaJson(a: Alerta) = JsonObject().apply {
            addProperty("id", a.id)
            addProperty("lat", a.lat)
            addProperty("lng", a.lng)
            addProperty("mensaje", a.mensaje)
            addProperty("tipo", a.tipo)
            addProperty("prioridad", a.prioridad)
            addProperty("radio", a.radio)
            addProperty("activa", a.activa)
            a.vigenciaDesdeMs?.let { addProperty("vigencia_desde_ms", it) }
            a.vigenciaHastaMs?.let { addProperty("vigencia_hasta_ms", it) }
            a.version?.let { addProperty("version", it) }
            a.actualizadoEnMs?.let { addProperty("actualizado_en_ms", it) }
        }

        internal fun alertaDe(o: JsonObject): Alerta = Alerta(
            id = o.get("id").asString,
            lat = o.get("lat").asDouble,
            lng = o.get("lng").asDouble,
            mensaje = o.get("mensaje").asString,
            tipo = o.texto("tipo") ?: "otro",
            prioridad = o.texto("prioridad") ?: "normal",
            radio = o.get("radio")?.takeUnless { it.isJsonNull }?.asInt ?: 15,
            activa = o.get("activa")?.takeUnless { it.isJsonNull }?.asBoolean ?: true,
            vigenciaDesdeMs = o.largo("vigencia_desde_ms"),
            vigenciaHastaMs = o.largo("vigencia_hasta_ms"),
            version = o.get("version")?.takeUnless { it.isJsonNull }?.asInt,
            actualizadoEnMs = o.largo("actualizado_en_ms"),
        )

        private fun JsonObject.texto(clave: String): String? = get(clave)?.takeUnless(JsonElement::isJsonNull)?.asString
        private fun JsonObject.largo(clave: String): Long? = get(clave)?.takeUnless(JsonElement::isJsonNull)?.asLong
    }
}

/** [AlmacenAlertas] en memoria, para pruebas y vistas previas. */
class AlmacenAlertasMemoria(var guardado: EstadoAlertas = EstadoAlertas(cargado = true)) : AlmacenAlertas {
    var escrituras = 0
        private set

    override suspend fun leer(): EstadoAlertas = guardado.copy(cargado = true)

    override suspend fun guardar(estado: EstadoAlertas) {
        guardado = estado
        escrituras++
    }
}
