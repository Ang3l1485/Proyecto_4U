package com.example.myapplication.ui.admin.usuarios

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.UsuariosRepositoryEnMemoria
import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.domain.usecase.AutoDesactivacionException
import com.example.myapplication.domain.usecase.GestionUsuarios
import com.example.myapplication.domain.usecase.UltimoAdministradorException
import com.example.myapplication.domain.usecase.UsuarioNoEncontradoException
import com.example.myapplication.session.SessionManager
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Diálogo abierto en la pantalla (solo uno a la vez). */
sealed interface DialogoUsuarios {
    data class CambiarRol(val usuario: Usuario) : DialogoUsuarios
    /** Confirmación previa a activar (activar = true) o desactivar (activar = false). */
    data class ConfirmarEstado(val usuario: Usuario, val activar: Boolean) : DialogoUsuarios
}

data class UsuariosUiState(
    val cargando: Boolean = true,
    val error: String? = null,
    val usuarios: List<Usuario> = emptyList(),
    /** Id del admin con sesión iniciada: se marca como "Tú" en la lista. */
    val idSesion: String? = null,
    /** Id del usuario con una acción en curso (deshabilita sus botones). */
    val procesando: String? = null,
    val dialogo: DialogoUsuarios? = null,
    /** Resultado de la última acción (éxito o rechazo); se muestra en un Snackbar. */
    val mensaje: String? = null,
)

sealed interface UsuariosEvento {
    /** El admin se quitó a sí mismo el rol ADMIN: ya no puede seguir en esta pantalla. */
    data object SinAcceso : UsuariosEvento
}

class UsuariosViewModel(
    private val gestion: GestionUsuarios,
    private val session: SessionManager,
) : ViewModel() {

    private val _state = MutableStateFlow(UsuariosUiState(idSesion = session.obtener()?.usuario?.id))
    val state: StateFlow<UsuariosUiState> = _state.asStateFlow()

    private val _eventos = Channel<UsuariosEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    init {
        cargar()
    }

    fun cargar() {
        _state.update { it.copy(cargando = true, error = null) }
        viewModelScope.launch {
            try {
                val usuarios = gestion.listar()
                _state.update { it.copy(cargando = false, usuarios = usuarios) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(cargando = false, error = "No se pudieron cargar los usuarios.") }
            }
        }
    }

    fun abrirCambioRol(usuario: Usuario) =
        _state.update { it.copy(dialogo = DialogoUsuarios.CambiarRol(usuario)) }

    fun pedirCambioEstado(usuario: Usuario) =
        _state.update { it.copy(dialogo = DialogoUsuarios.ConfirmarEstado(usuario, activar = !usuario.activo)) }

    fun cerrarDialogo() = _state.update { it.copy(dialogo = null) }

    fun mensajeMostrado() = _state.update { it.copy(mensaje = null) }

    fun cambiarRol(usuario: Usuario, rol: Rol) = ejecutar(usuario) {
        val actualizado = gestion.cambiarRol(usuario.id, rol)
        actualizarSesionSiEsPropia(actualizado)
        "Rol de ${actualizado.nombre} cambiado a ${rol.texto()}."
    }

    fun confirmarCambioEstado(usuario: Usuario, activar: Boolean) = ejecutar(usuario) {
        if (activar) {
            if (usuario.activo) "${usuario.nombre} ya estaba activo."
            else "${gestion.activar(usuario.id).nombre} fue activado."
        } else {
            val solicitante = _state.value.idSesion.orEmpty()
            "${gestion.desactivar(usuario.id, solicitante).nombre} fue desactivado."
        }
    }

    /** Ejecuta una acción de gestión, recarga la lista y traduce los rechazos a mensajes. */
    private fun ejecutar(usuario: Usuario, accion: suspend () -> String) {
        _state.update { it.copy(dialogo = null, procesando = usuario.id) }
        viewModelScope.launch {
            val mensaje = try {
                accion()
            } catch (e: CancellationException) {
                throw e
            } catch (e: UltimoAdministradorException) {
                "No se puede quitar el rol ni desactivar al último administrador activo."
            } catch (e: AutoDesactivacionException) {
                "No puedes desactivar tu propia cuenta."
            } catch (e: UsuarioNoEncontradoException) {
                "El usuario ya no existe. Se actualizó la lista."
            } catch (e: Exception) {
                "No se pudo completar la acción. Inténtalo de nuevo."
            }
            val usuarios = runCatching { gestion.listar() }.getOrDefault(_state.value.usuarios)
            _state.update { it.copy(procesando = null, usuarios = usuarios, mensaje = mensaje) }
        }
    }

    /** Si el admin cambia su propio rol, la sesión guardada debe reflejarlo. */
    private suspend fun actualizarSesionSiEsPropia(usuario: Usuario) {
        val sesion = session.obtener() ?: return
        if (sesion.usuario.id != usuario.id) return
        session.guardar(sesion.copy(usuario = usuario))
        if (!session.puedeAcceder(Modulo.USUARIOS)) _eventos.send(UsuariosEvento.SinAcceso)
    }

    class Factory(private val context: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            UsuariosViewModel(
                GestionUsuarios(UsuariosRepositoryEnMemoria.compartido),
                SessionManager(context.applicationContext),
            ) as T
    }
}

/** Nombre del rol para mostrar y leer en voz alta. */
internal fun Rol.texto(): String = when (this) {
    Rol.USER -> "Usuario"
    Rol.INVESTIGADOR -> "Investigador"
    Rol.ADMIN -> "Administrador"
}
