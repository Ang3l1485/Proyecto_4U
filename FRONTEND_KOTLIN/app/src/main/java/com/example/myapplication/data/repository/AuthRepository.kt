package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Sesion

class CredencialesInvalidasException : Exception("Credenciales inválidas")

interface AuthRepository {
    /**
     * POST /auth/login → token + rol.
     * @throws CredencialesInvalidasException si el backend responde 401/403 por credenciales.
     * @throws java.io.IOException si no hay conexión o el servidor no responde.
     */
    suspend fun login(identificador: String, password: String): Sesion
}

/**
 * TODO: reemplazar por la implementación real con Retrofit/Ktor usando ApiConfig.kt.
 * Mientras tanto devuelve una sesión simulada para poder probar la pantalla:
 *   - "admin@campus.edu.co" / cualquier clave  → ADMIN
 *   - "user@campus.edu.co"                      → USER (muestra "sin permisos")
 *   - "offline"                                 → simula falta de conexión
 *   - cualquier otro                            → credenciales inválidas
 */
class AuthRepositoryStub : AuthRepository {
    override suspend fun login(identificador: String, password: String): Sesion {
        kotlinx.coroutines.delay(1200)
        val rol = when (identificador.trim().lowercase()) {
            "admin@campus.edu.co" -> com.example.myapplication.domain.model.Rol.ADMIN
            "user@campus.edu.co" -> com.example.myapplication.domain.model.Rol.USER
            "offline" -> throw java.io.IOException("Sin conexión")
            else -> throw CredencialesInvalidasException()
        }
        return Sesion(
            token = "stub-token",
            usuario = com.example.myapplication.domain.model.Usuario(
                id = "1", nombre = "Administrador", correo = identificador.trim(), rol = rol,
            ),
        )
    }
}