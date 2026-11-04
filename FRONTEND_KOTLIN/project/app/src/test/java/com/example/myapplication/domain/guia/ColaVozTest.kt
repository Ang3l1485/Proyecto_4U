package com.example.myapplication.domain.guia

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-5.3: la cola de voz de la guía (esperar al texto actual, prioritarios que cortan, tope y token). */
class ColaVozTest {

    private val dichos = mutableListOf<String>()
    private val terminar = mutableListOf<() -> Unit>()
    private val cola = ColaVoz({ texto, alTerminar -> dichos += texto; terminar += alTerminar }, maximo = 2)

    @Test
    fun normalEsperaYPrioritarioCorta() {
        cola.decir("uno")
        cola.decir("dos")
        assertEquals(listOf("uno"), dichos)
        assertEquals(listOf("dos"), cola.pendientes)
        terminar.last().invoke() // termina «uno»
        assertEquals(listOf("uno", "dos"), dichos)
        cola.decir("tres")
        cola.decir("¡gira!", prioritario = true)
        assertEquals(listOf("uno", "dos", "¡gira!"), dichos)
        assertEquals(emptyList<String>(), cola.pendientes)
        // El alTerminar de «dos» (cortado) llega tarde: se ignora.
        terminar[1].invoke()
        assertTrue(cola.hablando)
        terminar.last().invoke()
        assertFalse(cola.hablando)
    }

    @Test
    fun topeDeEsperaYVaciar() {
        cola.decir("a")
        cola.decir("b")
        cola.decir("c")
        cola.decir("d")
        assertEquals(listOf("c", "d"), cola.pendientes)
        cola.vaciar()
        assertFalse(cola.hablando)
        terminar.last().invoke() // el de «a», ya vaciado: no dice nada más
        assertEquals(listOf("a"), dichos)
        cola.decir("e")
        assertEquals(listOf("a", "e"), dichos)
    }
}
