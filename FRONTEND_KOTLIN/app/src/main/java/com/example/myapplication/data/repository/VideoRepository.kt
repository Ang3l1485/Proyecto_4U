package com.example.myapplication.data.repository

import android.content.Context
import android.util.Log
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Contrato de acceso a videos y fotos. Las pantallas solo conocen esta interfaz. */
interface VideoRepository {
    suspend fun obtenerVideos(): List<Video>
    suspend fun renombrarVideo(videoId: String, nombre: String)
    suspend fun eliminarVideo(videoId: String)
    suspend fun eliminarFoto(videoId: String, fotoId: String)

    /** Emite cada vez que cambian los datos (renombrar, eliminar...) para que las pantallas abiertas se refresquen. */
    fun cambios(): Flow<Int>
}

/**
 * Ediciones en memoria sobre los assets (que son de solo lectura). Se pierden al cerrar la app.
 * Es un objeto único del proceso para que lista, detalle y galería vean lo mismo.
 *
 * **TODO:** desaparece cuando exista el backend (las ediciones serán llamadas a la API).
 */
internal object EdicionesLocales {
    private val nombres = mutableMapOf<String, String>()
    private val videosEliminados = mutableSetOf<String>()
    private val fotosEliminadas = mutableSetOf<String>()   // uid = "videoId/fotoId"
    private val _version = MutableStateFlow(0)
    val version: StateFlow<Int> = _version.asStateFlow()

    @Synchronized
    fun renombrar(videoId: String, nombre: String) {
        nombres[videoId] = nombre; _version.update { it + 1 }
    }

    @Synchronized
    fun eliminarVideo(videoId: String) {
        videosEliminados += videoId; _version.update { it + 1 }
    }

    @Synchronized
    fun eliminarFoto(videoId: String, fotoId: String) {
        fotosEliminadas += "$videoId/$fotoId"; _version.update { it + 1 }
    }

    @Synchronized
    fun aplicar(videos: List<Video>): List<Video> = videos
        .filterNot { it.id in videosEliminados }
        .map { v ->
            val nombre = nombres[v.id] ?: v.nombre
            v.copy(
                nombre = nombre,
                fotos = v.fotos.filterNot { it.uid in fotosEliminadas }.map { it.copy(videoNombre = nombre) },
            )
        }
}

/**
 * Lee los videos empaquetados en `app/src/main/assets/videos/<video_id>/manifest.json`.
 *
 * **TODO:** reemplazar por `RemoteVideoRepository` (`GET /admin/videos/{id}/images`) cuando
 * exista el backend. El modelo `Foto` no cambia: solo cambian las URLs.
 */
class AssetsVideoRepository(private val context: Context) : VideoRepository {

    override suspend fun obtenerVideos(): List<Video> = withContext(Dispatchers.IO) {
        val videos = context.assets.list(RAIZ).orEmpty().sorted().mapNotNull { videoId ->
            try {
                leerVideo(videoId)
            } catch (e: Exception) {
                Log.w(TAG, "No se pudo leer $RAIZ/$videoId", e)
                null
            }
        }
        EdicionesLocales.aplicar(videos)
    }

    override suspend fun renombrarVideo(videoId: String, nombre: String) = EdicionesLocales.renombrar(videoId, nombre)
    override suspend fun eliminarVideo(videoId: String) = EdicionesLocales.eliminarVideo(videoId)
    override suspend fun eliminarFoto(videoId: String, fotoId: String) = EdicionesLocales.eliminarFoto(videoId, fotoId)
    override fun cambios(): Flow<Int> = EdicionesLocales.version

    private fun leerVideo(videoId: String): Video {
        val base = "$RAIZ/$videoId"
        val json = JSONObject(
            context.assets.open("$base/manifest.json").bufferedReader().use { it.readText() }
        )
        val nombre = json.optString("name", videoId)

        // Si una miniatura no existe todavía, se usa la foto original (Coil la reduce al cargar).
        val miniaturas = context.assets.list("$base/thumbs").orEmpty().toSet()

        val arreglo = json.getJSONArray("photos")
        val fotos = (0 until arreglo.length()).map { i ->
            val p = arreglo.getJSONObject(i)
            val archivo = p.getString("file")
            val miniatura = p.optString("thumb")
                .takeIf { it.isNotEmpty() && it.substringAfterLast('/') in miniaturas }
                ?: archivo

            Foto(
                id = p.getString("id"),
                videoId = videoId,
                videoNombre = nombre,
                urlFoto = "$URI_ASSETS/$base/$archivo",
                urlMiniatura = "$URI_ASSETS/$base/$miniatura",
                lat = p.getDouble("lat"),
                lng = p.getDouble("lng"),
                rumbo = if (p.has("heading") && !p.isNull("heading")) {
                    p.getDouble("heading").toFloat()
                } else null,
                capturadaEn = p.optString("captured_at").ifBlank { null },
                lugar = p.optString("lugar").ifBlank { null },
                estado = p.enumOpcional("estado", EstadoFoto.PROCESADA),
                calidad = p.enumOpcional("calidad", CalidadFoto.NORMAL),
            )
        }.sortedBy { it.id }

        return Video(
            id = videoId,
            nombre = nombre,
            creadoEn = json.optString("created_at").ifBlank { null },
            fotos = fotos,
        )
    }

    private inline fun <reified T : Enum<T>> JSONObject.enumOpcional(clave: String, porDefecto: T): T {
        val texto = optString(clave, "")
        return enumValues<T>().firstOrNull { it.name.equals(texto, ignoreCase = true) } ?: porDefecto
    }

    private companion object {
        const val TAG = "AssetsVideoRepository"
        const val RAIZ = "videos"
        const val URI_ASSETS = "file:///android_asset"
    }
}