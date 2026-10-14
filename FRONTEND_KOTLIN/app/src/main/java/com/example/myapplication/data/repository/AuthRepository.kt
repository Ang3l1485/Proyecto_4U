package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Sesion

class CredencialesInvalidasException : Exception("Credenciales inválidas")

/** La cuenta existe pero un administrador la desactivó (HU-017). */
class CuentaDesactivadaException : Exception("Cuenta desactivada")

interface AuthRepository {
    /**
     * POST /auth/login → token + rol.
     * @throws CredencialesInvalidasException si el backend responde 401/403 por credenciales.
     * @throws CuentaDesactivadaException si la cuenta está desactivada.
     * @throws java.io.IOException si no hay conexión o el servidor no responde.
     */
    suspend fun login(identificador: String, password: String): Sesion
}

/**
 * TODO: reemplazar por la implementación real con Retrofit/Ktor usando ApiConfig.kt.
 * Mientras tanto busca el correo en [UsuariosRepository] (cualquier clave es válida):
 *   - "admin@campus.edu.co"        → ADMIN
 *   - "investigador@campus.edu.co" → INVESTIGADOR (muestra "sin permisos")
 *   - "user@campus.edu.co"         → USER (muestra "sin permisos")
 *   - cuenta desactivada           → CuentaDesactivadaException
 *   - "offline"                    → simula falta de conexión
 *   - cualquier otro               → credenciales inválidas
 */
class AuthRepositoryStub(
    private val usuarios: UsuariosRepository = UsuariosRepositoryEnMemoria.compartido,
    private val retardoMs: Long = 1200,
) : AuthRepository {
    override suspend fun login(identificador: String, password: String): Sesion {
        kotlinx.coroutines.delay(retardoMs)
        if (identificador.trim().lowercase() == "offline") throw java.io.IOException("Sin conexión")
        val usuario = usuarios.buscarPorCorreo(identificador) ?: throw CredencialesInvalidasException()
        if (!usuario.activo) throw CuentaDesactivadaException()
        return Sesion(token = "stub-token", usuario = usuario)
    }
}
