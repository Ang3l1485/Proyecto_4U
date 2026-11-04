package com.example.myapplication.ui.inicio

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `ComandoParser` (menú hablado de Inicio). FE-3.1 añade el comando «mapa» (apoyo de C2: abrir el mapa público con la
 * voz) y separa las palabras también por signos. Lo que ya hacía (uno, dos y sus fragmentos) no cambia.
 */
class ComandoParserTest {

    private fun p(texto: String) = ComandoParser.parse(texto)

    @Test
    fun mapa_abreElMapa() {
        assertEquals(Comando.VER_MAPA, p("mapa"))
        assertEquals(Comando.VER_MAPA, p("Mapa"))
        assertEquals(Comando.VER_MAPA, p("ver el mapa"))
        assertEquals(Comando.VER_MAPA, p("abre el mapa"))
        assertEquals(Comando.VER_MAPA, p("mapas"))
        assertEquals(Comando.VER_MAPA, p("mapá")) // sin tildes
        assertEquals(Comando.VER_MAPA, p("mapa mapa napa")) // hipótesis unidas de listen (§5.2)
    }

    @Test
    fun mapa_esPalabraCompleta_noFragmento() {
        assertEquals(Comando.NINGUNO, p("mapamundi"))
        assertEquals(Comando.NINGUNO, p("solapa"))
    }

    @Test
    fun unoYDos_siguenIgual() {
        assertEquals(Comando.UBICARME, p("uno"))
        assertEquals(Comando.UBICARME, p("1"))
        assertEquals(Comando.UBICARME, p("dónde estoy"))
        assertEquals(Comando.UBICARME, p("ubícame"))
        assertEquals(Comando.IR_A_LUGAR, p("dos"))
        assertEquals(Comando.IR_A_LUGAR, p("quiero ir a la biblioteca"))
        assertEquals(Comando.IR_A_LUGAR, p("destino"))
        assertEquals(Comando.NINGUNO, p("hola"))
        assertEquals(Comando.NINGUNO, p(""))
    }

    @Test
    fun signos_yaNoImpidenReconocerLaPalabra() {
        // Antes de FE-3.1, «uno,» no contaba como «uno» (se separaba solo por espacios).
        assertEquals(Comando.UBICARME, p("uno,"))
        assertEquals(Comando.IR_A_LUGAR, p("¡dos!"))
        assertEquals(Comando.VER_MAPA, p("mapa."))
    }

    @Test
    fun dosComandosALaVez_esNinguno() {
        assertEquals(Comando.NINGUNO, p("uno dos"))
        assertEquals(Comando.NINGUNO, p("mapa uno"))
        assertEquals(Comando.NINGUNO, p("mapa del lugar")) // «lugar» es de «ir a un lugar»
        assertEquals(Comando.NINGUNO, p("mi ubicación en el mapa"))
    }
}
