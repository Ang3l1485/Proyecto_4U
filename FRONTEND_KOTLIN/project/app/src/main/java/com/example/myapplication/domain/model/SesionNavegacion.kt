package com.example.myapplication.domain.model

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Datos que comparten las vistas del flujo público (decisión abierta 15, resuelta por el usuario el 2026-10-26: «En
 * memoria»; ADR-FE-24): el destino elegido en 6.4 y la última ubicación de «Ubicarse» (6.2 → 6.3). Es la lógica de
 * [SesionDeNavegacion] (el holder único del proceso), separada para probarla con un reloj falso.
 *
 *   6.4 Destino --[elegirDestino]--> 6.2 Escaneo --[registrar]--> 6.3 Resultado
 *   6.3 «Ir a un lugar desde aquí» --> 6.4 (posicionVigente: distancias reales)
 *
 * Solo en memoria (nada en disco: la posición de la persona no se guarda en el teléfono). Si Android mata el proceso se
 * pierde; 6.3 lo dice («No tengo una ubicación reciente») y ofrece volver a ubicarse.
 *
 * [reloj] da milisegundos monótonos (por defecto `System.nanoTime()`; no la hora del teléfono).
 */
open class SesionNavegacion(private val reloj: () -> Long = { System.nanoTime() / 1_000_000L }) {

    private val _destino = MutableStateFlow<LugarDestino?>(null)

    /** Destino confirmado en 6.4, o `null` (Inicio → «uno» lo quita). */
    val destino: StateFlow<LugarDestino?> = _destino.asStateFlow()

    private val _ubicacion = MutableStateFlow<UbicacionEstimada?>(null)

    /** Última ubicación recibida (vigente o no), o `null`. */
    val ubicacion: StateFlow<UbicacionEstimada?> = _ubicacion.asStateFlow()

    /** La llama la ruta `destino` al confirmar (6.4). */
    fun elegirDestino(lugar: LugarDestino) {
        _destino.value = lugar
    }

    /** La llama la ruta `inicio` antes de «Ubicarme» (solo ubicarse, sin destino). */
    fun quitarDestino() {
        _destino.value = null
    }

    /** La llama la ruta `ubicarme` al terminar el escaneo con un `200`. Devuelve lo guardado. */
    fun registrar(resultado: ResultadoUbicacion, rumboAlTerminar: Double?): UbicacionEstimada {
        val u = UbicacionEstimada(resultado, reloj(), rumboAlTerminar)
        _ubicacion.value = u
        return u
    }

    /** La ubicación si es vigente ([UbicacionEstimada.vigente]: alta o media y ≤ 2 min), o `null`. */
    fun ubicacionVigente(): UbicacionEstimada? = _ubicacion.value?.takeIf { it.vigente(reloj()) }

    /** `(lat, lng)` de la ubicación vigente, o `null`: el proveedor de `RemoteLugaresRepository` (ADR-FE-23). */
    fun posicionVigente(): Pair<Double, Double>? =
        ubicacionVigente()?.ubicado?.posicion?.let { it.lat to it.lng }

    /** Última posición conocida aunque no sea vigente (para calcular la declinación magnética), o `null`. */
    fun ultimaPosicion(): PosicionEstimada? = _ubicacion.value?.ubicado?.posicion

    fun limpiar() {
        _destino.value = null
        _ubicacion.value = null
    }
}

/** Holder único del proceso (como `SesionDeRecoleccion` para la recolección, ADR-FE-06). */
object SesionDeNavegacion : SesionNavegacion()
