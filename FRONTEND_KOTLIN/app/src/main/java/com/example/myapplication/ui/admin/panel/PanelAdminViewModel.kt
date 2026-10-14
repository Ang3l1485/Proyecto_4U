package com.example.myapplication.ui.admin.panel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AdminRepository
import com.example.myapplication.data.repository.AdminRepositoryStub
import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.domain.model.ResumenAdmin
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.usecase.PoliticaAcceso
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
    /** Módulos que el rol de la sesión puede abrir; las tarjetas del resto no se muestran. */
    val modulosPermitidos: Set<Modulo> = emptySet(),
)

sealed interface PanelEvento {
    /** El admin cerró sesión: volver al flujo público. */
    data object SesionCerrada : PanelEvento
    /** No hay sesión con acceso al panel: redirigir a Login. */
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

    private var resumenSolicitado = false

    /**
     * Guarda de rol. La pantalla la llama cada vez que el panel se muestra, para reflejar cambios
     * de rol hechos mientras tanto (p. ej. un admin que se asignó otro rol en Usuarios).
     */
    fun validarSesion() {
        val sesion = session.obtener()
        if (sesion == null || !PoliticaAcceso.puedeEntrarAlPanel(sesion.usuario.rol)) {
            _eventos.trySend(PanelEvento.SinSesion)
            return
        }
        _state.update {
            it.copy(
                nombre = sesion.usuario.nombre.trim().substringBefore(' '),
                rolTexto = if (sesion.usuario.rol == Rol.ADMIN) "Administrador del sistema" else "Investigador",
                modulosPermitidos = Modulo.entries.filter(session::puedeAcceder).toSet(),
            )
        }
        if (!resumenSolicitado) {
            resumenSolicitado = true
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