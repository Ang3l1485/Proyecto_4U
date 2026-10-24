package com.example.myapplication.ui.admin.imagenes

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AssetsVideoRepository
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

const val FOTOS_POR_PAGINA = 24

enum class ModoVista { CUADRICULA, MAPA }

data class GaleriaFiltros(
    val busqueda: String = "",
    val lugar: String? = null,
    val videoId: String? = null,
    val estado: EstadoFoto? = null,
    val calidad: CalidadFoto? = null,
) {
    val hayActivos: Boolean
        get() = busqueda.isNotBlank() || lugar != null || videoId != null ||
            estado != null || calidad != null
}

data class GaleriaUiState(
    val cargando: Boolean = true,
    val error: String? = null,
    val videos: List<Video> = emptyList(),
    val todas: List<Foto> = emptyList(),
    val filtros: GaleriaFiltros = GaleriaFiltros(),
    val modo: ModoVista = ModoVista.CUADRICULA,
    val pagina: Int = 1,
    /** `uid` de las fotos seleccionadas. */
    val seleccion: Set<String> = emptySet(),
) {
    val filtradas: List<Foto>
        get() {
            val q = filtros.busqueda.trim().lowercase()
            return todas.filter { f ->
                (filtros.videoId == null || f.videoId == filtros.videoId) &&
                    (filtros.lugar == null || f.lugar == filtros.lugar) &&
                    (filtros.estado == null || f.estado == filtros.estado) &&
                    (filtros.calidad == null || f.calidad == filtros.calidad) &&
                    (q.isEmpty() ||
                        f.nombreArchivo.lowercase().contains(q) ||
                        f.videoNombre.lowercase().contains(q) ||
                        f.lugar?.lowercase()?.contains(q) == true)
            }
        }

    val totalPaginas: Int
        get() = maxOf(1, (filtradas.size + FOTOS_POR_PAGINA - 1) / FOTOS_POR_PAGINA)

    val paginaActual: List<Foto>
        get() = filtradas.drop((pagina - 1) * FOTOS_POR_PAGINA).take(FOTOS_POR_PAGINA)

    val lugares: List<String>
        get() = todas.mapNotNull { it.lugar }.distinct().sorted()
}

class GaleriaViewModel(private val repositorio: VideoRepository) : ViewModel() {

    private val _ui = MutableStateFlow(GaleriaUiState())
    val uiState: StateFlow<GaleriaUiState> = _ui.asStateFlow()

    init {
        cargar()
    }

    fun cargar() {
        _ui.update { it.copy(cargando = true, error = null) }
        viewModelScope.launch {
            try {
                val videos = repositorio.obtenerVideos()
                _ui.update {
                    it.copy(
                        cargando = false,
                        videos = videos,
                        todas = videos.flatMap { v -> v.fotos },
                    )
                }
            } catch (e: Exception) {
                _ui.update { it.copy(cargando = false, error = "No se pudieron cargar las imágenes") }
            }
        }
    }

    // ── Filtros ─────────────────────────────────────────────────────────────

    fun buscar(texto: String) = cambiarFiltros { it.copy(busqueda = texto) }
    fun filtrarLugar(lugar: String?) = cambiarFiltros { it.copy(lugar = lugar) }
    fun filtrarVideo(videoId: String?) = cambiarFiltros { it.copy(videoId = videoId) }
    fun filtrarEstado(estado: EstadoFoto?) = cambiarFiltros { it.copy(estado = estado) }
    fun filtrarCalidad(calidad: CalidadFoto?) = cambiarFiltros { it.copy(calidad = calidad) }
    fun limpiarFiltros() = cambiarFiltros { GaleriaFiltros() }

    /** Al cambiar filtros se vuelve a la página 1 y se limpia la selección (evita acciones sobre fotos ocultas). */
    private fun cambiarFiltros(cambio: (GaleriaFiltros) -> GaleriaFiltros) {
        _ui.update {
            it.copy(filtros = cambio(it.filtros), pagina = 1, seleccion = emptySet())
        }
    }

    // ── Vista y paginación ──────────────────────────────────────────────────

    fun cambiarModo(modo: ModoVista) = _ui.update { it.copy(modo = modo) }

    fun irAPagina(pagina: Int) = _ui.update { it.copy(pagina = pagina.coerceIn(1, it.totalPaginas)) }

    // ── Selección y acciones en lote ────────────────────────────────────────

    fun alternarSeleccion(uid: String) = _ui.update {
        it.copy(seleccion = if (uid in it.seleccion) it.seleccion - uid else it.seleccion + uid)
    }

    fun limpiarSeleccion() = _ui.update { it.copy(seleccion = emptySet()) }

    /**
     * Solo en memoria: los assets son de solo lectura, así que se pierde al cerrar la pantalla.
     * **TODO:** llamar a `DELETE /admin/images` cuando exista el backend.
     */
    fun eliminarSeleccion() = _ui.update { s ->
        val restante = s.copy(
            todas = s.todas.filterNot { it.uid in s.seleccion },
            seleccion = emptySet(),
        )
        restante.copy(pagina = restante.pagina.coerceIn(1, restante.totalPaginas))
    }

    /** Solo en memoria (ver nota de [eliminarSeleccion]). */
    fun reasignarSeleccion(lugar: String) = _ui.update { s ->
        s.copy(
            todas = s.todas.map { if (it.uid in s.seleccion) it.copy(lugar = lugar.trim()) else it },
            seleccion = emptySet(),
        )
    }

    class Factory(private val appContext: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            GaleriaViewModel(AssetsVideoRepository(appContext)) as T
    }
}