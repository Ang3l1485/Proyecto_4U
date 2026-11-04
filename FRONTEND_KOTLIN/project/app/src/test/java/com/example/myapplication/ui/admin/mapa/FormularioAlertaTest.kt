package com.example.myapplication.ui.admin.mapa

import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.SinConexionException
import com.example.myapplication.data.repository.ResultadoSincronizacion
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.PosicionesAdmin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

/**
 * Reglas del formulario 7.9, filtros de la lista 7.10 y textos de la sincronización (FE-3.3; apoyo de C3 y del
 * formulario completo). Lógica pura.
 */
class FormularioAlertaTest {

    private val bogota = TimeZone.getTimeZone("America/Bogota")
    private fun alerta(mensaje: String = "Hay un lago", cambio: (Alerta) -> Alerta = { it }) =
        cambio(Alerta("a", 6.2, -75.57, mensaje))

    @Test
    fun validar_mensajeRecortadoObligatorioYConLimite() {
        assertEquals(FormularioAlerta.MENSAJE_VACIO, FormularioAlerta.validar(alerta("   ")).mensaje)
        assertEquals(FormularioAlerta.MENSAJE_LARGO, FormularioAlerta.validar(alerta("x".repeat(201))).mensaje)
        assertFalse(FormularioAlerta.validar(alerta("  ${"x".repeat(200)}  ")).hay)
        assertEquals("Hay un lago", FormularioAlerta.limpia(alerta("  Hay un lago ")).mensaje)
    }

    @Test
    fun validar_vigenciaAlReves_yDatosQueElFormularioNoPermite() {
        val alReves = alerta { it.copy(vigenciaDesdeMs = 2_000L, vigenciaHastaMs = 1_000L) }
        assertEquals(FormularioAlerta.VIGENCIA_AL_REVES, FormularioAlerta.validar(alReves).vigencia)
        // Mismo segundo: el backend compara sin fracciones (`hasta > desde`), así que también es un error.
        val mismoSegundo = alerta { it.copy(vigenciaDesdeMs = 1_200L, vigenciaHastaMs = 1_700L) }
        assertEquals(FormularioAlerta.VIGENCIA_AL_REVES, FormularioAlerta.validar(mismoSegundo).vigencia)
        assertNull(FormularioAlerta.validar(alerta { it.copy(vigenciaDesdeMs = 1_000L) }).vigencia)

        val mala = alerta { it.copy(tipo = "lago", prioridad = "urgente", radio = 3, lat = Double.NaN) }
        assertEquals("${FormularioAlerta.DATOS_INVALIDOS} (tipo, prioridad, radio, posición).", FormularioAlerta.validar(mala).general)
    }

    @Test
    fun dictado_seAnadeConUnEspacioYSinPasarDelLimite() {
        assertEquals("Ten cuidado", FormularioAlerta.agregarDictado("", " Ten cuidado "))
        assertEquals("Ten cuidado hay bancas", FormularioAlerta.agregarDictado("Ten cuidado ", "hay bancas"))
        assertEquals("igual", FormularioAlerta.agregarDictado("igual", "   "))
        assertEquals(200, FormularioAlerta.agregarDictado("x".repeat(195), "abcdefghij").length)
    }

    @Test
    fun vigencia_diasEnterosEnLaZonaDelTelefono() {
        val dia = 1_793_232_000_000L   // 2026-10-29T00:00:00Z: lo que devuelve el selector de fechas
        val desde = FormularioAlerta.inicioDelDia(dia, bogota)
        val hasta = FormularioAlerta.finDelDia(dia, bogota)
        assertEquals(dia + 5 * 3_600_000L, desde)                       // 00:00:00 en Bogotá (UTC−5)
        assertEquals(dia + 5 * 3_600_000L + 86_399_000L, hasta)          // 23:59:59 en Bogotá
        assertEquals(dia, FormularioAlerta.fechaUtcDelDia(hasta, bogota))
        assertEquals("29/10/2026", FormularioAlerta.textoFecha(desde, bogota))
        assertEquals("Del 29/10/2026 al 29/10/2026", FormularioAlerta.textoVigencia(desde, hasta, bogota))
        assertEquals("Siempre vigente", FormularioAlerta.textoVigencia(null, null, bogota))
        assertEquals("Hasta el 29/10/2026", FormularioAlerta.textoVigencia(null, hasta, bogota))
    }

    @Test
    fun posicion_seisDecimalesConPunto() {
        assertEquals("6.200512, -75.578311", FormularioAlerta.textoPosicion(6.2005123, -75.5783114))
        assertEquals(6.200512, FormularioAlerta.redondear(6.2005124), 0.0)
    }

    @Test
    fun filtros_buscanSinTildesNiMayusculas_yOrdenanPendientesPrimero() {
        val lista = listOf(
            Alerta("a", 6.2, -75.5, "Escalón roto en el bloque", "escalones", actualizadoEnMs = 1L),
            Alerta("b", 6.2, -75.5, "Hay un lago", "agua", "alta", actualizadoEnMs = 5L),
            Alerta("c", 6.2, -75.5, "Obra en la ESCALERA", "obra", activa = false, actualizadoEnMs = 3L),
        )
        val todas = FiltrosAlertas.filtrar(lista, "", null, null, FiltroEstado.TODAS)
        assertEquals(listOf("b", "c", "a"), todas.map { it.id })   // modificada más recientemente primero
        assertEquals(listOf("a", "b", "c"), FiltrosAlertas.filtrar(lista, "", null, null, FiltroEstado.TODAS, setOf("a")).map { it.id })
        assertEquals(listOf("c", "a"), FiltrosAlertas.filtrar(lista, "  ESCAL ", null, null, FiltroEstado.TODAS).map { it.id })
        assertEquals(listOf("a"), FiltrosAlertas.filtrar(lista, "escalón", null, null, FiltroEstado.ACTIVAS).map { it.id })
        assertEquals(listOf("b"), FiltrosAlertas.filtrar(lista, "", "agua", "alta", FiltroEstado.TODAS).map { it.id })
        assertEquals(listOf("c"), FiltrosAlertas.filtrar(lista, "", null, null, FiltroEstado.INACTIVAS).map { it.id })
    }

    @Test
    fun filaDe710_empiezaPorElMensaje() {
        val a = Alerta("a", 6.2, -75.5, "validacion-3-3-c3", "obra", "alta", activa = false)
        assertEquals(
            "validacion-3-3-c3, Obra, prioridad alta, inactiva, sin sincronizar. Toca para editar.",
            descripcionFilaAlerta(a, pendiente = true),
        )
        assertEquals("1 alerta", textoTotal(1))
    }

    @Test
    fun textosDeSincronizacion() {
        assertEquals("Sincronizado: 2 de 2 cambios.", TextosAlertas.resultado(ResultadoSincronizacion(2, 2, emptyList(), true)))
        assertEquals(
            "Sincronizado: 1 de 2 cambios. 1 rechazados por el servidor (datos no válidos): revísalos en la lista. " +
                "No se pudo releer la lista del servidor.",
            TextosAlertas.resultado(ResultadoSincronizacion(2, 1, listOf("x"), false)),
        )
        assertEquals(TextosAlertas.SIN_CONEXION, TextosAlertas.deExcepcion(SinConexionException()))
        assertNull(TextosAlertas.deExcepcion(ApiException(FalloApi.SesionVencida("TOKEN_EXPIRADO"), 401, null)))
        assertEquals(TextosAlertas.ALGO_SALIO_MAL, TextosAlertas.deExcepcion(ApiException(FalloApi.Desconocido(503, "BASE_NO_DISPONIBLE"), 503, null)))
        assertEquals(TextosAlertas.CARGA_SIN_CONEXION, TextosAlertas.deCarga(SinConexionException()))
    }

    @Test
    fun posicionAdmin_laDeLaRecoleccionYSiNoElRespaldo() {
        var respaldo: Pair<Double, Double>? = null
        val p = PosicionesAdmin { respaldo }
        assertNull(p.ultima())
        respaldo = 1.0 to 2.0
        assertEquals(1.0 to 2.0, p.ultima())
        p.registrar(6.2, -75.5)
        assertTrue(p.ultima() == (6.2 to -75.5))
    }
}
