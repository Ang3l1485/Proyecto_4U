package com.example.myapplication.ui.admin.lugares

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.RemoteLugaresAdminRepository
import com.example.myapplication.data.repository.CambiosLugares
import com.example.myapplication.data.repository.LugaresAdminRepository
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarAdmin
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Vista 7.6 · Lista de lugares (FE-3.4). Carga `GET /v1/admin/places` al crearse y **vuelve a cargar cada vez que
 * [cambios] sube** (crear o editar en 7.7, borrar aquí): así la lista está al día al
 * volver del formulario sin recargar en cada `ON_RESUME`. Una sesión perdida no muestra error (`AppNav` va a Login).
 */
class LugaresViewModel(
    private val repo: LugaresAdminRepository,
    cambios: StateFlow<Int> = CambiosLugares.version,
) : ViewModel() {

    private val _estado = MutableStateFlow(LugaresUiState())
    val estado: StateFlow<LugaresUiState> = _estado.asStateFlow()

    private var carga: Job? = null

    init {
        cargar()
        viewModelScope.launch { cambios.drop(1).collect { cargar(silencioso = true) } }
    }

    /** Lee la lista. [silencioso]: recarga tras un cambio, sin vaciar la pantalla ni mostrar el indicador. */
    fun cargar(silencioso: Boolean = false) {
        carga?.cancel()
        if (!silencioso) _estado.update { it.copy(cargando = true, error = null) }
        carga = viewModelScope.launch {
            try {
                val lugares = repo.listar()
                _estado.update { it.copy(cargando = false, error = null, todos = lugares) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val texto = ErroresLugarMapeo.errorDeCarga(e)
                _estado.update {
                    when {
                        texto == null -> it.copy(cargando = false)
                        silencioso && it.todos.isNotEmpty() -> it.copy(cargando = false, aviso = texto)
                        else -> it.copy(cargando = false, error = texto)
                    }
                }
            }
        }
    }

    fun alBuscar(texto: String) = _estado.update { it.copy(busqueda = texto) }
    fun alCategoria(c: CategoriaLugar?) = _estado.update { it.copy(categoria = c) }
    fun limpiarFiltros() = _estado.update { it.copy(busqueda = "", categoria = null) }
    fun alModo(m: ModoLugares) = _estado.update { it.copy(modo = m) }
    fun descartarAviso() = _estado.update { it.copy(aviso = null) }

    fun pedirBorrar(l: LugarAdmin) = _estado.update { if (it.borrando) it else it.copy(confirmandoBorrar = l) }
    fun cancelarBorrar() = _estado.update { it.copy(confirmandoBorrar = null) }

    /** `DELETE /v1/admin/places/{id}`; lo quita de la lista al instante (la recarga llega por [CambiosLugares]). */
    fun confirmarBorrar() {
        val l = _estado.value.confirmandoBorrar ?: return
        _estado.update { it.copy(confirmandoBorrar = null, borrando = true) }
        viewModelScope.launch {
            try {
                repo.borrar(l.id)
                _estado.update { s ->
                    s.copy(borrando = false, todos = s.todos.filterNot { it.id == l.id }, aviso = "«${l.nombre}» eliminado.")
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val texto = ErroresLugarMapeo.deExcepcion(e)?.general
                _estado.update { it.copy(borrando = false, aviso = texto?.let { t -> "No se pudo eliminar: $t" }) }
            }
        }
    }

    class Factory : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            LugaresViewModel(RemoteLugaresAdminRepository()) as T
    }
}
