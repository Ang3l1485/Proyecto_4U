package com.example.myapplication.ui.admin.panel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AdminRepository
import com.example.myapplication.data.repository.AdminRepositoryStub
import com.example.myapplication.domain.model.ResumenAdmin
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.session.SessionManager
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PanelUiState(
    val nombre: String = "",
    val rolTexto: String = "",
    val resumen: ResumenAdmin? = null,
    val cargandoResumen: Boolean = true,
    val errorResumen: Boolean = false,
)

sealed interface PanelEvento {
    /** El admin cerró sesión: volver al flujo público. */
    data object SesionCerrada : PanelEvento
    /** No hay sesión ADMIN válida: redirigir a Login. */
    data object SinSesion : PanelEvento
}

class PanelAdminViewModel(
    private val repo: AdminRepository,
    private val session: SessionManager,
) : ViewModel() {

    private val _state = MutableStateFlow(PanelUiState())
    val state: StateFlow<PanelUiState> = _state.asStateFlow()

    private val _eventos = Channel<PanelEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    init {
        val sesion = session.obtener()
        if (sesion == null || sesion.usuario.rol != Rol.ADMIN) {
            // Guarda de rol: sin sesión ADMIN no se muestra el panel.
            _eventos.trySend(PanelEvento.SinSesion)
        } else {
            _state.update {
                it.copy(
                    nombre = sesion.usuario.nombre.trim().substringBefore(' '),
                    rolTexto = "Administrador del sistema",
                )
            }
            cargarResumen()
        }
    }

    fun cargarResumen() {
        _state.update { it.copy(cargandoResumen = true, errorResumen = false) }
        viewModelScope.launch {
            try {
                val resumen = repo.obtenerResumen()
                _state.update { it.copy(resumen = resumen, cargandoResumen = false) }
            } catch (e: Exception) {
                _state.update { it.copy(cargandoResumen = false, errorResumen = true) }
            }
        }
    }

    fun cerrarSesion() {
        session.cerrarSesion()
        _eventos.trySend(PanelEvento.SesionCerrada)
    }

    class Factory(private val context: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PanelAdminViewModel(AdminRepositoryStub(), SessionManager(context.applicationContext)) as T
    }
}