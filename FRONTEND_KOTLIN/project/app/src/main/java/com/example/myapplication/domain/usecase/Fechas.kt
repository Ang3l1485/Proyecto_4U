package com.example.myapplication.domain.usecase

import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * Fechas ISO-8601 de la app (FE-4.1). El backend las da en UTC con `Z` (backend §5.1) y los manifests del teléfono con
 * zona (`2026-10-25T15:04:10-05:00`, §5.6): para comparar o mostrar las dos hay que pasar por milisegundos. Usa
 * `SimpleDateFormat` y no `java.time` (`minSdk = 24`). Lógica pura (`TextosVideosTest`).
 */
object Fechas {

    private val PATRON = Regex("""^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$""")

    /** `yyyy-MM-dd'T'HH:mm:ss[.fff](Z|±hh:mm)` → milisegundos epoch; otra forma (sin zona incluida) → `null`. */
    fun aMilis(texto: String?): Long? {
        val m = PATRON.matchEntire(texto?.trim() ?: return null) ?: return null
        val base = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
            isLenient = false
        }
        val utc = try {
            base.parse(m.groupValues[1])?.time ?: return null
        } catch (_: ParseException) {
            return null
        }
        val zona = m.groupValues[2]
        if (zona == "Z") return utc
        val signo = if (zona[0] == '-') -1 else 1
        val desfaseMin = zona.substring(1, 3).toInt() * 60 + zona.substring(4, 6).toInt()
        return utc - signo * desfaseMin * 60_000L
    }

    /**
     * «dd/MM/yyyy» en la zona [zona] (la del teléfono). Si el texto no tiene una forma reconocida pero empieza por
     * `yyyy-MM-dd`, usa esos 10 caracteres tal cual (como hacía la Lista antes de FE-4.1). `null` si no hay fecha.
     */
    fun fechaCorta(texto: String?, zona: TimeZone = TimeZone.getDefault()): String? {
        val ms = aMilis(texto)
        if (ms != null) {
            return SimpleDateFormat("dd/MM/yyyy", Locale.ROOT).apply { timeZone = zona }.format(java.util.Date(ms))
        }
        val inicio = texto?.trim()?.take(10) ?: return null
        if (!Regex("""^\d{4}-\d{2}-\d{2}$""").matches(inicio)) return null
        return inicio.split("-").reversed().joinToString("/")
    }
}
