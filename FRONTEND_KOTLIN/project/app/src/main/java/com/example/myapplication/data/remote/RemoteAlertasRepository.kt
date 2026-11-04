package com.example.myapplication.data.remote

import android.content.Context
import com.example.myapplication.data.local.AlmacenAlertas
import com.example.myapplication.data.local.AlmacenAlertasArchivo
import com.example.myapplication.data.repository.AlertasRepository
import com.example.myapplication.data.repository.CambiosAlertas
import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.data.repository.EstadoAlertas
import com.example.myapplication.data.repository.ReglasAlertas
import com.example.myapplication.data.repository.ResultadoSincronizacion
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import com.example.myapplication.logs.AppLog
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/**
 * [AlertasRepository] «local primero» (FE-3.3): el estado vive en [almacen] (en la app, `files/alertas/editor.json`) y
 * se envía con `POST /v1/admin/alerts/sincronizar` (backend §5.5). Las escrituras locales y la aplicación de cada
 * respuesta van bajo un `Mutex`; las peticiones, fuera de él (se puede seguir editando mientras sincroniza).
 *
 * - [sincronizar]: copia los pendientes, los envía en lotes de [ReglasAlertas.LOTE] y aplica cada respuesta con
 *   [ReglasAlertas.confirmar] (un `ok` sale de pendientes solo si no cambió durante el envío; `error` queda marcado).
 *   Si un lote falla, lo de los anteriores ya quedó aplicado y la excepción sale. Después relee con [refrescar] (un
 *   fallo ahí no es un fallo de la sincronización: `releida = false`). Si el servidor aplicó algo, `cambios.avisar()`.
 * - No registra nada más que la línea `Api` de cada petición y, en [registrar], el resumen de cada sincronización
 *   (cuántos; nunca mensajes ni ids).
 */
class RemoteAlertasRepository(
    private val almacen: AlmacenAlertas,
    private val api: CampusApi = ClienteApi.api,
    private val cambios: ContadorCambios = CambiosAlertas,
    private val registrar: (String) -> Unit = { AppLog.i(TAG, it) },
) : AlertasRepository {

    private val mutex = Mutex()
    private val _estado = MutableStateFlow(EstadoAlertas())
    override val estado: StateFlow<EstadoAlertas> = _estado.asStateFlow()

    override suspend fun cargar() {
        mutex.withLock { asegurarCargado() }
    }

    override suspend fun guardar(alerta: Alerta) = cambiar { ReglasAlertas.registrar(it, OperacionAlerta.Upsert(alerta)) }

    override suspend fun mover(id: String, lat: Double, lng: Double) = cambiar { e ->
        val a = e.visibles.firstOrNull { it.id == id } ?: return@cambiar e
        ReglasAlertas.registrar(e, OperacionAlerta.Upsert(a.copy(lat = lat, lng = lng)))
    }

    override suspend fun eliminar(id: String) = cambiar { ReglasAlertas.registrar(it, OperacionAlerta.Eliminar(id)) }

    override suspend fun refrescar() {
        val dto = llamar { api.alertasAdmin() }
        val items = dto.items ?: throw RespuestaInesperadaException("GET /v1/admin/alerts: la respuesta no trae «items»")
        val lista = items.map { MapeoDatosApi.alerta(it) }.distinctBy { it.id }
        cambiar { it.copy(servidor = lista) }
    }

    override suspend fun refrescarPublicas() {
        val dto = llamar { api.alertasPublicas() }
        val alertas = dto.alertas ?: throw RespuestaInesperadaException("GET /v1/alerts: la respuesta no trae «alertas»")
        val publicas = alertas.map { MapeoDatosApi.alerta(it) }.distinctBy { it.id }
        cambiar { it.copy(servidor = ReglasAlertas.fusionarPublicas(it.servidor, publicas)) }
    }

    override suspend fun sincronizar(): ResultadoSincronizacion {
        val enviados = mutex.withLock { asegurarCargado(); _estado.value.pendientes }
        var aplicados = 0
        val rechazados = mutableListOf<String>()
        try {
            for (lote in enviados.chunked(ReglasAlertas.LOTE)) {
                val dto = llamar { api.sincronizarAlertas(SincronizarAlertasDto(lote.map(MapeoDatosApi::cambioAlerta))) }
                val resultados = dto.resultados
                    ?: throw RespuestaInesperadaException("POST /v1/admin/alerts/sincronizar: sin «resultados»")
                val ids = lote.mapTo(HashSet()) { it.id }
                val ok = resultados.filter { it.estado == "ok" }.mapNotNullTo(HashSet()) { it.id }.intersect(ids)
                val error = resultados.filter { it.estado == "error" }.mapNotNullTo(HashSet()) { it.id }.intersect(ids)
                cambiar { ReglasAlertas.confirmar(it, lote, ok, error) }
                aplicados += ok.size
                rechazados += error
            }
        } finally {
            if (aplicados > 0) cambios.avisar()
        }
        registrar("Alertas sincronizadas: ${enviados.size} enviadas, $aplicados aplicadas, ${rechazados.size} rechazadas")
        val releida = try {
            refrescar()
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            registrar("Alertas: no se pudo releer la lista tras sincronizar (${e.javaClass.simpleName})")
            false
        }
        return ResultadoSincronizacion(enviados.size, aplicados, rechazados, releida)
    }

    /** Aplica [f] al estado bajo el cerrojo, lo guarda en disco y solo entonces lo publica. */
    private suspend fun cambiar(f: (EstadoAlertas) -> EstadoAlertas) {
        mutex.withLock {
            asegurarCargado()
            val antes = _estado.value
            val nuevo = f(antes)
            if (nuevo == antes) return
            almacen.guardar(nuevo)
            _estado.value = nuevo
        }
    }

    /** Solo con el cerrojo tomado. */
    private suspend fun asegurarCargado() {
        if (_estado.value.cargado) return
        _estado.value = almacen.leer().copy(cargado = true)
    }

    companion object {
        /** Tag de `AppLog` de las alertas del editor. */
        const val TAG = "Alertas"
    }
}

/** El [AlertasRepository] único del proceso (7.4, 7.8 y 7.10 comparten estado). Usa `ClienteApi.api` al crearse. */
object Alertas {
    @Volatile
    private var repositorio: AlertasRepository? = null

    fun de(context: Context): AlertasRepository = repositorio ?: synchronized(this) {
        repositorio ?: RemoteAlertasRepository(
            almacen = AlmacenAlertasArchivo(
                File(context.applicationContext.filesDir, "alertas/editor.json"),
                registrar = { AppLog.w(RemoteAlertasRepository.TAG, it) },
            ),
        ).also { repositorio = it }
    }
}
