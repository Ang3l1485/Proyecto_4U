package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.ResultadoFrame
import com.example.myapplication.domain.ruta.Geo
import com.example.myapplication.domain.ruta.GrafosDePrueba
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import com.example.myapplication.domain.ruta.Ruta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.3: la guía completa en la JVM con el `grafo.json` real y la ruta de la validación en casa (posición de prueba
 * 6.201434, −75.578707 → `bloque35`, 28,7 m: «Camina 14 metros…», «Gira a la izquierda…», «Has llegado a bloque 35.»),
 * caminada con el modo de simulación (0,7 m por paso): avisos, fotos, desvío y recálculo, mezcla de fotos y sin red.
 */
class GuiaNavegacionTest {

    private val planificador = Planificador(GrafosDePrueba.real())
    private val lat0 = 6.201434
    private val lng0 = -75.578707

    private fun calcular(lat: Double, lng: Double, rumbo: Double?): Ruta? =
        (planificador.calcular(lat, lng, listOf("bloque35"), "bloque 35", rumbo) as? ResultadoRuta.Encontrada)?.ruta

    private fun guia(): GuiaNavegacion = GuiaNavegacion(::calcular, calcular(lat0, lng0, null)!!)

    private fun textos(s: List<SalidaGuia>) = s.filterIsInstance<SalidaGuia.Hablar>().map { it.texto }

    @Test
    fun caminarLaRutaSimuladaDiceCadaAvisoYLlega() {
        val g = guia()
        val habla = mutableListOf<String>()
        habla += textos(g.empezar())
        val sim = SimuladorPasos(TrazadoRuta(g.ruta), PruebaGuia.PASO_DEFECTO_M)
        val fotos = mutableListOf<SalidaGuia.TomarFoto>()
        var llegada: SalidaGuia.Llegada? = null
        var pasos = 0
        while (llegada == null && pasos < 100) {
            val p = sim.siguiente()
            pasos++
            val s = g.alMoverse(p.lat, p.lng, p.caminadoM, null)
            habla += textos(s)
            s.filterIsInstance<SalidaGuia.TomarFoto>().forEach { pedido ->
                fotos += pedido
                // En casa: la foto no ubica (sin_coincidencias) y la guía sigue igual.
                habla += textos(g.alResponderFoto(pedido, ResultadoFrame.SinCoincidencias(pedido.radioM, 0)))
            }
            llegada = s.filterIsInstance<SalidaGuia.Llegada>().firstOrNull()
        }
        assertEquals("Has llegado a bloque 35.", llegada!!.texto)
        assertEquals(4, habla.size)
        assertEquals(
            "$COMO_LLEVAR_EL_TELEFONO Vamos a bloque 35, a 29 metros por el camino. Camina 14 metros por el camino.",
            habla[0],
        )
        assertTrue(habla[1], habla[1].matches(Regex("En \\d+ metros, gira a la izquierda\\.")))
        assertEquals("Gira a la izquierda y sigue recto 14 metros.", habla[2])
        assertTrue(habla[3], habla[3].matches(Regex("En \\d+ metros, llegas a bloque 35\\.")))
        // La llegada no se habla aquí (la dice 6.6): queda en el estado y en SalidaGuia.Llegada.
        assertEquals("Has llegado a bloque 35.", g.estado().instruccion)
        assertTrue(g.estado().llegado)
        // Llega a ≤ 3 m del final (28,7 m): entre 25,7 y 28,7 m caminados.
        assertTrue("pasos $pasos", sim.caminadoM in 25.7..29.5)
        // Una foto cada 10 m: a los 10,5 y a los 21 m; con radio 40 (el mínimo).
        assertEquals(listOf(10.5, 21.0), fotos.map { Math.round(it.caminadoM * 10) / 10.0 })
        assertTrue(fotos.all { it.radioM == 40.0 })
        assertEquals("descartada (sin_coincidencias)", g.estado().ultimaFoto)
        // Tras llegar no dice ni pide nada más.
        assertEquals(emptyList<SalidaGuia>(), g.alMoverse(lat0, lng0, 40.0, null))
    }

    @Test
    fun alejarseVariasLecturasRecalculaYLoAvisa() {
        val g = guia()
        g.empezar()
        val plano = Geo.Plano(lat0, lng0)
        // 30 m al este y al sur de la posición inicial (lejos de cualquier tramo de esta ruta corta).
        val lejosLat = plano.lat(-30.0)
        val lejosLng = plano.lng(30.0)
        val antes = g.ruta
        repeat(3) { i ->
            val s = g.alMoverse(lejosLat, lejosLng, 1.0 + i, 90.0)
            assertFalse(s.any { it is SalidaGuia.RutaNueva })
        }
        val s = g.alMoverse(lejosLat, lejosLng, 4.0, 90.0)
        val nueva = s.filterIsInstance<SalidaGuia.RutaNueva>().single().ruta
        assertTrue(nueva !== antes)
        val aviso = s.filterIsInstance<SalidaGuia.Hablar>().first()
        assertTrue(aviso.prioritario)
        assertTrue(aviso.texto, aviso.texto.startsWith(TextosGuia.RECALCULANDO + " "))
        assertEquals(nueva.primera.texto, aviso.texto.removePrefix(TextosGuia.RECALCULANDO + " "))
        assertEquals(1, g.estado().recalculos)
        // La ruta nueva sale de la persona (o de su punto en el camino, a ≤ 15 m): ya no cuenta como desviada.
        assertTrue(g.estado().desvioM <= 15.0)
    }

    @Test
    fun unaFotoCoherenteCorrigeYUnaIncoherenteNo() {
        val g = guia()
        g.empezar()
        val t = TrazadoRuta(g.ruta)
        // Camina 10 m por la ruta: pide la foto con la posición estimada.
        var pedido: SalidaGuia.TomarFoto? = null
        var m = 0.0
        while (pedido == null) {
            m += 0.7
            val (la, ln) = t.puntoEn(m)
            pedido = g.alMoverse(la, ln, m, 0.0).filterIsInstance<SalidaGuia.TomarFoto>().firstOrNull()
        }
        // La foto dice que está 2 m más adelante por la ruta (antes del giro; límite 8 + 0,5·10,5 m).
        val (fLat, fLng) = t.puntoEn(m + 2.0)
        val ok = ResultadoFrame.Ubicado(fLat, fLng, 3.0, 0.95, NivelConfianza.ALTA, 2.0, 40.0, 20)
        val s = g.alResponderFoto(pedido, ok)
        val c = s.filterIsInstance<SalidaGuia.CorregirPosicion>().single()
        assertEquals(m + 2.0, t.proyectar(c.lat, c.lng).avanceM, 0.1)
        assertEquals(1, g.estado().fotosAceptadas)
        assertEquals("aceptada (2 m)", g.estado().ultimaFoto)

        // Otra foto a los 10 m siguientes, con un salto de 40 m: se descarta y la posición no cambia.
        var otro: SalidaGuia.TomarFoto? = null
        var m2 = m + 2.0
        while (otro == null && m2 < 28.0) {
            m2 += 0.7
            val (la, ln) = t.puntoEn(m2)
            otro = g.alMoverse(la, ln, m2 - 2.0, 0.0).filterIsInstance<SalidaGuia.TomarFoto>().firstOrNull()
        }
        val salto = ResultadoFrame.Ubicado(lat0 + 0.0004, lng0, 3.0, 0.95, NivelConfianza.ALTA, 40.0, 40.0, 20)
        assertEquals(emptyList<SalidaGuia>(), g.alResponderFoto(otro!!, salto))
        assertEquals("descartada (incoherente)", g.estado().ultimaFoto)
        assertEquals(1, g.estado().fotosAceptadas)
    }

    @Test
    fun sinRedY503SeAvisanUnaVezCadaUno() {
        val g = guia()
        g.empezar()
        val pedido = SalidaGuia.TomarFoto(lat0, lng0, null, 40.0, 10.0)
        assertEquals(listOf(TextosGuia.SIN_CONEXION), textos(g.alFallarFoto(pedido, FalloFrame.SIN_CONEXION)))
        assertTrue(g.estado().sinConexion)
        assertEquals(emptyList<String>(), textos(g.alFallarFoto(pedido, FalloFrame.SIN_CONEXION)))
        assertEquals(listOf(TextosGuia.SERVICIO_NO_DISPONIBLE), textos(g.alFallarFoto(pedido, FalloFrame.SERVICIO_NO_DISPONIBLE)))
        assertEquals(emptyList<String>(), textos(g.alFallarFoto(pedido, FalloFrame.SERVICIO_NO_DISPONIBLE)))
        assertEquals(emptyList<String>(), textos(g.alFallarFoto(pedido, FalloFrame.FOTO_NO_VALIDA)))
        assertEquals("falló (foto_no_valida)", g.estado().ultimaFoto)
    }

    @Test
    fun lasAlertasCercaDeLaRutaSeDicenUnaVez_laAltaCorta() {
        val ruta = calcular(lat0, lng0, null)!!
        val t = TrazadoRuta(ruta)
        val (aLat, aLng) = t.puntoEn(12.0)
        val alertas = listOf(
            Alerta("n", aLat, aLng, "Hay bancas cerca", radio = 2),
            Alerta("h", aLat, aLng, "Ten cuidado, hay escalones", prioridad = "alta", radio = 2),
        )
        val lineas = mutableListOf<String>()
        val avisador = AlertasEnRuta({ alertas }, ahoraMs = { 1_000L }, registrar = { lineas += it })
        val g = GuiaNavegacion(::calcular, ruta, avisador = avisador)
        g.empezar()
        val (la, ln) = t.puntoEn(1.0)
        assertTrue(g.alMoverse(la, ln, 1.0, null).filterIsInstance<SalidaGuia.Hablar>().none { it.vibrar })
        // A 6 m: umbral = radio 2 + incertidumbre (5 de partida + 4 % de 6 m) ≈ 7,2 m.
        val (la2, ln2) = t.puntoEn(6.0)
        val s = g.alMoverse(la2, ln2, 6.0, null).filterIsInstance<SalidaGuia.Hablar>().filter { it.vibrar }
        assertEquals(
            listOf(
                SalidaGuia.Hablar("Ten cuidado, hay escalones.", prioritario = true, vibrar = true),
                SalidaGuia.Hablar("Hay bancas cerca.", prioritario = false, vibrar = true),
            ),
            s,
        )
        assertEquals(5.24, g.incertidumbreM(), 1e-9)
        assertTrue(lineas.all { it.startsWith("Alerta anunciada (navegacion): ") })
        assertEquals(2, lineas.size)
        // Una vez por aproximación: un paso más no las repite.
        val (la3, ln3) = t.puntoEn(7.0)
        assertTrue(g.alMoverse(la3, ln3, 7.0, null).none { it is SalidaGuia.Hablar && it.vibrar })
    }

    @Test
    fun repetirYSimulacionDeLosExtras() {
        val g = guia()
        g.empezar()
        assertTrue(g.repetir(), g.repetir().matches(Regex("Sigue 1[45] metros; después, gira a la izquierda\\.")))
        assertEquals(PruebaGuia.Simulacion(0.7, 500L), PruebaGuia.leerSimulacion("0.7,500"))
        assertEquals(PruebaGuia.Simulacion(0.7, 500L), PruebaGuia.leerSimulacion("si"))
        assertEquals(PruebaGuia.Simulacion(1.5, 250L), PruebaGuia.leerSimulacion(" 1.5 , 250 "))
        assertEquals(null, PruebaGuia.leerSimulacion("0,7,500"))
        assertEquals(null, PruebaGuia.leerSimulacion("9,500"))
        assertEquals(null, PruebaGuia.leerSimulacion(null))
        PruebaGuia.fijar("bloque35", "6.201434,-75.578707", null)
        assertTrue(PruebaGuia.activa)
        assertEquals(null, PruebaGuia.simulacion)
        PruebaGuia.limpiar()
        assertFalse(PruebaGuia.activa)
    }
}
