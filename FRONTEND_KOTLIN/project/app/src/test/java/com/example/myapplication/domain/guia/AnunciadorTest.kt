package com.example.myapplication.domain.guia

import com.example.myapplication.domain.ruta.Giro
import com.example.myapplication.domain.ruta.Instruccion
import com.example.myapplication.domain.ruta.Lado
import com.example.myapplication.domain.ruta.TipoInstruccion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-5.3: cuándo se anuncia cada maniobra (aviso previo, al llegar, saltos y llegada) y «Repetir instrucción». */
class AnunciadorTest {

    private fun ins(tipo: TipoInstruccion, giro: Giro?, lado: Lado, desde: Double, texto: String) =
        Instruccion(tipo, giro, lado, 0.0, desde, 0.0, 0.0, texto)

    private val instrucciones = listOf(
        ins(TipoInstruccion.SALIDA, null, Lado.NINGUNO, 0.0, "Camina 30 metros por el camino."),
        ins(TipoInstruccion.GIRO, Giro.NORMAL, Lado.DERECHA, 30.0, "Gira a la derecha y sigue recto 6 metros."),
        ins(TipoInstruccion.GIRO, Giro.LEVE, Lado.IZQUIERDA, 36.0, "Gira levemente a la izquierda y sigue recto 24 metros."),
        ins(TipoInstruccion.LLEGADA, null, Lado.NINGUNO, 60.0, "Has llegado a Meta."),
    )

    @Test
    fun secuenciaCompleta() {
        val a = Anunciador(instrucciones, "Meta")
        val dichos = mutableListOf<Anuncio>()
        var m = 0.0
        while (m <= 60.0) {
            dichos += a.alAvanzar(m)
            m += 0.5
        }
        assertEquals(
            listOf(
                "En 10 metros, gira a la derecha.",
                "Gira a la derecha y sigue recto 6 metros.",
                // El aviso previo de la segunda se omite: estaba a menos de 10 m al decir la primera.
                "Gira levemente a la izquierda y sigue recto 24 metros.",
                "En 10 metros, llegas a Meta.",
                "Has llegado a Meta.",
            ),
            dichos.map { it.texto },
        )
        assertTrue(dichos[0] is Anuncio.Previo)
        assertTrue(dichos[1] is Anuncio.Maniobra)
        assertTrue(dichos.last() is Anuncio.Llegada)
        assertTrue(a.llegado)
    }

    @Test
    fun losUmbralesSonLosDeLosParametros() {
        val a = Anunciador(instrucciones, "Meta")
        assertEquals(emptyList<Anuncio>(), a.alAvanzar(19.9))  // a 10,1 m: todavía no
        assertEquals("En 10 metros, gira a la derecha.", a.alAvanzar(20.0).single().texto)
        assertEquals(emptyList<Anuncio>(), a.alAvanzar(26.9))  // a 3,1 m: todavía no
        assertTrue(a.alAvanzar(27.0).single() is Anuncio.Maniobra)
    }

    @Test
    fun unSaltoSoloDiceLaUltimaAlcanzada() {
        val a = Anunciador(instrucciones, "Meta")
        assertEquals(listOf("Gira levemente a la izquierda y sigue recto 24 metros."), a.alAvanzar(40.0).map { it.texto })
        // Retroceder no repite nada.
        assertEquals(emptyList<Anuncio>(), a.alAvanzar(10.0))
        assertEquals(listOf(Anuncio.Llegada("Has llegado a Meta.")), a.alAvanzar(59.0))
        assertEquals(emptyList<Anuncio>(), a.alAvanzar(60.0))
    }

    @Test
    fun repetirDiceCuantoFaltaYQueHacer() {
        val a = Anunciador(instrucciones, "Meta")
        assertEquals("Sigue 25 metros; después, gira a la derecha.", a.repetir(5.0))
        a.alAvanzar(28.0)
        assertEquals("Sigue 7 metros; después, gira levemente a la izquierda.", a.repetir(29.0))
        a.alAvanzar(34.0)
        assertEquals("Sigue 22 metros; después, llegas a Meta.", a.repetir(38.0))
        a.alAvanzar(58.0)
        assertEquals("Has llegado a Meta.", a.repetir(58.0))
    }

    @Test
    fun accionesDeCadaGiro() {
        fun accion(g: Giro?, l: Lado) = TextosGuia.accion(ins(TipoInstruccion.GIRO, g, l, 0.0, ""), "X")
        assertEquals("gira cerrado a la izquierda", accion(Giro.CERRADO, Lado.IZQUIERDA))
        assertEquals("date la vuelta", accion(Giro.VUELTA, Lado.NINGUNO))
        assertEquals("llegas al camino; sigue recto", accion(Giro.RECTO, Lado.NINGUNO))
        assertEquals("En 1 metro, gira a la derecha.", TextosGuia.previo(ins(TipoInstruccion.GIRO, Giro.NORMAL, Lado.DERECHA, 0.0, ""), 0.6, "X"))
    }
}
