package com.example.myapplication.sensors

import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.1 (apoyo de C2 y hallazgo de FE-2.3): con el ciclo de vida de la **pantalla** (la entrada de la pila de
 * navegación), el PDR del mapa público deja de leer sensores cuando el mapa no es lo visible, aunque el proceso vuelva
 * al primer plano. `LifecycleRegistry.createUnsafe` no comprueba el hilo principal, así que corre en la JVM.
 */
class ObservadorPrimerPlanoTest {

    /** Un `LifecycleOwner` con su registro, como una entrada de la pila o el proceso. */
    private class Ciclo : LifecycleOwner {
        val registro: LifecycleRegistry = LifecycleRegistry.createUnsafe(this)
        override val lifecycle: Lifecycle get() = registro
        fun a(estado: Lifecycle.State) {
            registro.currentState = estado
        }
    }

    /** Lo que haría `PdrTracker`: un interruptor, un observador y los cambios que llegarían a los sensores. */
    private class Tracker(ciclo: Ciclo) {
        val interruptor = InterruptorSensores(
            enPrimerPlano = ciclo.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED),
        )
        val cambios = mutableListOf<String>()
        val observador = ObservadorPrimerPlano(interruptor) { cambio, motivo -> anotar(cambio, motivo) }

        init {
            ciclo.lifecycle.addObserver(observador)
        }

        fun anotar(cambio: CambioSensores, motivo: String) {
            if (cambio != CambioSensores.NINGUNO) cambios += "$cambio ($motivo)"
        }

        fun iniciar() = anotar(interruptor.iniciar(), "iniciar")
    }

    @Test
    fun pantallaVisible_registra_yAlTaparseLaQuita() {
        val pantalla = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val t = Tracker(pantalla)
        t.iniciar()
        pantalla.a(Lifecycle.State.CREATED) // otra pantalla encima, o la app en segundo plano
        pantalla.a(Lifecycle.State.RESUMED) // vuelve a ser la visible
        assertEquals(
            listOf("REGISTRAR (iniciar)", "QUITAR (segundo plano)", "REGISTRAR (primer plano)"),
            t.cambios,
        )
    }

    @Test
    fun mapaEnLaPilaSinSerVisible_noVuelveARegistrar_aunqueElProcesoVuelva() {
        // El hallazgo de FE-2.3 (21:48:35): el mapa quedó en una tarea en segundo plano y la app volvió al primer plano
        // por otra (abrirla desde el ícono mostró Inicio). Con el ciclo del proceso, sus sensores volvían; con el de la
        // pantalla, no.
        val proceso = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val pantalla = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val conPantalla = Tracker(pantalla)
        val conProceso = Tracker(proceso)
        conPantalla.iniciar()
        conProceso.iniciar()

        proceso.a(Lifecycle.State.CREATED) // la app pasa a segundo plano…
        pantalla.a(Lifecycle.State.CREATED)
        proceso.a(Lifecycle.State.RESUMED) // …y vuelve, pero el mapa sigue tapado (su entrada se queda en CREATED)

        assertEquals(listOf("REGISTRAR (iniciar)", "QUITAR (segundo plano)"), conPantalla.cambios)
        assertFalse(conPantalla.interruptor.registrados)
        assertTrue(conPantalla.interruptor.pedido) // el rastreo sigue pedido: vuelve si el mapa vuelve a verse
        // Con el ciclo del proceso (lo de FE-2.3) se habrían vuelto a registrar:
        assertEquals("REGISTRAR (primer plano)", conProceso.cambios.last())
    }

    @Test
    fun pantallaDestruida_quitaLosSensoresUnaSolaVez() {
        // Atrás desde el mapa: la entrada sale de la pila (ON_PAUSE, ON_STOP, ON_DESTROY).
        val pantalla = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val t = Tracker(pantalla)
        t.iniciar()
        pantalla.a(Lifecycle.State.DESTROYED)
        assertEquals(listOf("REGISTRAR (iniciar)", "QUITAR (segundo plano)"), t.cambios)
        assertFalse(t.interruptor.registrados)
    }

    @Test
    fun creadoAntesDeVerse_esperaAlOnStart() {
        // Al navegar, la primera composición puede llegar con la entrada aún en CREATED (transición).
        val pantalla = Ciclo().apply { a(Lifecycle.State.CREATED) }
        val t = Tracker(pantalla)
        assertFalse(t.interruptor.enPrimerPlano)
        t.iniciar()
        assertTrue(t.cambios.isEmpty()) // pedido, pero sin sensores todavía
        pantalla.a(Lifecycle.State.RESUMED)
        assertEquals(listOf("REGISTRAR (primer plano)"), t.cambios)
    }

    @Test
    fun observarUnCicloYaIniciado_sinRastreoPedido_noTocaLosSensores() {
        val pantalla = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val t = Tracker(pantalla) // addObserver entrega ON_CREATE, ON_START y ON_RESUME en el acto
        pantalla.a(Lifecycle.State.CREATED)
        pantalla.a(Lifecycle.State.RESUMED)
        assertTrue(t.cambios.isEmpty())
        assertTrue(t.interruptor.enPrimerPlano)
    }

    @Test
    fun quitarElObservador_dejaDeSeguirAlCiclo() {
        // `PdrTracker.liberar()` hace `removeObserver`: después, el ciclo ya no toca los sensores.
        val pantalla = Ciclo().apply { a(Lifecycle.State.RESUMED) }
        val t = Tracker(pantalla)
        t.iniciar()
        t.anotar(t.interruptor.detener(), "detener")
        pantalla.lifecycle.removeObserver(t.observador)
        pantalla.a(Lifecycle.State.CREATED)
        pantalla.a(Lifecycle.State.RESUMED)
        assertEquals(listOf("REGISTRAR (iniciar)", "QUITAR (detener)"), t.cambios)
    }
}
