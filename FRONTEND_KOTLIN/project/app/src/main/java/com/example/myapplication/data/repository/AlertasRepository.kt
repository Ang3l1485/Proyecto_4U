package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import kotlinx.coroutines.flow.StateFlow

/**
 * Alertas de la administración, «local primero» (FE-3.3; vistas 7.4, 7.8, 7.9 y 7.10). Guardar, mover o eliminar se
 * aplica al instante en el teléfono (y en disco) y queda como operación pendiente; [sincronizar] la envía con
 * `POST /v1/admin/alerts/sincronizar` (backend §5.5). Una sola instancia por proceso (`Alertas.de(context)`): así 7.4,
 * 7.8 y 7.10 ven lo mismo.
 *
 * Excepciones (las de `llamar`, ARCHITECTURE §5.10): sin red `SinConexionException`; sesión perdida
 * `ApiException(FalloApi.SesionVencida)`; otro error `ApiException`; `2xx` fuera de contrato
 * `RespuestaInesperadaException`. Las escrituras locales pueden lanzar `IOException` (disco).
 */
interface AlertasRepository {
    /** Lo que hay en el teléfono: la última lista del servidor y los pendientes. */
    val estado: StateFlow<EstadoAlertas>

    /** Lee el disco (una sola vez por proceso; después no hace nada). No llama al backend. */
    suspend fun cargar()

    /** Crea o reemplaza la alerta en local y deja un `upsert` pendiente. No llama al backend. */
    suspend fun guardar(alerta: Alerta)

    /** Mueve una alerta visible y deja un `upsert` pendiente (sin la alerta, nada). No llama al backend. */
    suspend fun mover(id: String, lat: Double, lng: Double)

    /** Quita la alerta en local y deja un `eliminar` pendiente. No llama al backend. */
    suspend fun eliminar(id: String)

    /** `GET /v1/admin/alerts` (protegida): reemplaza la lista del servidor; los pendientes se siguen viendo encima. */
    suspend fun refrescar()

    /**
     * `GET /v1/alerts` (pública, sin sesión: la usa 7.4 para no arriesgar un `401` que la saque de la pila, ADR-FE-31):
     * fusiona las activas con la lista del servidor ([ReglasAlertas.fusionarPublicas]).
     */
    suspend fun refrescarPublicas()

    /** Envía los pendientes (lotes de 100), aplica cada resultado y relee la lista (`GET /v1/admin/alerts`). */
    suspend fun sincronizar(): ResultadoSincronizacion
}

/**
 * Estado local de las alertas. [servidor]: la última lista conocida del backend (con los cambios ya confirmados);
 * [pendientes]: una operación por id, en el orden del último cambio; [rechazadas]: ids cuyo último envío dio
 * `estado = error` (`VALIDACION`) y que siguen pendientes hasta que el admin las corrija.
 */
data class EstadoAlertas(
    val servidor: List<Alerta> = emptyList(),
    val pendientes: List<OperacionAlerta> = emptyList(),
    val rechazadas: Set<String> = emptySet(),
    val cargado: Boolean = false,
) {
    /** Lo que se dibuja y se lista: [servidor] con [pendientes] aplicados encima. */
    val visibles: List<Alerta> get() = ReglasAlertas.aplicar(servidor, pendientes)

    val idsPendientes: Set<String> get() = pendientes.mapTo(LinkedHashSet()) { it.id }
}

/** Lo que pasó al sincronizar: cuántos cambios se enviaron y aplicaron, cuáles rechazó el backend y si se releyó. */
data class ResultadoSincronizacion(
    val enviados: Int,
    val aplicados: Int,
    val rechazados: List<String>,
    val releida: Boolean,
)

/** Reglas puras de los pendientes de alertas (FE-3.3; `ReglasAlertasTest`). */
object ReglasAlertas {

    /** Máximo de cambios por `sincronizar` (backend `CAMBIOS_MAX`). */
    const val LOTE = 100

    /** Una operación por id, la última: quita la anterior del mismo id y añade [op] al final. */
    fun registrar(estado: EstadoAlertas, op: OperacionAlerta): EstadoAlertas = estado.copy(
        pendientes = estado.pendientes.filterNot { it.id == op.id } + op,
        rechazadas = estado.rechazadas - op.id,
    )

    /** [servidor] con [pendientes] aplicados en orden (un `upsert` reemplaza por id o se añade; `eliminar` quita). */
    fun aplicar(servidor: List<Alerta>, pendientes: List<OperacionAlerta>): List<Alerta> {
        if (pendientes.isEmpty()) return servidor
        val porId = LinkedHashMap<String, Alerta>()
        servidor.forEach { porId[it.id] = it }
        pendientes.forEach { aplicarUna(porId, it) }
        return porId.values.toList()
    }

    private fun aplicarUna(porId: MutableMap<String, Alerta>, op: OperacionAlerta) {
        when (op) {
            is OperacionAlerta.Upsert -> porId[op.id] = op.alerta
            is OperacionAlerta.Eliminar -> porId.remove(op.id)
        }
    }

    /**
     * Aplica la respuesta de `sincronizar` a lo que se envió ([enviados]): cada id en [ok] pasa a la lista del servidor y
     * sale de los pendientes **solo si** su operación sigue siendo la enviada (si el admin la cambió mientras tanto, la
     * nueva sigue pendiente); cada id en [rechazados] queda pendiente y marcado. Ids que no se enviaron se ignoran.
     */
    fun confirmar(
        estado: EstadoAlertas,
        enviados: List<OperacionAlerta>,
        ok: Set<String>,
        rechazados: Set<String>,
    ): EstadoAlertas {
        val servidor = LinkedHashMap<String, Alerta>()
        estado.servidor.forEach { servidor[it.id] = it }
        var pendientes = estado.pendientes
        var marcadas = estado.rechazadas
        for (op in enviados) {
            val actual = pendientes.firstOrNull { it.id == op.id }
            when (op.id) {
                in ok -> {
                    aplicarUna(servidor, op)
                    if (actual == op) pendientes = pendientes - op
                    marcadas = marcadas - op.id
                }
                in rechazados -> if (actual == op) marcadas = marcadas + op.id
            }
        }
        return estado.copy(servidor = servidor.values.toList(), pendientes = pendientes, rechazadas = marcadas)
    }

    /**
     * Lista del servidor tras leer `GET /v1/alerts` (solo activas y sin borrar): las [publicas] reemplazan a las que
     * había, y de las anteriores se conservan solo las **inactivas** que no vinieron (la ruta pública no las trae). Una
     * activa que ya no viene se borró (o se desactivó) en el servidor y sale.
     */
    fun fusionarPublicas(servidor: List<Alerta>, publicas: List<Alerta>): List<Alerta> {
        val ids = publicas.mapTo(HashSet()) { it.id }
        return publicas + servidor.filter { !it.activa && it.id !in ids }
    }
}

/**
 * Cambios de alertas confirmados por el backend en este proceso (FE-3.3): los avisa la sincronización cuando el
 * servidor aplicó algo. Lo mira el Panel para recargar «Alertas activas» al volver. Solo memoria.
 */
object CambiosAlertas : ContadorCambios()
