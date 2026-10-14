package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Usuario

interface UsuariosRepository {
    suspend fun listar(): List<Usuario>
    suspend fun obtener(id: String): Usuario?
    /** Búsqueda sin distinguir mayúsculas ni espacios alrededor. */
    suspend fun buscarPorCorreo(correo: String): Usuario?
    /** Inserta o reemplaza el usuario con el mismo id. */
    suspend fun guardar(usuario: Usuario)
}

/**
 * TODO: reemplazar por la implementación real (GET/PUT /usuarios) usando ApiConfig.kt.
 * Mientras tanto guarda los usuarios en memoria; los cambios se pierden al cerrar la app.
 */
class UsuariosRepositoryEnMemoria(
    iniciales: List<Usuario> = SEMILLA,
) : UsuariosRepository {

    private val usuarios = LinkedHashMap<String, Usuario>().apply {
        iniciales.forEach { put(it.id, it) }
    }

    override suspend fun listar(): List<Usuario> = synchronized(usuarios) { usuarios.values.toList() }

    override suspend fun obtener(id: String): Usuario? = synchronized(usuarios) { usuarios[id] }

    override suspend fun buscarPorCorreo(correo: String): Usuario? {
        val buscado = correo.trim()
        return synchronized(usuarios) {
            usuarios.values.firstOrNull { it.correo.equals(buscado, ignoreCase = true) }
        }
    }

    override suspend fun guardar(usuario: Usuario) {
        synchronized(usuarios) { usuarios[usuario.id] = usuario }
    }

    companion object {
        val SEMILLA = listOf(
            Usuario(id = "1", nombre = "Administrador", correo = "admin@campus.edu.co", rol = Rol.ADMIN),
            Usuario(id = "2", nombre = "Investigador", correo = "investigador@campus.edu.co", rol = Rol.INVESTIGADOR),
            Usuario(id = "3", nombre = "Usuario", correo = "user@campus.edu.co", rol = Rol.USER),
        )

        /** Instancia única de la app: login y gestión de usuarios deben ver los mismos datos. */
        val compartido: UsuariosRepository by lazy { UsuariosRepositoryEnMemoria() }
    }
}
