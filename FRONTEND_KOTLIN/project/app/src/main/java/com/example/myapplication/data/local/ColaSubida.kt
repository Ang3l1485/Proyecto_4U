package com.example.myapplication.data.local

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Qué está haciendo la cola (lo muestran 7.5 y el Panel). */
enum class FaseCola {
    INACTIVA,
    PREPARANDO,
    SUBIENDO,
    COMPLETANDO,

    /** El último recorrido que se intentó terminó bien. */
    COMPLETADA,

    /** Fallo transitorio (red, 5xx, 429, `complete` con pendientes): espera [EstadoCola.reintentoEnS] y reintenta. */
    SIN_CONEXION,

    /** Sin sesión (o vencida o rechazada): no reintenta hasta que alguien llame a `reanudar()` con sesión. */
    ESPERANDO_SESION,

    /** Fallo permanente de [EstadoCola.videoId] (no se reintenta en esta pasada). */
    ERROR,

    /** Fotos que no se pudieron re-codificar ([EstadoCola.fotosIlegibles]); el recorrido volvió a `sin_subir`. */
    FOTOS_ILEGIBLES,
}

data class EstadoCola(
    val fase: FaseCola = FaseCola.INACTIVA,
    /** Recorrido al que se refiere el estado (`null` en `INACTIVA` y `ESPERANDO_SESION`). */
    val videoId: String? = null,
    val hechas: Int = 0,
    val total: Int = 0,
    val mensaje: String? = null,
    /** Segundos hasta el siguiente intento (solo en `SIN_CONEXION`). */
    val reintentoEnS: Int? = null,
    val fotosIlegibles: List<String> = emptyList(),
) {
    val activa: Boolean get() = fase in setOf(FaseCola.PREPARANDO, FaseCola.SUBIENDO, FaseCola.COMPLETANDO, FaseCola.SIN_CONEXION)
}

/**
 * Cola de subida de recorridos (FE-2.1, ARCHITECTURE §5.10 y ADR-FE-19). **Única por proceso** (la crea `Subidas`).
 * Lo pendiente vive en disco (los manifests: `subida_estado = subiendo`), así que sobrevive al cierre de la app; el
 * trabajo corre en una corrutina de [alcance] mientras el proceso viva.
 *
 * - [subir] (botón «Subir y procesar» de 7.5) añade un recorrido y arranca o despierta la cola.
 * - [reanudar] (al abrir el Panel o 7.5) retoma los `finalizado` con `subida_estado = subiendo`.
 * - Sin sesión ([haySesion] falso) no llama al backend: `ESPERANDO_SESION`, sin reintentos en bucle; el siguiente
 *   [reanudar] con sesión sigue. Si la sesión se pierde a mitad (`401` o `SIN_SESION_LOCAL`), igual.
 * - Un fallo transitorio espera [esperasMs] (5 s, 10 s, 20 s, 40 s, 60 s, 2 min y 5 min; la última se repite) y
 *   reintenta; [subir] o [reanudar] cortan la espera.
 * - Un fallo permanente deja el recorrido en `subiendo` y no se reintenta en esta pasada: el siguiente [reanudar]
 *   (otra apertura del Panel o de 7.5) lo intenta una vez más.
 */
class ColaSubida(
    private val almacen: AlmacenRecorridos,
    private val ejecutor: EjecutorSubida,
    private val haySesion: () -> Boolean,
    private val alcance: CoroutineScope,
    private val registrar: (String) -> Unit = {},
    private val esperasMs: List<Long> = ESPERAS_MS,
) {
    private val _estado = MutableStateFlow(EstadoCola())
    val estado: StateFlow<EstadoCola> = _estado.asStateFlow()

    /** Sube cada vez que cambia algo en disco (una foto subida, un estado): 7.5 relee su manifest. */
    private val _cambios = MutableStateFlow(0)
    val cambios: StateFlow<Int> = _cambios.asStateFlow()

    /** Sube cada vez que termina un intento sobre un recorrido (para el `VideoRepository` compuesto: menos recargas). */
    private val _cambiosVideos = MutableStateFlow(0)
    val cambiosVideos: StateFlow<Int> = _cambiosVideos.asStateFlow()

    // Protegidos con synchronized(this).
    private val pedidos = linkedSetOf<String>()
    private val fallidos = mutableSetOf<String>() // fallos permanentes de la pasada en curso
    private val despertar = Channel<Unit>(Channel.CONFLATED)
    private var trabajo: Job? = null

    /** Pide subir [videoId] (si ya estaba en la cola, no se duplica; si falló en esta pasada, se reintenta). */
    fun subir(videoId: String) {
        synchronized(this) {
            pedidos += videoId
            fallidos -= videoId
        }
        lanzarODespertar()
    }

    /** Retoma lo que quedó `subiendo` (al abrir el Panel o 7.5). Si la cola ya corre, corta su espera. */
    fun reanudar() = lanzarODespertar()

    private fun lanzarODespertar() {
        synchronized(this) {
            if (trabajo?.isActive == true) {
                despertar.trySend(Unit)
            } else {
                trabajo = alcance.launch { procesar() }
            }
        }
    }

    /** Una pasada completa de la cola (la llama [lanzarODespertar]; las pruebas la llaman directamente). */
    suspend fun procesar() {
        var intento = 0
        synchronized(this) { fallidos.clear() }
        while (true) {
            if (!haySesion()) {
                publicar(EstadoCola(FaseCola.ESPERANDO_SESION, mensaje = MENSAJE_SIN_SESION))
                registrar("cola: sin sesión, espera al login")
                return
            }
            val enDisco = almacen.idsEnSubida()
            val ids = synchronized(this) { (pedidos.toList() + enDisco).distinct().filter { it !in fallidos } }
            if (ids.isEmpty()) {
                // Salir y soltar `trabajo` de forma atómica: un `subir()` que llegue justo ahora lanza otra pasada.
                val salir = synchronized(this) { pedidos.none { it !in fallidos }.also { if (it) trabajo = null } }
                if (!salir) continue
                if (_estado.value.activa) publicar(EstadoCola())
                return
            }
            var transitorio: String? = null
            for (id in ids) {
                val resultado = ejecutor.ejecutar(id) { p ->
                    val fase = when (p.fase) {
                        FaseSubida.PREPARANDO -> FaseCola.PREPARANDO
                        FaseSubida.SUBIENDO -> FaseCola.SUBIENDO
                        FaseSubida.COMPLETANDO -> FaseCola.COMPLETANDO
                    }
                    publicar(EstadoCola(fase, id, p.hechas, p.total))
                    _cambios.update { it + 1 }
                }
                _cambios.update { it + 1 }
                _cambiosVideos.update { it + 1 }
                when (resultado) {
                    is ResultadoSubida.Completada -> {
                        quitarPedido(id)
                        intento = 0
                        val n = resultado.conteo?.total ?: 0
                        publicar(EstadoCola(FaseCola.COMPLETADA, id, n, n))
                    }
                    is ResultadoSubida.EsperandoSesion -> {
                        publicar(EstadoCola(FaseCola.ESPERANDO_SESION, mensaje = MENSAJE_SIN_SESION))
                        registrar("cola: sesión perdida (${resultado.codigo}), espera al login")
                        return
                    }
                    is ResultadoSubida.SinConexion -> {
                        transitorio = resultado.motivo
                        break // los demás fallarían igual: se espera y se reintenta todo
                    }
                    is ResultadoSubida.Pendiente -> transitorio = "El servidor aún no confirma todas las fotos"
                    is ResultadoSubida.Fallida -> {
                        quitarPedido(id)
                        synchronized(this) { fallidos += id }
                        publicar(EstadoCola(FaseCola.ERROR, id, mensaje = resultado.motivo))
                        registrar("cola: $id falló sin reintento: ${resultado.motivo}")
                    }
                    is ResultadoSubida.FotosIlegibles -> {
                        quitarPedido(id)
                        synchronized(this) { fallidos += id }
                        publicar(
                            EstadoCola(
                                FaseCola.FOTOS_ILEGIBLES, id,
                                mensaje = "No se pudieron leer ${resultado.ids.size} foto(s): descártalas y vuelve a subir",
                                fotosIlegibles = resultado.ids,
                            ),
                        )
                    }
                }
            }
            val motivo = transitorio ?: continue
            val espera = esperasMs[intento.coerceAtMost(esperasMs.lastIndex)]
            intento++
            val actual = _estado.value
            publicar(
                EstadoCola(
                    FaseCola.SIN_CONEXION, actual.videoId, actual.hechas, actual.total,
                    mensaje = motivo, reintentoEnS = ((espera + 999) / 1000).toInt(),
                ),
            )
            registrar("cola: reintento en ${espera / 1000} s ($motivo)")
            withTimeoutOrNull(espera) { despertar.receive() }
        }
    }

    private fun quitarPedido(id: String) = synchronized(this) { pedidos -= id }

    private fun publicar(e: EstadoCola) {
        _estado.value = e
    }

    companion object {
        val ESPERAS_MS = listOf(5_000L, 10_000L, 20_000L, 40_000L, 60_000L, 120_000L, 300_000L)
        const val MENSAJE_SIN_SESION = "Inicia sesión para seguir subiendo"
    }
}
