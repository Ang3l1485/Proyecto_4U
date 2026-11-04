package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.Alerta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `DetectarAlertasCercanas` y `SeguimientoAlertas` (FE-3.6, criterio C3: radio, incertidumbre, una vez por
 * aproximación y vigencia; ARCHITECTURE §2.5 y §5.7). Las posiciones se mueven hacia el norte desde la alerta, en metros
 * (1 m de latitud = 1 / 111 194,9 grados con la Tierra de 6 371 km de `Geo`).
 */
class DetectarAlertasCercanasTest {

    private val lat0 = 6.2011
    private val lng0 = -75.579
    private val ahora = 1_800_000_000_000L

    /** Latitud a [m] metros al norte del punto de la alerta. */
    private fun norte(m: Double) = lat0 + m / 111_194.93

    private fun alerta(
        id: String,
        radio: Int = 15,
        prioridad: String = "normal",
        activa: Boolean = true,
        desde: Long? = null,
        hasta: Long? = null,
        lat: Double = lat0,
    ) = Alerta(id, lat, lng0, "Cuidado $id", "agua", prioridad, radio, activa, desde, hasta)

    @Test
    fun radio_dentroYFuera() {
        val a = alerta("a", radio = 15)
        assertEquals(listOf("a"), DetectarAlertasCercanas.cercanas(listOf(a), norte(14.0), lng0, 0.0, ahora).map { it.alerta.id })
        assertTrue(DetectarAlertasCercanas.cercanas(listOf(a), norte(16.0), lng0, 0.0, ahora).isEmpty())
        val d = DetectarAlertasCercanas.cercanas(listOf(a), norte(10.0), lng0, 0.0, ahora).single().distanciaM
        assertEquals(10.0, d, 0.05)
    }

    @Test
    fun incertidumbre_amplia_elRadio_yNegativaNoResta() {
        val a = alerta("a", radio = 15)
        // A 20 m: fuera del radio, dentro con 6 m de incertidumbre (15 + 6 = 21).
        assertTrue(DetectarAlertasCercanas.cercanas(listOf(a), norte(20.0), lng0, 0.0, ahora).isEmpty())
        assertEquals(1, DetectarAlertasCercanas.cercanas(listOf(a), norte(20.0), lng0, 6.0, ahora).size)
        assertTrue(DetectarAlertasCercanas.cercanas(listOf(a), norte(20.0), lng0, 4.0, ahora).isEmpty())
        // Una incertidumbre negativa cuenta como 0.
        assertEquals(1, DetectarAlertasCercanas.cercanas(listOf(a), norte(14.0), lng0, -10.0, ahora).size)
        assertEquals(15.0, DetectarAlertasCercanas.umbralM(a, -3.0), 0.0)
    }

    @Test
    fun vigencia_inactivas_yFiltro() {
        val lista = listOf(
            alerta("sin-limite"),
            alerta("empieza-ahora", desde = ahora),
            alerta("futura", desde = ahora + 1),
            alerta("vencida", hasta = ahora),
            alerta("vence-luego", hasta = ahora + 1),
            alerta("inactiva", activa = false),
        )
        val ids = DetectarAlertasCercanas.cercanas(lista, norte(1.0), lng0, 0.0, ahora).map { it.alerta.id }.toSet()
        assertEquals(setOf("sin-limite", "empieza-ahora", "vence-luego"), ids)
        // `incluir` (FE-5.3: p. ej. solo las cercanas a la ruta).
        val soloUna = DetectarAlertasCercanas.cercanas(lista, norte(1.0), lng0, 0.0, ahora, incluir = { it.id == "vence-luego" })
        assertEquals(listOf("vence-luego"), soloUna.map { it.alerta.id })
    }

    @Test
    fun orden_altaPrimero_despuesLaMasCercana() {
        val lista = listOf(
            alerta("normal-cerca", lat = norte(2.0)),
            alerta("alta-lejos", prioridad = "alta", lat = norte(12.0)),
            alerta("normal-media", lat = norte(6.0)),
        )
        val r = DetectarAlertasCercanas.cercanas(lista, lat0, lng0, 0.0, ahora)
        assertEquals(listOf("alta-lejos", "normal-cerca", "normal-media"), r.map { it.alerta.id })
        assertTrue(r.first().alta)
        assertFalse(r[1].alta)
    }

    @Test
    fun seguimiento_unaVezPorAproximacion_conHisteresisYEspera() {
        val s = SeguimientoAlertas(ParametrosAlertas(margenSalidaM = 5.0, esperaRepetirMs = 60_000L))
        val a = listOf(alerta("a", radio = 15))
        // Lejos: nada. Entra: se anuncia una vez. Sigue dentro: nada.
        assertTrue(s.actualizar(a, norte(30.0), lng0, 0.0, ahora).isEmpty())
        assertEquals(listOf("a"), s.actualizar(a, norte(14.0), lng0, 0.0, ahora + 1_000).map { it.alerta.id })
        assertTrue(s.actualizar(a, norte(5.0), lng0, 0.0, ahora + 2_000).isEmpty())
        assertEquals(setOf("a"), s.enCurso)
        // Borde (entre 15 y 20 m): sigue dentro, no repite al volver a entrar.
        assertTrue(s.actualizar(a, norte(18.0), lng0, 0.0, ahora + 3_000).isEmpty())
        assertTrue(s.actualizar(a, norte(14.0), lng0, 0.0, ahora + 4_000).isEmpty())
        // Sale (> 20 m) y vuelve antes de la espera: entra en silencio.
        assertTrue(s.actualizar(a, norte(25.0), lng0, 0.0, ahora + 5_000).isEmpty())
        assertTrue(s.enCurso.isEmpty())
        assertTrue(s.actualizar(a, norte(10.0), lng0, 0.0, ahora + 10_000).isEmpty())
        // Sale y vuelve tras la espera: otra aproximación, se anuncia.
        assertTrue(s.actualizar(a, norte(40.0), lng0, 0.0, ahora + 70_000).isEmpty())
        assertEquals(1, s.actualizar(a, norte(10.0), lng0, 0.0, ahora + 70_000 + 1_000).size)
    }

    @Test
    fun seguimiento_incertidumbre_alertasQueSalenDeLaLista_yReiniciar() {
        val s = SeguimientoAlertas()
        val a = alerta("a", radio = 10)
        // A 14 m solo alcanza con incertidumbre (10 + 5).
        assertTrue(s.actualizar(listOf(a), norte(14.0), lng0, 0.0, ahora).isEmpty())
        assertEquals(1, s.actualizar(listOf(a), norte(14.0), lng0, 5.0, ahora + 1).size)
        // Deja de estar en la caché (borrada): sale de las aproximaciones.
        assertTrue(s.actualizar(emptyList(), norte(14.0), lng0, 5.0, ahora + 2).isEmpty())
        assertTrue(s.enCurso.isEmpty())
        // Vencida mientras se está dentro: sale; reiniciar olvida los avisos (vuelve a anunciar en el acto).
        val vence = alerta("v", hasta = ahora + 10)
        assertEquals(1, s.actualizar(listOf(vence), norte(1.0), lng0, 0.0, ahora + 5).size)
        assertTrue(s.actualizar(listOf(vence), norte(1.0), lng0, 0.0, ahora + 20).isEmpty())
        assertFalse("v" in s.enCurso)
        s.reiniciar()
        assertEquals(1, s.actualizar(listOf(a), norte(1.0), lng0, 0.0, ahora + 30).size)
    }

    @Test
    fun seguimiento_variasALaVez_altaPrimero_yTextos() {
        val s = SeguimientoAlertas()
        val lista = listOf(
            alerta("n", lat = norte(1.0)),
            Alerta("h", norte(3.0), lng0, "  Ten cuidado, hay un lago  ", "agua", "alta", 15),
        )
        val r = s.actualizar(lista, lat0, lng0, 0.0, ahora)
        assertEquals(listOf("h", "n"), r.map { it.alerta.id })
        assertEquals("Ten cuidado, hay un lago.", DetectarAlertasCercanas.texto(r.first().alerta))
        assertEquals("¡Ojo!", DetectarAlertasCercanas.texto(Alerta("x", 0.0, 0.0, "¡Ojo!")))
        assertEquals(
            "Alerta anunciada (mapa): h a 3 m (radio 15 m, incertidumbre 5 m, alta)",
            DetectarAlertasCercanas.lineaAnunciada("mapa", r.first(), 4.6),
        )
    }
}
