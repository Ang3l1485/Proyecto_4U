package com.example.myapplication.session

import com.example.myapplication.domain.model.Sesion
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow

/** Por qué una petición protegida se quedó sin sesión (lo recibe `onSinSesion`). */
sealed interface MotivoSinSesion {
    /** No había sesión guardada o su `expira_en` ya pasó: la petición no salió del teléfono. */
    data object SinSesionLocal : MotivoSinSesion

    /** El backend respondió `401` con [codigo] = `TOKEN_EXPIRADO`, `TOKEN_INVALIDO` o `NO_AUTENTICADO` (backend §5.2). */
    data class Rechazada(val codigo: String) : MotivoSinSesion
}

/**
 * Lo que hace la app cuando una ruta `/v1/admin/…` o `/v1/collect/…` se queda sin sesión (FE-1.2, ARCHITECTURE §5.3 y
 * §5.10). Lógica pura (sin Android): la usa `SesionInterceptor` de `data/remote/` y se prueba en `SesionVencidaTest`.
 *
 * - Antes de enviar: [sesionParaPeticion] devuelve la sesión vigente; sin sesión (o vencida) llama a [onSinSesion]
 *   con [MotivoSinSesion.SinSesionLocal] y la petición no se envía.
 * - Tras un `401` de sesión: [rechazada] cierra la sesión (si sigue siendo la del token enviado) y llama a
 *   [onSinSesion] con [MotivoSinSesion.Rechazada].
 *
 * Nunca lanza: si el almacén cifrado falla, cuenta como «sin sesión». [registrar] recibe una línea sin token ni correo.
 * Se llama desde los hilos de OkHttp: [onSinSesion] no debe tocar la interfaz directamente (la app usa [EventosSesion]).
 */
class VigilanteSesion(
    private val session: SessionManager,
    private val onSinSesion: (MotivoSinSesion) -> Unit,
    private val registrar: (String) -> Unit = {},
) {

    /** Token de la sesión vigente, o `null` (sin sesión, vencida o almacén roto). No llama al backend. */
    fun token(): String? = leer()?.token

    /** La sesión con la que se envía [peticion] (`"GET /v1/admin/stats"`), o `null` tras avisar con [onSinSesion]. */
    fun sesionParaPeticion(peticion: String): Sesion? {
        val sesion = leer()
        if (sesion == null) {
            registrar("$peticion no se envía: sin sesión o vencida")
            onSinSesion(MotivoSinSesion.SinSesionLocal)
        }
        return sesion
    }

    /**
     * El backend rechazó con [codigo] la petición [peticion], enviada con [tokenEnviado]. Si mientras tanto se guardó
     * otra sesión (otro token), no hace nada: el rechazo era de la anterior.
     */
    fun rechazada(codigo: String, tokenEnviado: String, peticion: String) {
        val actual = leer()
        if (actual != null && actual.token != tokenEnviado) {
            registrar("$peticion -> 401 $codigo con un token anterior: la sesión actual se conserva")
            return
        }
        runCatching { session.cerrarSesion() }
            .onFailure { registrar("$peticion -> 401 $codigo: no se pudo borrar la sesión (${it.javaClass.simpleName})") }
        registrar("$peticion -> 401 $codigo: sesión cerrada")
        onSinSesion(MotivoSinSesion.Rechazada(codigo))
    }

    private fun leer(): Sesion? = try {
        session.obtener()
    } catch (e: Exception) {
        registrar("no se pudo leer la sesión (${e.javaClass.simpleName}): cuenta como sin sesión")
        null
    }
}

/**
 * Eventos «sin sesión» de toda la app (FE-1.2). `MyApp` conecta [emitir] como `onSinSesion` del [VigilanteSesion] de
 * `ClienteApi`; `AppNav` recoge [sinSesion] y, si la ruta actual es `admin/…`, navega a `login` sin cerrar la app.
 * `Channel.CONFLATED`: un solo colector; si llega un evento sin colector, se guarda el último.
 */
object EventosSesion {
    private val canal = Channel<MotivoSinSesion>(Channel.CONFLATED)

    val sinSesion: Flow<MotivoSinSesion> = canal.receiveAsFlow()

    fun emitir(motivo: MotivoSinSesion) {
        canal.trySend(motivo)
    }
}
