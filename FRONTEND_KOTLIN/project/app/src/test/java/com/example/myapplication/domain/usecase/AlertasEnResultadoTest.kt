package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.model.UbicacionEstimada
import com.example.myapplication.domain.ruta.GrafosDePrueba
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.ui.ubicacion.PruebaUbicacion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.6, criterio C4 (en la JVM): en la vista 6.3, las alertas cercanas a la posición estimada se muestran y se dicen
 * **después** de la ubicación y de la ruta de FE-5.1 (ARCHITECTURE §5.7, «Reglas de `DescribirUbicacion`»); y la
 * ubicación de prueba de la validación en casa (ADR-FE-42).
 */
class AlertasEnResultadoTest {

    private val latPrueba = 6.201434
    private val lngPrueba = -75.578427
    private val ahora = 1_800_000_000_000L
    private val bloque35 = LugarDestino("b35", "Bloque 35", CategoriaLugar.BLOQUE, 6.201286, -75.578834)

    private fun ubicado(radio: Double = 5.0, nivel: NivelConfianza = NivelConfianza.ALTA) = UbicacionEstimada(
        ResultadoUbicacion.Ubicado(
            posicion = PosicionEstimada(latPrueba, lngPrueba, radio),
            confianza = 0.8,
            nivel = nivel,
            correccionRumboGrados = -10.0,
            lugarCercano = LugarCercano("b38", "Bloque 38", 15.0),
            referencias = emptyList(),
            fotosUsadas = 5,
            fotosConCoincidencia = 5,
        ),
        obtenidaEnMs = 0L,
        rumboAlTerminar = null,
    )

    /** Una alerta a [metros] al norte de la posición de prueba. */
    private fun alerta(id: String, metros: Double, mensaje: String, prioridad: String = "normal", radio: Int = 15) =
        Alerta(id, latPrueba + metros / 111_194.93, lngPrueba, mensaje, "agua", prioridad, radio)

    @Test
    fun alertasAlFinal_despuesDeLaRuta_altaPrimero() {
        val alertas = listOf(
            alerta("n", 4.0, "Hay bancas cerca"),
            alerta("h", 12.0, "Ten cuidado, hay un lago alrededor de la biblioteca.", prioridad = "alta"),
            alerta("lejos", 40.0, "No debería oírse"),
        )
        val cercanas = DetectarAlertasCercanas.cercanas(alertas, latPrueba, lngPrueba, 5.0, ahora)
        val planificador = Planificador(GrafosDePrueba.real())
        val d = DescribirUbicacion.describir(ubicado(), 10.0, bloque35, planificador, cercanas)
        // La primera instrucción depende del grafo (FE-5.1); aquí importa el orden: ruta y después alertas.
        // Brújula 10° + corrección −10° = norte.
        val primera = planificador.rutaA(bloque35, latPrueba, lngPrueba, 0.0)!!.primera.texto
        assertEquals(listOf("Ten cuidado, hay un lago alrededor de la biblioteca.", "Hay bancas cerca."), d.alertas)
        // Las alertas no van en los detalles (tarjeta aparte) y se dicen al final, tras la ruta.
        assertTrue(d.detalles.none { it.contains("lago") })
        assertTrue(
            d.hablado.endsWith(
                "$primera ${DescribirUbicacion.GUIA_DISPONIBLE} " +
                    "${DescribirUbicacion.ALERTAS_CERCANAS} Ten cuidado, hay un lago alrededor de la biblioteca. Hay bancas cerca.",
            ),
        )
        assertTrue(d.hablado.startsWith("Estás cerca de Bloque 38, a unos 15 metros."))
    }

    @Test
    fun unaSola_sinDestino_yLaIncertidumbreEsElRadioDeLaPosicion() {
        val a = listOf(alerta("a", 18.0, "Escalones"))
        // A 18 m con radio 15: solo alcanza con el radio de la posición estimada (5 m).
        assertTrue(DetectarAlertasCercanas.cercanas(a, latPrueba, lngPrueba, 0.0, ahora).isEmpty())
        val cercanas = DetectarAlertasCercanas.cercanas(a, latPrueba, lngPrueba, 5.0, ahora)
        val d = DescribirUbicacion.describir(ubicado(), null, null, null, cercanas)
        assertEquals(
            "Estás cerca de Bloque 38, a unos 15 metros. Confianza alta. ${DescribirUbicacion.ALERTA_CERCANA} Escalones.",
            d.hablado,
        )
        // Sin alertas, el texto es el de siempre.
        assertEquals("Estás cerca de Bloque 38, a unos 15 metros. Confianza alta.", DescribirUbicacion.describir(ubicado(), null, null).hablado)
    }

    @Test
    fun sinPosicion_noHayAlertas() {
        val cercanas = DetectarAlertasCercanas.cercanas(listOf(alerta("a", 1.0, "x")), latPrueba, lngPrueba, 5.0, ahora)
        val sin = DescribirUbicacion.describir(UbicacionEstimada(ResultadoUbicacion.SinCoincidencias(5), 0L, null), null, null, null, cercanas)
        assertTrue(sin.alertas.isEmpty())
        assertTrue(DescribirUbicacion.describir(null, null, null, null, cercanas).alertas.isEmpty())
    }

    @Test
    fun ubicacionDePrueba_esAltaConElRadioFijo() {
        val u = PruebaUbicacion.resultado("6.201434,-75.578427")!!
        assertEquals(NivelConfianza.ALTA, u.nivel)
        assertEquals(PosicionEstimada(6.201434, -75.578427, PruebaUbicacion.RADIO_M), u.posicion)
        assertTrue(u.referencias.isEmpty())
        assertNull(u.lugarCercano)
        assertNull(PruebaUbicacion.resultado("6.2"))
        assertNull(PruebaUbicacion.resultado(null))
        assertNull(PruebaUbicacion.resultado("95.0,-75.5"))
    }
}
