package com.example.myapplication.domain.usecase

import com.example.myapplication.data.repository.UsuariosRepository
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Usuario

/** Acción rechazada por una regla de gestión de usuarios. */
sealed class GestionUsuariosException(mensaje: String) : Exception(mensaje)

class UsuarioNoEncontradoException(id: String) :
    GestionUsuariosException("No existe el usuario con id $id")

/** Quitar el rol o desactivar al último ADMIN activo dejaría el sistema sin administrador. */
class UltimoAdministradorException :
    GestionUsuariosException("No se puede dejar el sistema sin un administrador activo")

class AutoDesactivacionException :
    GestionUsuariosException("Un administrador no puede desactivar su propia cuenta")

/** Casos de uso de HU-017. Kotlin puro: se prueba con JUnit sin Android. */
class GestionUsuarios(private val repo: UsuariosRepository) {

    suspend fun listar(): List<Usuario> = repo.listar()

    /** @throws UsuarioNoEncontradoException, UltimoAdministradorException */
    suspend fun cambiarRol(id: String, rol: Rol): Usuario {
        val usuario = obtenerOFallar(id)
        if (usuario.rol == rol) return usuario
        if (esUltimoAdminActivo(usuario)) throw UltimoAdministradorException()
        return usuario.copy(rol = rol).also { repo.guardar(it) }
    }

    /** Activar una cuenta ya activa no cambia nada. @throws UsuarioNoEncontradoException */
    suspend fun activar(id: String): Usuario {
        val usuario = obtenerOFallar(id)
        if (usuario.activo) return usuario
        return usuario.copy(activo = true).also { repo.guardar(it) }
    }

    /** @throws UsuarioNoEncontradoException, AutoDesactivacionException, UltimoAdministradorException */
    suspend fun desactivar(id: String, idSolicitante: String): Usuario {
        val usuario = obtenerOFallar(id)
        if (id == idSolicitante) throw AutoDesactivacionException()
        if (!usuario.activo) return usuario
        if (esUltimoAdminActivo(usuario)) throw UltimoAdministradorException()
        return usuario.copy(activo = false).also { repo.guardar(it) }
    }

    private suspend fun obtenerOFallar(id: String): Usuario =
        repo.obtener(id) ?: throw UsuarioNoEncontradoException(id)

    private suspend fun esUltimoAdminActivo(usuario: Usuario): Boolean =
        usuario.rol == Rol.ADMIN && usuario.activo &&
            repo.listar().count { it.rol == Rol.ADMIN && it.activo } <= 1
}
