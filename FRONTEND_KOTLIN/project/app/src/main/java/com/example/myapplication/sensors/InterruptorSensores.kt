package com.example.myapplication.sensors

/** Qué debe hacer [PdrTracker] con sus sensores tras un cambio de [InterruptorSensores]. */
internal enum class CambioSensores { REGISTRAR, QUITAR, NINGUNO }

/**
 * Lógica pura (sin Android) de cuándo deben estar registrados los sensores del [PdrTracker] (FE-2.3): solo si se pidió
 * rastrear ([iniciar] sin [detener] después) **y** la app está en primer plano. Así el PDR deja de leer sensores en
 * segundo plano sin que cada pantalla tenga que acordarse, y vuelve solo al primer plano si el rastreo seguía pedido.
 *
 * Cada operación devuelve el cambio que hay que aplicar a los sensores.
 */
internal class InterruptorSensores(enPrimerPlano: Boolean = true) {

    /** Se pidió rastrear: [iniciar] sin [detener] después. Es lo que publica `PdrEstado.activo`. */
    var pedido: Boolean = false
        private set

    var enPrimerPlano: Boolean = enPrimerPlano
        private set

    /** Los sensores deben estar registrados ahora. */
    val registrados: Boolean get() = pedido && enPrimerPlano

    fun iniciar(): CambioSensores = cambiar { pedido = true }

    fun detener(): CambioSensores = cambiar { pedido = false }

    fun alPrimerPlano(): CambioSensores = cambiar { enPrimerPlano = true }

    fun alSegundoPlano(): CambioSensores = cambiar { enPrimerPlano = false }

    private inline fun cambiar(accion: () -> Unit): CambioSensores {
        val antes = registrados
        accion()
        val ahora = registrados
        return when {
            !antes && ahora -> CambioSensores.REGISTRAR
            antes && !ahora -> CambioSensores.QUITAR
            else -> CambioSensores.NINGUNO
        }
    }
}
