package com.example.myapplication.ui.auth

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AuthRepository
import com.example.myapplication.data.repository.AuthRepositoryStub
import com.example.myapplication.data.repository.CredencialesInvalidasException
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.session.SessionManager
import java.io.IOException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class LoginError { CredencialesInvalidas, SinConexion, SinPermisos, Desconocido }

data class LoginUiState(
    val identificador: String = "",
    val password: String = "",
    val mostrarPassword: Boolean = false,
    val cargando: Boolean = false,
    val error: LoginError? = null,
) {
    val puedeEnviar: Boolean
        get() = identificador.isNotBlank() && password.isNotEmpty() && !cargando
}

sealed interface LoginEvento {
    /** Sesión ADMIN válida: navegar a admin/panel. */
    data object IrAlPanel : LoginEvento
}

class LoginViewModel(
    private val auth: AuthRepository,
    private val session: SessionManager,
) : ViewModel() {

    private val _state = MutableStateFlow(LoginUiState())
    val state: StateFlow<LoginUiState> = _state.asStateFlow()

    private val _eventos = Channel<LoginEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    init {
        // Si ya hay una sesión ADMIN guardada, se entra directo al panel.
        if (session.esAdmin()) _eventos.trySend(LoginEvento.IrAlPanel)
    }

    fun onIdentificadorChange(valor: String) =
        _state.update { it.copy(identificador = valor, error = null) }

    fun onPasswordChange(valor: String) =
        _state.update { it.copy(password = valor, error = null) }

    fun onTogglePassword() =
        _state.update { it.copy(mostrarPassword = !it.mostrarPassword) }

    fun iniciarSesion() {
        val actual = _state.value
        if (!actual.puedeEnviar) return

        _state.update { it.copy(cargando = true, error = null) }
        viewModelScope.launch {
            try {
                val sesion = auth.login(actual.identificador.trim(), actual.password)
                if (sesion.usuario.rol == Rol.ADMIN) {
                    session.guardar(sesion)
                    _state.update { it.copy(cargando = false, password = "") }
                    _eventos.send(LoginEvento.IrAlPanel)
                } else {
                    // Cuenta válida pero sin rol ADMIN: no se guarda sesión ni se habilita el panel.
                    session.cerrarSesion()
                    _state.update { it.copy(cargando = false, password = "", error = LoginError.SinPermisos) }
                }
            } catch (e: CredencialesInvalidasException) {
                _state.update { it.copy(cargando = false, error = LoginError.CredencialesInvalidas) }
            } catch (e: IOException) {
                _state.update { it.copy(cargando = false, error = LoginError.SinConexion) }
            } catch (e: Exception) {
                _state.update { it.copy(cargando = false, error = LoginError.Desconocido) }
            }
        }
    }

    class Factory(private val context: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            LoginViewModel(AuthRepositoryStub(), SessionManager(context.applicationContext)) as T
    }
}