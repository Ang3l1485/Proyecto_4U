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

data class VideosUiState(
    val cargando: Boolean = true,
    val error: String? = null,
    val videos: List<Video> = emptyList(),
)

class VideosViewModel(private val repositorio: VideoRepository) : ViewModel() {

    private val _ui = MutableStateFlow(VideosUiState())
    val uiState: StateFlow<VideosUiState> = _ui.asStateFlow()

    init {
        // Emite al suscribirse (carga inicial) y cada vez que el detalle renombra o elimina un video.
        viewModelScope.launch { repositorio.cambios().collect { cargar() } }
    }

    fun reintentar() {
        viewModelScope.launch { cargar() }
    }

    private suspend fun cargar() {
        try {
            val videos = repositorio.obtenerVideos()
            _ui.update { it.copy(cargando = false, error = null, videos = videos) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _ui.update { it.copy(cargando = false, error = "No se pudieron cargar los videos") }
        }
    }

    class Factory(private val appContext: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            VideosViewModel(AssetsVideoRepository(appContext)) as T
    }
}