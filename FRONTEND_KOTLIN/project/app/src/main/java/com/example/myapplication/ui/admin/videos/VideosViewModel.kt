package com.example.myapplication.ui.admin.videos

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.data.repository.VideoRepositoryCompuesto
import com.example.myapplication.domain.model.OrdenVideos
import com.example.myapplication.domain.model.ResumenVideo
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Estado de la Lista (7.13, FE-4.1). [locales] = recorridos del teléfono sin subir (salen aunque el servidor falle);
 * [servidor] = todas las páginas de `GET /v1/admin/videos` con la búsqueda y el orden; [totalServidor] es el «N videos»
 * del encabezado (`total` del servidor, `null` mientras carga o si falló).
 */
data class VideosUiState(
    val cargando: Boolean = true,
    val errorServidor: String? = null,
    val locales: List<ResumenVideo> = emptyList(),
    val servidor: List<ResumenVideo> = emptyList(),
    val totalServidor: Int? = null,
    val busqueda: String = "",
    val orden: OrdenVideos = OrdenVideos.RECIENTES,
) {
    val vacia: Boolean get() = !cargando && errorServidor == null && locales.isEmpty() && servidor.isEmpty()
}

/**
 * ViewModel de 7.13 (FE-4.1). Recoge `repositorio.cambios()` (su primera emisión **es** la carga inicial; las siguientes,
 * tras renombrar o eliminar en 7.14 o un intento de la cola de subida). Cada carga cancela la anterior: gana la última.
 * La búsqueda espera [ESPERA_BUSQUEDA_MS] sin teclear antes de pedir.
 */
class VideosViewModel(private val repositorio: VideoRepository) : ViewModel() {

    private val _ui = MutableStateFlow(VideosUiState())
    val uiState: StateFlow<VideosUiState> = _ui.asStateFlow()

    private var carga: Job? = null

    init {
        viewModelScope.launch { repositorio.cambios().collect { cargar(espera = 0) } }
    }

    fun reintentar() {
        _ui.update { it.copy(cargando = true, errorServidor = null) }
        cargar(espera = 0)
    }

    fun buscar(texto: String) {
        _ui.update { it.copy(busqueda = texto.take(MAX_BUSQUEDA)) }
        cargar(espera = ESPERA_BUSQUEDA_MS)
    }

    fun ordenar(orden: OrdenVideos) {
        if (orden == _ui.value.orden) return
        _ui.update { it.copy(orden = orden, cargando = true) }
        cargar(espera = 0)
    }

    private fun cargar(espera: Long) {
        carga?.cancel()
        carga = viewModelScope.launch {
            if (espera > 0) delay(espera)
            val s = _ui.value
            try {
                val lista = repositorio.listarVideos(s.busqueda.trim().ifEmpty { null }, s.orden)
                val error = lista.errorServidor
                _ui.update {
                    it.copy(
                        cargando = false,
                        locales = lista.locales,
                        // Si el servidor falló, su parte queda vacía (con el aviso y «Reintentar»); los locales se ven.
                        servidor = lista.servidor,
                        totalServidor = lista.totalServidor,
                        errorServidor = error?.let { e -> TextosVideos.error(e, "cargar la lista del servidor") },
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update {
                    it.copy(cargando = false, errorServidor = TextosVideos.error(e, "cargar los videos") ?: it.errorServidor)
                }
            }
        }
    }

    /** Sin argumentos desde FE-4.1 (`VideoRepositoryCompuesto.deLaApp()` usa `Subidas`, que ya tiene el contexto). */
    class Factory : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            VideosViewModel(VideoRepositoryCompuesto.deLaApp()) as T
    }

    companion object {
        const val ESPERA_BUSQUEDA_MS = 400L

        /** El `q` del backend admite como mucho 100 caracteres. */
        const val MAX_BUSQUEDA = 100
    }
}