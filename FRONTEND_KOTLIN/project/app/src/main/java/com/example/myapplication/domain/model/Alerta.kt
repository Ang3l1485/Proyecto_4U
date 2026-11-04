package com.example.myapplication.domain.model

/**
 * Alerta de obstáculo que el admin coloca en el mapa. `tipo` y `prioridad` usan las mismas claves del mapa web y del
 * backend (`Alerta`, backend §5.3).
 *
 * FE-3.3: la vigencia (instantes en milisegundos UTC; `null` = sin límite) y lo que el backend dice de la alerta
 * (`version` y `actualizado_en` en milisegundos; `null` en una alerta que el servidor aún no conoce). La app no manda
 * `version` ni `actualizado_en`: los pone el backend.
 */
data class Alerta(
    val id: String,
    val lat: Double,
    val lng: Double,
    val mensaje: String,
    val tipo: String = "otro",          // agua | mobiliario | escalones | obra | vehiculos | otro
    val prioridad: String = "normal",   // normal | alta
    val radio: Int = 15,                // metros (5..100)
    val activa: Boolean = true,
    val vigenciaDesdeMs: Long? = null,
    val vigenciaHastaMs: Long? = null,
    val version: Int? = null,
    val actualizadoEnMs: Long? = null,
)

/**
 * Un cambio de alertas pendiente de enviar (FE-3.3). Los pendientes guardan **una sola operación por id, la última**
 * (backend §4.11, «Para la app»): crear y editar → un [Upsert]; crear y borrar antes de sincronizar → un [Eliminar], que
 * con un id que el servidor no conoce no deja rastro.
 */
sealed interface OperacionAlerta {
    val id: String

    data class Upsert(val alerta: Alerta) : OperacionAlerta {
        override val id: String get() = alerta.id
    }

    data class Eliminar(override val id: String) : OperacionAlerta
}

// FE-3.4: el antiguo `Lugar(nombre, lat, lng)` del editor de mapa se unificó en `LugarDestino` (LugarDestino.kt).