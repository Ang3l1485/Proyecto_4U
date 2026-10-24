package com.example.myapplication.domain.model

/** Alerta de obstáculo que el admin coloca en el mapa. `tipo` y `prioridad` usan las mismas claves del mapa web. */
data class Alerta(
    val id: String,
    val lat: Double,
    val lng: Double,
    val mensaje: String,
    val tipo: String = "otro",          // agua | mobiliario | escalones | obra | vehiculos | otro
    val prioridad: String = "normal",   // normal | alta
    val radio: Int = 15,                // metros (5..100)
    val activa: Boolean = true,
)

data class Lugar(val nombre: String, val lat: Double, val lng: Double)