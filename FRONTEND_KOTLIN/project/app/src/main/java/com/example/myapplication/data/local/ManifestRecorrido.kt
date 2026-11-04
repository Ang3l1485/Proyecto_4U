package com.example.myapplication.data.local

import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.PuntoRecorrido
import com.example.myapplication.domain.model.Video
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.IOException
import java.util.Locale

/** El `manifest.json` no se puede leer (no existe, JSON roto o falta un campo obligatorio). No es un fallo de red. */
class ManifestException(mensaje: String, causa: Throwable? = null) : IOException(mensaje, causa)

/**
 * Parser **compartido** del `manifest.json` (FE-2.1, ARCHITECTURE §5.6): lo usan `AlmacenRecorridos` (y con él la cola
 * de subida, 7.5 y, desde FE-4.1, el `VideoRepository` compuesto de 7.13/7.14) sobre `files/recoleccion/`. Lógica pura
 * con Gson (no `org.json`, que en la JVM son *stubs*): se prueba en `AlmacenRecorridosTest`. Desde FE-4.1 no hay
 * `assets/videos/` ni `AssetsVideoRepository`: [video] (el formato de esos assets) queda sin uso en la app y solo lo
 * prueba `AlmacenRecorridosTest` (quitarlo con su prueba es de FE-4.3).
 *
 * Claves por foto: `id`, `file`, `lat`, `lng` (obligatorias), `thumb`, `heading`, `captured_at`, `lugar`, `estado`,
 * `calidad`, `sync`, `error` y `upload` (`{bytes, width, height}`). Por video: `name`, `created_at`, `estado`,
 * `start_lat`, `start_lng`, `start_heading`, `ended_at`, `duration_s`, `distance_m`, `steps`, `progress.track`,
 * `remote_video_id` y `subida_estado`.
 */
object ManifestRecorrido {

    // Claves que añade FE-2.1 (las demás son de 7.4 y FE-2.3; formato completo en ARCHITECTURE §5.6).
    const val VIDEO_REMOTO = "remote_video_id"
    const val SUBIDA_ESTADO = "subida_estado"
    const val SYNC = "sync"
    const val SYNC_PENDIENTE = "pendiente"
    const val SYNC_SUBIDA = "subida"
    const val ESTADO = "estado"
    const val ERROR = "error"
    const val UPLOAD = "upload"
    const val ESTADO_FINALIZADO = "finalizado"

    private val gson = GsonBuilder().disableHtmlEscaping().create()

    /** Texto → objeto JSON; vacío, roto o que no es un objeto → [ManifestException]. */
    fun parsear(texto: String): JsonObject = try {
        JsonParser.parseString(texto).takeIf { it.isJsonObject }?.asJsonObject
            ?: throw ManifestException("el manifest no es un objeto JSON")
    } catch (e: RuntimeException) {
        throw ManifestException("manifest dañado", e)
    }

    /** Objeto → texto (sin escapar `<`, `>`, `=` como hace Gson por defecto; los números se conservan tal cual). */
    fun texto(json: JsonObject): String = gson.toJson(json)

    /**
     * Estado de una foto para mostrar: el `estado` del manifest si se reconoce (`pendiente`/`pendiente_subida`,
     * `subida`, `procesada`, `error`, sin distinguir mayúsculas); si no, `sync` (`pendiente` → `PENDIENTE`, `subida` →
     * `SUBIDA`); si no hay ninguno, `PROCESADA` (lo que asumía `assets/videos/`).
     */
    fun estadoFoto(foto: JsonObject): EstadoFoto {
        val estado = foto.texto(ESTADO)?.lowercase(Locale.ROOT)
        val porEstado = when (estado) {
            "pendiente", "pendiente_subida" -> EstadoFoto.PENDIENTE
            "subida" -> EstadoFoto.SUBIDA
            "procesada" -> EstadoFoto.PROCESADA
            "error" -> EstadoFoto.ERROR
            else -> null
        }
        return porEstado ?: when (foto.texto(SYNC)) {
            SYNC_PENDIENTE -> EstadoFoto.PENDIENTE
            SYNC_SUBIDA -> EstadoFoto.SUBIDA
            else -> EstadoFoto.PROCESADA
        }
    }

    /**
     * Manifest de `assets/videos/<videoId>/` (o de cualquier carpeta) → [Video]. [url] convierte una ruta relativa a la
     * carpeta en URL; [miniaturaExiste] decide si `thumb` se usa (si no, la miniatura es la foto original). Fotos
     * ordenadas por `id` como texto. Falta un campo obligatorio → [ManifestException].
     */
    fun video(
        videoId: String,
        json: JsonObject,
        url: (rutaRelativa: String) -> String,
        miniaturaExiste: (rutaRelativa: String) -> Boolean = { false },
    ): Video {
        val nombre = json.texto("name")?.takeIf { it.isNotBlank() } ?: videoId
        val fotos = fotos(json).map { p ->
            val archivo = p.obligatorio("file")
            val miniatura = p.texto("thumb")?.takeIf { it.isNotEmpty() && miniaturaExiste(it) } ?: archivo
            Foto(
                id = p.obligatorio("id"),
                videoId = videoId,
                videoNombre = nombre,
                urlFoto = url(archivo),
                urlMiniatura = url(miniatura),
                lat = p.numero("lat") ?: throw ManifestException("falta lat en una foto de $videoId"),
                lng = p.numero("lng") ?: throw ManifestException("falta lng en una foto de $videoId"),
                rumbo = p.numero("heading")?.toFloat(),
                capturadaEn = p.texto("captured_at")?.ifBlank { null },
                lugar = p.texto("lugar")?.ifBlank { null },
                estado = estadoFoto(p),
                calidad = CalidadFoto.entries.firstOrNull { it.name.equals(p.texto("calidad"), ignoreCase = true) }
                    ?: CalidadFoto.NORMAL,
            )
        }.sortedBy { it.id }
        return Video(id = videoId, nombre = nombre, creadoEn = json.texto("created_at")?.ifBlank { null }, fotos = fotos)
    }

    /** Manifest de `files/recoleccion/<videoId>/` → [RecorridoLocal]. Fotos en el orden del manifest. */
    fun recorrido(videoId: String, json: JsonObject): RecorridoLocal = RecorridoLocal(
        id = videoId,
        nombre = json.texto("name")?.takeIf { it.isNotBlank() } ?: videoId,
        creadoEn = json.texto("created_at")?.ifBlank { null },
        finalizadoEn = json.texto("ended_at")?.ifBlank { null },
        finalizado = json.texto(ESTADO) == ESTADO_FINALIZADO,
        inicioLat = json.numero("start_lat"),
        inicioLng = json.numero("start_lng"),
        inicioRumbo = json.numero("start_heading"),
        duracionSegundos = json.numero("duration_s")?.toLong(),
        distanciaMetros = json.numero("distance_m"),
        pasos = json.numero("steps")?.toInt(),
        fotos = fotos(json).map { p ->
            FotoLocal(
                id = p.obligatorio("id"),
                archivo = p.obligatorio("file"),
                lat = p.numero("lat") ?: throw ManifestException("falta lat en una foto de $videoId"),
                lng = p.numero("lng") ?: throw ManifestException("falta lng en una foto de $videoId"),
                rumbo = p.numero("heading"),
                capturadaEn = p.texto("captured_at")?.ifBlank { null },
                subida = p.texto(SYNC) == SYNC_SUBIDA,
                estado = estadoFoto(p),
                error = p.texto(ERROR)?.ifBlank { null },
                preparada = p.objeto(UPLOAD)?.let { u ->
                    val bytes = u.numero("bytes")?.toLong()
                    val ancho = u.numero("width")?.toInt()
                    val alto = u.numero("height")?.toInt()
                    if (bytes != null && ancho != null && alto != null) FotoPreparada(bytes, ancho, alto) else null
                },
            )
        },
        trayectoria = json.objeto("progress")?.get("track")?.takeIf { it.isJsonArray }?.asJsonArray
            ?.mapNotNull { punto ->
                val par = punto.takeIf { it.isJsonArray }?.asJsonArray ?: return@mapNotNull null
                if (par.size() < 2) return@mapNotNull null
                val lat = par[0].comoNumero() ?: return@mapNotNull null
                val lng = par[1].comoNumero() ?: return@mapNotNull null
                PuntoRecorrido(lat, lng)
            }.orEmpty(),
        remoteVideoId = json.texto(VIDEO_REMOTO)?.ifBlank { null },
        subida = EstadoSubida.deClave(json.texto(SUBIDA_ESTADO)),
    )

    /** Las fotos (`photos[]`) como objetos; sin `photos` → lista vacía. */
    fun fotos(json: JsonObject): List<JsonObject> =
        json.get("photos")?.takeIf { it.isJsonArray }?.asJsonArray?.mapNotNull { it.takeIf(JsonElement::isJsonObject)?.asJsonObject }
            .orEmpty()

    /** `photos[]` del manifest (para modificarlo); lo crea si falta. */
    fun arregloFotos(json: JsonObject): JsonArray =
        json.get("photos")?.takeIf { it.isJsonArray }?.asJsonArray ?: JsonArray().also { json.add("photos", it) }

    // ---- utilidades -------------------------------------------------------------------------------------------

    internal fun JsonObject.texto(clave: String): String? =
        get(clave)?.takeIf { it.isJsonPrimitive }?.asString

    internal fun JsonObject.numero(clave: String): Double? = get(clave)?.comoNumero()

    private fun JsonObject.objeto(clave: String): JsonObject? = get(clave)?.takeIf { it.isJsonObject }?.asJsonObject

    private fun JsonObject.obligatorio(clave: String): String =
        texto(clave)?.takeIf { it.isNotEmpty() } ?: throw ManifestException("falta $clave en una foto")

    private fun JsonElement.comoNumero(): Double? = try {
        if (isJsonPrimitive && asJsonPrimitive.isNumber) asDouble
        else if (isJsonPrimitive && asJsonPrimitive.isString) asString.toDoubleOrNull()
        else null
    } catch (_: NumberFormatException) {
        null
    }?.takeIf { it.isFinite() }
}
