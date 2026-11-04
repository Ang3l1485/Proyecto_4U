package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.BackendHealth
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

/**
 * [BackendHealth] real: `GET /v1/health` (backend §5.3). En línea = `200` con `"estado": "ok"`. Cualquier otro
 * resultado (sin red, *timeout*, 5xx, cuerpo distinto) es `false`. La llamada entera tiene [limiteMs] (5 s por
 * defecto) para que el sondeo de Inicio (cada 15 s) no se quede esperando los 30 s de lectura del cliente.
 */
class RemoteBackendHealth(
    private val api: CampusApi,
    private val limiteMs: Long = LIMITE_MS,
) : BackendHealth {

    override suspend fun estaEnLinea(): Boolean = withTimeoutOrNull(limiteMs) {
        try {
            llamar { api.salud() }.estado == "ok"
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            false
        }
    } ?: false

    companion object {
        const val LIMITE_MS = 5_000L
    }
}
