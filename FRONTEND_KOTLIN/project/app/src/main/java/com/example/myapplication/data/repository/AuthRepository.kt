package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Sesion

class CredencialesInvalidasException : Exception("Credenciales inválidas")

interface AuthRepository {
    /**
     * `POST /v1/auth/login` → [Sesion] con token, usuario y `expira_en` (backend §5.3). La implementación real es
     * `data.remote.RemoteAuthRepository` (FE-1.2).
     * @throws CredencialesInvalidasException si el backend responde `401 CREDENCIALES_INVALIDAS`.
     * @throws java.io.IOException si no hay conexión o el servidor no responde.
     */
    suspend fun login(identificador: String, password: String): Sesion
}

/**
 * Sesión simulada, sin red (desde FE-1.2 la app usa `RemoteAuthRepository`; esto queda para pruebas a mano):
 *   - "admin@campus.edu.co" / cualquier clave  → ADMIN
 *   - "user@campus.edu.co"                      → USER (muestra "sin permisos")
 *   - "offline"                                 → simula falta de conexión
 *   - cualquier otro                            → credenciales inválidas
 * La sesión vence a las 12 h, como el JWT del backend.
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
            expiraEnMs = System.currentTimeMillis() + 12 * 60 * 60 * 1000L,
        )
    }
}
