package com.example.myapplication.data.local

import com.example.myapplication.domain.model.Alerta
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/**
 * Caché local de las alertas públicas (FE-3.6, ARCHITECTURE §5.10 «Alertas sin conexión», ADR-FE-40): las activas de
 * `GET /v1/alerts` y el `generado_en` de la última respuesta (el `desde` de la siguiente, **tal cual** llegó). No es el
 * almacén del editor (FE-3.3), que guarda también inactivas y pendientes. [cargada] = ya se leyó el disco.
 */
data class CachePublica(
    val alertas: List<Alerta> = emptyList(),
    val generadoEn: String? = null,
    val cargada: Boolean = false,
)

/** Dónde se guarda la [CachePublica]. */
interface AlmacenCacheAlertas {
    /** Lo guardado; sin archivo, vacía. Siempre con `cargada = true`. */
    suspend fun leer(): CachePublica

    /** Reemplaza lo guardado (escritura atómica). Lanza `IOException` si no puede. */
    suspend fun guardar(cache: CachePublica)
}

/**
 * [AlmacenCacheAlertas] en `files/alertas/publicas.json`, con el patrón de [AlmacenAlertasArchivo] (ADR-FE-33): Gson,
 * temporal `.tmp` + renombrar; un archivo ilegible se aparta como `publicas.json.danado`, se anota con [registrar] y se
 * empieza vacío (la siguiente sincronización pide la foto completa).
 *
 * Forma (versión 1): `{"version": 1, "generado_en": "2026-10-28T15:04:05Z", "alertas": [Alerta…]}` con cada alerta en
 * las claves del editor (`id`, `lat`, `lng`, `mensaje`, `tipo`, `prioridad`, `radio`, `activa` y, si no son nulas,
 * `vigencia_desde_ms`, `vigencia_hasta_ms`, `version`, `actualizado_en_ms`). `generado_en` se omite si es nulo.
 */
class AlmacenCacheAlertasArchivo(
    private val archivo: File,
    private val registrar: (String) -> Unit = {},
) : AlmacenCacheAlertas {

    override suspend fun leer(): CachePublica = withContext(Dispatchers.IO) {
        if (!archivo.exists()) return@withContext CachePublica(cargada = true)
        try {
            desdeJson(JsonParser.parseString(archivo.readText()).asJsonObject)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val apartado = File(archivo.parentFile, "${archivo.name}.danado")
            apartado.delete()
            archivo.renameTo(apartado)
            registrar("Alertas públicas: ${archivo.name} ilegible (${e.javaClass.simpleName}); se apartó y se empieza vacío")
            CachePublica(cargada = true)
        }
    }

    override suspend fun guardar(cache: CachePublica) {
        withContext(Dispatchers.IO) {
            archivo.parentFile?.mkdirs()
            val tmp = File(archivo.parentFile, "${archivo.name}.tmp")
            tmp.writeText(GSON.toJson(aJson(cache)))
            if (!tmp.renameTo(archivo)) {
                archivo.delete()
                if (!tmp.renameTo(archivo)) throw IOException("No se pudo guardar ${archivo.name}")
            }
        }
    }

    companion object {
        private val GSON = GsonBuilder().disableHtmlEscaping().create()
        const val VERSION = 1

        /** En la app: `files/alertas/publicas.json`. */
        const val NOMBRE = "publicas.json"

        fun aJson(c: CachePublica): JsonObject = JsonObject().apply {
            addProperty("version", VERSION)
            c.generadoEn?.let { addProperty("generado_en", it) }
            add("alertas", JsonArray().also { a -> c.alertas.forEach { a.add(AlmacenAlertasArchivo.alertaJson(it)) } })
        }

        fun desdeJson(o: JsonObject): CachePublica = CachePublica(
            alertas = o.getAsJsonArray("alertas")!!.map { AlmacenAlertasArchivo.alertaDe(it.asJsonObject) },
            generadoEn = o.get("generado_en")?.takeUnless { it.isJsonNull }?.asString,
            cargada = true,
        )
    }
}

/** [AlmacenCacheAlertas] en memoria, para pruebas. */
class AlmacenCacheAlertasMemoria(var guardada: CachePublica = CachePublica(cargada = true)) : AlmacenCacheAlertas {
    var escrituras = 0
        private set

    override suspend fun leer(): CachePublica = guardada.copy(cargada = true)

    override suspend fun guardar(cache: CachePublica) {
        guardada = cache
        escrituras++
    }
}

/**
 * Cómo se aplica una respuesta de `GET /v1/alerts` a la caché (backend §4.11, «Para la app», y §5.3). Lógica pura
 * (`CacheAlertasPublicasTest`).
 */
object ReglasCacheAlertas {
    /**
     * [completo] → la caché pasa a ser [alertas] (solo las activas, sin ids repetidos). Si no (diferencias): cada alerta
     * reemplaza por `id` a la que había (o se añade al final) si está activa, o la quita si llega con `activa = false`, y
     * se quitan los ids de [eliminadas] (pueden no estar). Repetir una diferencia ya aplicada (margen de 60 s del
     * backend) no cambia nada.
     */
    fun aplicar(actual: List<Alerta>, completo: Boolean, alertas: List<Alerta>, eliminadas: Collection<String>): List<Alerta> {
        if (completo) return alertas.filter { it.activa }.distinctBy { it.id }
        val porId = LinkedHashMap<String, Alerta>()
        actual.forEach { porId[it.id] = it }
        for (a in alertas) {
            if (a.activa) porId[a.id] = a else porId.remove(a.id)
        }
        eliminadas.forEach { porId.remove(it) }
        return porId.values.toList()
    }
}
