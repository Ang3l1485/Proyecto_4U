package com.example.myapplication.ui.admin.videos

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AssetsVideoRepository
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** El mapa web recibe todo como JSON (ver `video_detalle.js`), por eso el estado ya lo trae serializado. */
data class VideoDetalleUiState(
    val cargando: Boolean = true,
    val noEncontrado: Boolean = false,
    val videoJson: String? = null,
    val otrosJson: String = "[]",
)

class VideoDetalleViewModel(
    private val videoId: String,
    private val repositorio: VideoRepository,
) : ViewModel() {

    private val _ui = MutableStateFlow(VideoDetalleUiState())
    val ui: StateFlow<VideoDetalleUiState> = _ui.asStateFlow()

    /** Una vez visto el video, si desaparece (lo eliminamos nosotros) no se muestra "no encontrado". */
    private var huboVideo = false

    init {
        // `cambios()` emite al suscribirse (carga inicial) y después tras cada renombrar/eliminar.
        viewModelScope.launch { repositorio.cambios().collect { cargar() } }
    }

    private suspend fun cargar() {
        try {
            val todos = repositorio.obtenerVideos()
            val video = todos.firstOrNull { it.id == videoId }
            if (video != null) huboVideo = true
            _ui.update {
                it.copy(
                    cargando = false,
                    noEncontrado = video == null && !huboVideo,
                    videoJson = video?.let(::videoAJson) ?: it.videoJson,
                    otrosJson = otrosAJson(todos.filter { v -> v.id != videoId }),
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _ui.update { it.copy(cargando = false, noEncontrado = !huboVideo) }
        }
    }

    fun renombrar(nombre: String) {
        viewModelScope.launch { repositorio.renombrarVideo(videoId, nombre.trim()) }
    }

    fun eliminarFoto(fotoId: String) {
        viewModelScope.launch { repositorio.eliminarFoto(videoId, fotoId) }
    }

    fun eliminarVideo() {
        viewModelScope.launch { repositorio.eliminarVideo(videoId) }
    }

    private fun videoAJson(v: Video): String = JSONObject().apply {
        put("id", v.id)
        put("nombre", v.nombre)
        put("fecha", v.creadoEn?.take(10) ?: JSONObject.NULL)   // "2026-10-09"
        put("fotos", JSONArray(v.fotos.map { f ->
            JSONObject().apply {
                put("id", f.id)
                put("url", f.urlFoto)
                put("thumb", f.urlMiniatura)
                put("lat", f.lat)
                put("lng", f.lng)
                put("rumbo", f.rumbo?.toDouble() ?: JSONObject.NULL)
            }
        }))
    }.toString()

    private fun otrosAJson(videos: List<Video>): String = JSONArray(videos.map { v ->
        JSONObject().apply {
            put("id", v.id)
            put("nombre", v.nombre)
            put("fotos", JSONArray(v.fotos.map { f -> JSONObject().put("lat", f.lat).put("lng", f.lng) }))
        }
    }).toString()

    class Factory(private val appContext: Context, private val videoId: String) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            VideoDetalleViewModel(videoId, AssetsVideoRepository(appContext)) as T
    }
}