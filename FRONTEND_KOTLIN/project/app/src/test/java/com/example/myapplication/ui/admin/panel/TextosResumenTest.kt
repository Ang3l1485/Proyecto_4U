package com.example.myapplication.ui.admin.panel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale
import java.util.TimeZone

/**
 * Textos del «Resumen rápido» (FE-2.2; apoyo de C1: lo que el Panel dibuja con los datos de `GET /v1/admin/stats`).
 * Fechas en la zona de Bogotá (UTC−5, sin horario de verano) con un «ahora» fijo: 2026-10-26 10:00 de Bogotá.
 */
class TextosResumenTest {

    private val bogota = TimeZone.getTimeZone("America/Bogota")
    private val espanol = Locale("es", "CO")
    private val ahora = 1_793_026_800_000L // 2026-10-26T15:00:00Z = 10:00 en Bogotá

    private fun fecha(millis: Long) = TextosResumen.fecha(millis, ahoraMs = ahora, zona = bogota, idioma = espanol)

    @Test
    fun numero_conSeparadorDeMilesDelIdioma_yRayaSinDato() {
        assertEquals("2,842", TextosResumen.numero(2842, Locale.US))
        assertEquals("2.842", TextosResumen.numero(2842, Locale.GERMANY))
        assertEquals("0", TextosResumen.numero(0, Locale.US))
        assertEquals("—", TextosResumen.numero(null, Locale.US))
        assertEquals(TextosResumen.SIN_DATO, TextosResumen.numero(null))
    }

    @Test
    fun fecha_deHoy_esHoyConLaHoraLocal() {
        assertEquals("Hoy, 09:24", fecha(1_793_024_640_000L)) // 2026-10-26T14:24:00Z
        assertEquals("Hoy, 00:00", fecha(1_792_990_800_000L)) // 2026-10-26T05:00:00Z, medianoche en Bogotá
    }

    @Test
    fun fecha_deAyer_esAyer_aunqueEnUtcSeaHoy() {
        assertEquals("Ayer, 23:59", fecha(1_792_990_740_000L)) // 2026-10-26T04:59:00Z = 25 oct 23:59 en Bogotá
        assertEquals("Ayer, 00:00", fecha(1_792_904_400_000L)) // 2026-10-25T05:00:00Z
    }

    @Test
    fun fecha_anterior_esDiaMesYHora() {
        val texto = fecha(1_792_904_399_000L) // 2026-10-25T04:59:59Z = 24 oct 23:59 en Bogotá
        assertTrue(texto, texto.startsWith("24 "))
        assertTrue(texto, texto.endsWith(", 23:59"))
        val otro = fecha(1_792_767_845_000L) // 2026-10-23T15:04:05Z = 23 oct 10:04
        assertTrue(otro, otro.startsWith("23 ") && otro.endsWith(", 10:04"))
    }

    @Test
    fun fecha_futura_esDiaMesYHora() {
        val texto = fecha(ahora + 86_400_000L) // mañana: reloj del teléfono atrasado
        assertTrue(texto, texto.startsWith("27 ") && texto.endsWith(", 10:00"))
    }

    @Test
    fun fecha_usaLaZonaDelTelefono() {
        val utc = TimeZone.getTimeZone("UTC")
        assertEquals("Hoy, 14:24", TextosResumen.fecha(1_793_024_640_000L, ahoraMs = ahora, zona = utc, idioma = espanol))
    }
}
