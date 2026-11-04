package com.example.myapplication.data.remote

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import com.example.myapplication.data.local.AlmacenCacheAlertas
import com.example.myapplication.data.local.AlmacenCacheAlertasArchivo
import com.example.myapplication.data.local.CachePublica
import com.example.myapplication.data.local.ReglasCacheAlertas
import com.example.myapplication.logs.AppLog
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/** Lo que hizo una sincronización de la caché pública (para el registro y las pruebas). */
data class SincronizacionPublica(
    val completa: Boolean,
    val desde: String?,
    val recibidas: Int,
    val eliminadas: Int,
    val total: Int,
    val generadoEn: String,
)

/**
 * Caché de las alertas públicas con sincronización por diferencias (FE-3.6; ARCHITECTURE §5.10, «Alertas sin conexión»;
 * ADR-FE-40). Contrato: backend §5.3 `GET /v1/alerts` (pública: sin `Authorization`, nunca lleva a Login) y §4.11, «Para
 * la app». Sin estado de Android: `CacheAlertasPublicasTest` (MockWebServer).
 *
 * - [cargar]: lee el disco una vez y publica en [estado].
 * - [sincronizar]: `GET /v1/alerts` (sin `desde` la primera vez o sin `generado_en` guardado; si no,
 *   `?desde=<generado_en guardado>` tal cual), aplica la respuesta con [ReglasCacheAlertas], guarda en disco y
 *   **después** publica. No hace nada (devuelve `null`) si otra sincronización está en curso o si la última correcta fue
 *   hace menos de [INTERVALO_MS] (salvo `forzar`). Un `422` con `desde` (fecha que el backend no acepta) repite una vez
 *   sin `desde` (foto completa). Lanza los errores de `llamar` (§5.10) y `RespuestaInesperadaException` si falta
 *   `generado_en`, `completo` o `alertas`; la caché queda como estaba.
 * - La última sincronización correcta vive en memoria: cada proceso nuevo sincroniza al arrancar.
 */
class CacheAlertasPublicas(
    private val almacen: AlmacenCacheAlertas,
    private val api: CampusApi = ClienteApi.api,
    private val reloj: () -> Long = { System.nanoTime() / 1_000_000 },
    private val registrar: (String) -> Unit = { AppLog.i(TAG, it) },
) {
    private val _estado = MutableStateFlow(CachePublica())
    val estado: StateFlow<CachePublica> = _estado.asStateFlow()

    private val cerrojoDisco = Mutex()
    private val enCurso = Mutex()

    @Volatile
    private var ultimoExitoMs: Long? = null

    /** Lee el disco la primera vez (después devuelve lo que hay en memoria). */
    suspend fun cargar(): CachePublica = cerrojoDisco.withLock {
        if (!_estado.value.cargada) _estado.value = almacen.leer().copy(cargada = true)
        _estado.value
    }

    /** ¿Toca sincronizar? (nunca se sincronizó en este proceso, o la última correcta fue hace [INTERVALO_MS] o más). */
    fun haceFalta(): Boolean = ultimoExitoMs?.let { reloj() - it >= INTERVALO_MS } ?: true

    suspend fun sincronizar(motivo: String, forzar: Boolean = false): SincronizacionPublica? {
        if (!forzar && !haceFalta()) return null
        if (!enCurso.tryLock()) return null
        try {
            val actual = cargar()
            val desde = actual.generadoEn
            val dto = try {
                llamar { api.alertasPublicas(desde) }
            } catch (e: ApiException) {
                if (desde == null || e.fallo !is FalloApi.Validacion) throw e
                registrar("Alertas públicas: el backend no aceptó desde=$desde (${e.http}); se pide la foto completa")
                llamar { api.alertasPublicas(null) }
            }
            val generadoEn = dto.generadoEn?.takeIf { it.isNotBlank() }
                ?: throw RespuestaInesperadaException("GET /v1/alerts: la respuesta no trae «generado_en»")
            val completo = dto.completo
                ?: throw RespuestaInesperadaException("GET /v1/alerts: la respuesta no trae «completo»")
            val recibidas = (dto.alertas ?: throw RespuestaInesperadaException("GET /v1/alerts: la respuesta no trae «alertas»"))
                .map { MapeoDatosApi.alerta(it) }
            val eliminadas = dto.eliminadas.orEmpty()
            val nueva = cerrojoDisco.withLock {
                val c = CachePublica(
                    alertas = ReglasCacheAlertas.aplicar(_estado.value.alertas, completo, recibidas, eliminadas),
                    generadoEn = generadoEn,
                    cargada = true,
                )
                almacen.guardar(c)
                _estado.value = c
                c
            }
            ultimoExitoMs = reloj()
            val r = SincronizacionPublica(
                completa = completo,
                desde = if (completo) null else desde,
                recibidas = recibidas.size,
                eliminadas = eliminadas.size,
                total = nueva.alertas.size,
                generadoEn = generadoEn,
            )
            registrar(lineaSincronizada(motivo, r))
            return r
        } finally {
            enCurso.unlock()
        }
    }

    companion object {
        const val TAG = "AlertasPublicas"

        /** Como mucho una sincronización cada 5 min (salvo `forzar`), ARCHITECTURE §5.10. */
        const val INTERVALO_MS = 300_000L

        /**
         * Línea del registro (la lee `validate36.py`, no cambiar su forma sin cambiar `PATRON_SINCRONIZADA`):
         * `Alertas públicas sincronizadas (<motivo>): completa, R recibidas, E eliminadas, N en caché (generado_en <t>)`
         * o `…: diferencias desde <t0>, …`. Sin mensajes ni ids.
         */
        fun lineaSincronizada(motivo: String, r: SincronizacionPublica): String {
            val tipo = if (r.completa) "completa" else "diferencias desde ${r.desde}"
            return "Alertas públicas sincronizadas ($motivo): $tipo, ${r.recibidas} recibidas, ${r.eliminadas} eliminadas, " +
                "${r.total} en caché (generado_en ${r.generadoEn})"
        }
    }
}

/**
 * La caché pública de la app (una por proceso) y sus disparadores (FE-3.6, ADR-FE-40). [iniciar] lo llama `MyApp`:
 * lee el disco y sincroniza **al pasar a primer plano** (también al arrancar), **cada 5 min mientras está en primer
 * plano** y **al volver la conexión** (`ConnectivityManager.registerDefaultNetworkCallback`; con la regla de los 5 min,
 * así que solo pide si la última correcta fue hace 5 min o más, p. ej. tras un fallo sin red). Un fallo solo deja una
 * línea `AlertasPublicas` («no se pudo sincronizar»): la caché sigue sirviendo sin red.
 */
object AlertasPublicas {
    @Volatile
    private var cache: CacheAlertasPublicas? = null
    private val ambito = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var bucle: Job? = null

    fun de(context: Context): CacheAlertasPublicas = cache ?: synchronized(this) {
        cache ?: CacheAlertasPublicas(
            almacen = AlmacenCacheAlertasArchivo(
                File(context.applicationContext.filesDir, "alertas/${AlmacenCacheAlertasArchivo.NOMBRE}"),
                registrar = { AppLog.w(CacheAlertasPublicas.TAG, it) },
            ),
        ).also { cache = it }
    }

    /** Desde `MyApp.onCreate` (hilo principal). Nunca lanza. */
    fun iniciar(context: Context) {
        val c = de(context)
        ambito.launch { runCatching { c.cargar() } }
        runCatching {
            ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) {
                    bucle?.cancel()
                    bucle = ambito.launch {
                        intentar(c, "primer plano", forzar = false)
                        while (isActive) {
                            delay(CacheAlertasPublicas.INTERVALO_MS)
                            intentar(c, "cada 5 min", forzar = true)
                        }
                    }
                }

                override fun onStop(owner: LifecycleOwner) {
                    bucle?.cancel()
                    bucle = null
                }
            })
        }.onFailure { AppLog.w(CacheAlertasPublicas.TAG, "Alertas públicas: sin disparador de primer plano", it) }
        runCatching {
            val cm = context.applicationContext.getSystemService(ConnectivityManager::class.java)
            cm?.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    ambito.launch { intentar(c, "conexión", forzar = false) }
                }
            })
        }.onFailure { AppLog.w(CacheAlertasPublicas.TAG, "Alertas públicas: sin disparador de conexión", it) }
    }

    private suspend fun intentar(c: CacheAlertasPublicas, motivo: String, forzar: Boolean) {
        try {
            c.sincronizar(motivo, forzar)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            AppLog.w(CacheAlertasPublicas.TAG, "Alertas públicas: no se pudo sincronizar ($motivo): ${e.javaClass.simpleName}")
        }
    }
}
