package com.example.myapplication.ui.admin.mapa

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.Alertas
import com.example.myapplication.data.repository.AlertasRepository
import com.example.myapplication.domain.model.Alerta
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Estado de la lista 7.10 (FE-3.3). */
data class AlertasUiState(
    val cargando: Boolean = true,
    /** Error al leer el servidor sin nada guardado en el teléfono (con alertas guardadas va a [aviso]). */
    val error: String? = null,
    val todas: List<Alerta> = emptyList(),
    val pendientes: Set<String> = emptySet(),
    val rechazadas: Set<String> = emptySet(),
    val busqueda: String = "",
    val tipo: String? = null,
    val prioridad: String? = null,
    val estado: FiltroEstado = FiltroEstado.TODAS,
    val formulario: Alerta? = null,
    val errores: ErroresAlerta = ErroresAlerta.NINGUNO,
    val confirmandoBorrar: Alerta? = null,
    val sincronizando: Boolean = false,
    val aviso: String? = null,
) {
    val visibles: List<Alerta> get() = FiltrosAlertas.filtrar(todas, busqueda, tipo, prioridad, estado, pendientes)
    val hayFiltros: Boolean get() = busqueda.isNotBlank() || tipo != null || prioridad != null || estado != FiltroEstado.TODAS
}

/** Acciones de 7.10 (`{}` por defecto, para la vista previa). */
data class AlertasAcciones(
    val onVolver: () -> Unit = {},
    val onVerMapa: () -> Unit = {},
    val onNueva: () -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onBusqueda: (String) -> Unit = {},
    val onTipo: (String?) -> Unit = {},
    val onPrioridad: (String?) -> Unit = {},
    val onEstado: (FiltroEstado) -> Unit = {},
    val onLimpiarFiltros: () -> Unit = {},
    val onEditar: (String) -> Unit = {},
    val onAlternarActiva: (String) -> Unit = {},
    val onVerEnMapa: (String) -> Unit = {},
    val onPedirBorrar: (Alerta) -> Unit = {},
    val onConfirmarBorrar: () -> Unit = {},
    val onCancelarBorrar: () -> Unit = {},
    val onSincronizar: () -> Unit = {},
    val onDescartarAviso: () -> Unit = {},
)

/**
 * Vista 7.10 (FE-3.3): la lista de [repo] (la misma que ve 7.8). Al abrirse lee el disco y `GET /v1/admin/alerts`;
 * editar abre `AlertaFormSheet` aquí mismo; activar/desactivar y eliminar quedan pendientes como en el mapa; el aviso de
 * cambios sin sincronizar ofrece «Sincronizar».
 */
class AlertasViewModel(private val repo: AlertasRepository) : ViewModel() {
    private val _estado = MutableStateFlow(AlertasUiState())
    val estado: StateFlow<AlertasUiState> = _estado.asStateFlow()
    private var carga: Job? = null

    init {
        viewModelScope.launch {
            repo.estado.collect { e ->
                _estado.update { it.copy(todas = e.visibles, pendientes = e.idsPendientes, rechazadas = e.rechazadas) }
            }
        }
        cargar()
    }

    fun cargar() {
        carga?.cancel()
        _estado.update { it.copy(cargando = true, error = null) }
        carga = viewModelScope.launch {
            try {
                repo.cargar()
                repo.refrescar()
                _estado.update { it.copy(cargando = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val texto = TextosAlertas.deCarga(e)
                _estado.update {
                    if (it.todas.isEmpty()) it.copy(cargando = false, error = texto)
                    else it.copy(cargando = false, aviso = texto)
                }
            }
        }
    }

    fun alBuscar(texto: String) = _estado.update { it.copy(busqueda = texto) }
    fun alTipo(tipo: String?) = _estado.update { it.copy(tipo = tipo) }
    fun alPrioridad(p: String?) = _estado.update { it.copy(prioridad = p) }
    fun alEstado(e: FiltroEstado) = _estado.update { it.copy(estado = e) }
    fun limpiarFiltros() = _estado.update { it.copy(busqueda = "", tipo = null, prioridad = null, estado = FiltroEstado.TODAS) }
    fun descartarAviso() = _estado.update { it.copy(aviso = null) }

    // ── Formulario (7.9) ──
    fun editar(id: String) = _estado.update { s ->
        s.copy(formulario = s.todas.firstOrNull { it.id == id }, errores = ErroresAlerta.NINGUNO)
    }

    fun actualizarFormulario(a: Alerta) = _estado.update { it.copy(formulario = a, errores = ErroresAlerta.NINGUNO) }
    fun cancelarFormulario() = _estado.update { it.copy(formulario = null, errores = ErroresAlerta.NINGUNO) }

    fun guardarFormulario() {
        val a = _estado.value.formulario ?: return
        val errores = FormularioAlerta.validar(a)
        if (errores.hay) {
            _estado.update { it.copy(errores = errores) }
            return
        }
        _estado.update { it.copy(formulario = null, errores = ErroresAlerta.NINGUNO) }
        enRepo { repo.guardar(FormularioAlerta.limpia(a)) }
    }

    fun alternarActiva(id: String) {
        val a = _estado.value.todas.firstOrNull { it.id == id } ?: return
        enRepo { repo.guardar(a.copy(activa = !a.activa)) }
    }

    fun pedirBorrar(a: Alerta) = _estado.update { it.copy(confirmandoBorrar = a) }
    fun cancelarBorrar() = _estado.update { it.copy(confirmandoBorrar = null) }

    fun confirmarBorrar() {
        val a = _estado.value.confirmandoBorrar ?: return
        _estado.update { s -> s.copy(confirmandoBorrar = null, formulario = s.formulario?.takeIf { it.id != a.id }) }
        enRepo { repo.eliminar(a.id) }
    }

    fun sincronizar() {
        if (_estado.value.sincronizando) return
        _estado.update { it.copy(sincronizando = true) }
        viewModelScope.launch {
            val aviso = try {
                TextosAlertas.resultado(repo.sincronizar())
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                TextosAlertas.deExcepcion(e)
            }
            _estado.update { it.copy(sincronizando = false, aviso = aviso ?: it.aviso) }
        }
    }

    private fun enRepo(accion: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                accion()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                _estado.update { it.copy(aviso = TextosAlertas.NO_SE_GUARDO) }
            }
        }
    }

    /** `appContext` = el de la aplicación (la pantalla pasa `LocalContext.current.applicationContext`). */
    class Factory(private val appContext: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = AlertasViewModel(Alertas.de(appContext)) as T
    }
}
