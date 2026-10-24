package com.example.myapplication.domain.model

enum class Rol { USER, ADMIN }

data class Usuario(
    val id: String,
    val nombre: String,
    val correo: String,
    val rol: Rol,
)

/** Sesión activa: el token nunca se registra en logs (ver ARCHITECTURE §4, Registro de eventos). */
data class Sesion(
    val token: String,
    val usuario: Usuario,
)