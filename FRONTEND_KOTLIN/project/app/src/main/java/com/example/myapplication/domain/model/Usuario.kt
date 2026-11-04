package com.example.myapplication.domain.model

enum class Rol { USER, ADMIN }

data class Usuario(
    val id: String,
    val nombre: String,
    val correo: String,
    val rol: Rol,
)

/**
 * Sesión activa: el token nunca se registra en logs (ver ARCHITECTURE §3.2, «Registro de eventos»).
 * [expiraEnMs] es el `expira_en` del login (backend §5.2: el `exp` del JWT) en milisegundos Unix (FE-1.2).
 */
data class Sesion(
    val token: String,
    val usuario: Usuario,
    val expiraEnMs: Long,
) {
    /** `true` si `expira_en` ya pasó (sin margen, como el backend): la sesión cuenta como «sin sesión». */
    fun vencida(ahoraMs: Long): Boolean = ahoraMs >= expiraEnMs
}
