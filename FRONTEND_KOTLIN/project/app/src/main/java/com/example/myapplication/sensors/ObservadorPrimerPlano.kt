package com.example.myapplication.sensors

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner

/**
 * Conecta un `Lifecycle` con el [InterruptorSensores] del [PdrTracker] (FE-2.3; extraído en FE-3.1 para probarlo en la
 * JVM): `ON_START` → [InterruptorSensores.alPrimerPlano] y `ON_STOP` → [InterruptorSensores.alSegundoPlano]; cada
 * cambio se pasa a [aplicar] (que registra o quita los sensores; `NINGUNO` también llega y no hace nada).
 *
 * Qué ciclo de vida se observa lo decide quien crea el tracker:
 * - el del **proceso** (`ProcessLifecycleOwner`, valor por defecto de `PdrTracker`): los sensores siguen a la app
 *   entera; lo usan la calibración y la recolección, cuyos trackers viven en ViewModels (ADR-FE-16);
 * - el de la **pantalla** (la entrada de la pila de navegación, `LocalLifecycleOwner` dentro de un `composable`): los
 *   sensores siguen a lo visible; lo usa el mapa público desde FE-3.1 (ADR-FE-22). Una entrada que queda en la pila
 *   sin ser la visible, o en una tarea en segundo plano, se queda en `CREATED` aunque el proceso vuelva al primer
 *   plano, así que sus sensores no vuelven (el hallazgo de FE-2.3).
 *
 * `addObserver` sobre un ciclo ya iniciado entrega `ON_CREATE`, `ON_START`… en el acto: sin rastreo pedido no cambian
 * nada.
 */
internal class ObservadorPrimerPlano(
    private val interruptor: InterruptorSensores,
    private val aplicar: (CambioSensores, String) -> Unit,
) : LifecycleEventObserver {

    override fun onStateChanged(source: LifecycleOwner, event: Lifecycle.Event) {
        when (event) {
            Lifecycle.Event.ON_START -> aplicar(interruptor.alPrimerPlano(), MOTIVO_PRIMER_PLANO)
            Lifecycle.Event.ON_STOP -> aplicar(interruptor.alSegundoPlano(), MOTIVO_SEGUNDO_PLANO)
            else -> Unit
        }
    }

    companion object {
        /** Textos del registro (`AppLog`, tag `Pdr`): la evidencia de FE-2.3 C5 los busca. */
        const val MOTIVO_PRIMER_PLANO = "primer plano"
        const val MOTIVO_SEGUNDO_PLANO = "segundo plano"
    }
}
