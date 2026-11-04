package com.example.myapplication.ui.admin.panel

import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Textos del «Resumen rápido» del Panel (7.2; lógica pura, sin Android: FE-2.2 la sacó de `PanelAdminScreen` para
 * probarla en la JVM). Los valores por defecto son los del teléfono (idioma, zona horaria y hora actual).
 */
internal object TextosResumen {

    /** Lo que se ve cuando no hay dato (cargando, error o sin último video). */
    const val SIN_DATO = "—"

    /** Entero con el separador de miles del idioma («2.842» o «2,842»); `null` → [SIN_DATO]. */
    fun numero(valor: Int?, idioma: Locale = Locale.getDefault()): String =
        valor?.let { NumberFormat.getIntegerInstance(idioma).format(it) } ?: SIN_DATO

    /**
     * Fecha y hora del último video en la zona del teléfono: «Hoy, HH:mm», «Ayer, HH:mm» (el día de calendario
     * anterior) o «d MMM, HH:mm» (p. ej. «23 oct, 10:04»; la abreviatura del mes depende del idioma). Una fecha futura
     * (reloj del teléfono atrasado) sale como «d MMM, HH:mm».
     */
    fun fecha(
        millis: Long,
        ahoraMs: Long = System.currentTimeMillis(),
        zona: TimeZone = TimeZone.getDefault(),
        idioma: Locale = Locale.getDefault(),
    ): String {
        val hora = formato("HH:mm", zona, idioma).format(Date(millis))
        val dia = diaDe(millis, zona)
        val hoy = Calendar.getInstance(zona).apply { timeInMillis = ahoraMs }
        val ayer = (hoy.clone() as Calendar).apply { add(Calendar.DAY_OF_YEAR, -1) }
        return when (dia) {
            clave(hoy) -> "Hoy, $hora"
            clave(ayer) -> "Ayer, $hora"
            else -> formato("d MMM, HH:mm", zona, idioma).format(Date(millis))
        }
    }

    private fun formato(patron: String, zona: TimeZone, idioma: Locale) =
        SimpleDateFormat(patron, idioma).apply { timeZone = zona }

    private fun diaDe(millis: Long, zona: TimeZone): Int =
        clave(Calendar.getInstance(zona).apply { timeInMillis = millis })

    private fun clave(c: Calendar): Int = c.get(Calendar.YEAR) * 1000 + c.get(Calendar.DAY_OF_YEAR)
}
