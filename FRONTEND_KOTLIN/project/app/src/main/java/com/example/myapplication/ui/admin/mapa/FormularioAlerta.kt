package com.example.myapplication.ui.admin.mapa

import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.MapeoErroresApi
import com.example.myapplication.data.repository.ResultadoSincronizacion
import com.example.myapplication.domain.model.Alerta
import java.text.Normalizer
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

/** Errores del formulario de alerta (7.9): bajo el mensaje, bajo la vigencia y uno general. `null` = sin error. */
data class ErroresAlerta(val mensaje: String? = null, val vigencia: String? = null, val general: String? = null) {
    val hay: Boolean get() = mensaje != null || vigencia != null || general != null

    companion object {
        val NINGUNO = ErroresAlerta()
    }
}

/**
 * Reglas del formulario de alerta (FE-3.3; lógica pura, `FormularioAlertaTest`). Los límites son los de
 * `AlertaEntrada` (backend §5.5): mensaje de 1 a [MAX_MENSAJE] caracteres tras recortar, radio de 5 a 100, `tipo` y
 * `prioridad` de las listas, coordenada WGS84 y, con las dos fechas, `hasta > desde`. La usan 7.4, 7.8 y 7.10.
 */
internal object FormularioAlerta {

    /** Claves y nombres de los tipos: los mismos que `TIPOS` y `TIPO_NOMBRE` de `editor_mapa.js`. */
    val TIPOS = listOf(
        "agua" to "Agua", "mobiliario" to "Mobiliario", "escalones" to "Escalones",
        "obra" to "Obra", "vehiculos" to "Vehículos", "otro" to "Otro",
    )
    val PRIORIDADES = listOf("normal" to "Normal", "alta" to "Alta")
    const val RADIO_MIN = 5
    const val RADIO_MAX = 100

    const val MENSAJE_VACIO = "Escribe el mensaje que se leerá al usuario."
    const val MENSAJE_LARGO = "Máximo $MAX_MENSAJE caracteres."
    const val VIGENCIA_AL_REVES = "La fecha final debe ser igual o posterior a la inicial."
    const val DATOS_INVALIDOS = "La alerta tiene datos no válidos"

    fun nombreTipo(clave: String): String = TIPOS.firstOrNull { it.first == clave }?.second ?: "Alerta"
    fun nombrePrioridad(clave: String): String = if (clave == "alta") "Alta" else "Normal"

    /** Lo que se guarda: el mensaje recortado (como el backend). */
    fun limpia(a: Alerta): Alerta = a.copy(mensaje = a.mensaje.trim())

    fun validar(a: Alerta): ErroresAlerta {
        val m = a.mensaje.trim()
        val mensaje = when {
            m.isEmpty() -> MENSAJE_VACIO
            m.length > MAX_MENSAJE -> MENSAJE_LARGO
            else -> null
        }
        val desde = a.vigenciaDesdeMs
        val hasta = a.vigenciaHastaMs
        val vigencia = if (desde != null && hasta != null && hasta / 1000 <= desde / 1000) VIGENCIA_AL_REVES else null
        val malos = buildList {
            if (a.tipo !in TIPOS.map { it.first }) add("tipo")
            if (a.prioridad !in PRIORIDADES.map { it.first }) add("prioridad")
            if (a.radio !in RADIO_MIN..RADIO_MAX) add("radio")
            if (!a.lat.isFinite() || a.lat !in -90.0..90.0 || !a.lng.isFinite() || a.lng !in -180.0..180.0) add("posición")
        }
        val general = if (malos.isEmpty()) null else "$DATOS_INVALIDOS (${malos.joinToString(", ")})."
        return ErroresAlerta(mensaje, vigencia, general)
    }

    /** Añade lo dictado al final del mensaje (con un espacio), sin pasar de [MAX_MENSAJE]. */
    fun agregarDictado(actual: String, dicho: String): String {
        val d = dicho.trim()
        if (d.isEmpty()) return actual
        val base = actual.trimEnd()
        return (if (base.isEmpty()) d else "$base $d").take(MAX_MENSAJE)
    }

    // ── Vigencia (7.9) ──
    // El selector de fechas de Material devuelve la medianoche UTC del día elegido. «Desde» empieza a las 00:00:00 de ese
    // día en la zona del teléfono y «Hasta» termina a las 23:59:59 del suyo (el día elegido cuenta entero).

    fun inicioDelDia(fechaUtcMs: Long, zona: TimeZone): Long = enZona(fechaUtcMs, zona, 0, 0, 0)

    fun finDelDia(fechaUtcMs: Long, zona: TimeZone): Long = enZona(fechaUtcMs, zona, 23, 59, 59)

    /** Lo contrario: la medianoche UTC del día en que cae [instanteMs] en [zona] (lo que espera el selector). */
    fun fechaUtcDelDia(instanteMs: Long, zona: TimeZone): Long {
        val local = Calendar.getInstance(zona).apply { timeInMillis = instanteMs }
        return Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply {
            clear()
            set(local.get(Calendar.YEAR), local.get(Calendar.MONTH), local.get(Calendar.DAY_OF_MONTH))
        }.timeInMillis
    }

    fun textoFecha(instanteMs: Long, zona: TimeZone): String =
        SimpleDateFormat("dd/MM/yyyy", Locale.ROOT).apply { timeZone = zona }.format(java.util.Date(instanteMs))

    fun textoVigencia(desdeMs: Long?, hastaMs: Long?, zona: TimeZone): String = when {
        desdeMs == null && hastaMs == null -> "Siempre vigente"
        hastaMs == null -> "Desde el ${textoFecha(desdeMs!!, zona)}"
        desdeMs == null -> "Hasta el ${textoFecha(hastaMs, zona)}"
        else -> "Del ${textoFecha(desdeMs, zona)} al ${textoFecha(hastaMs, zona)}"
    }

    /** «lat, lng» con 6 decimales y punto decimal en cualquier idioma (como el pie de 7.7). */
    fun textoPosicion(lat: Double, lng: Double): String = String.format(Locale.ROOT, "%.6f, %.6f", lat, lng)

    /** Coordenada redondeada a 6 decimales (≈ 0,11 m), como los lugares (ADR-FE-30). */
    fun redondear(g: Double): Double = Math.round(g * 1_000_000.0) / 1_000_000.0

    private fun enZona(fechaUtcMs: Long, zona: TimeZone, h: Int, m: Int, s: Int): Long {
        val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = fechaUtcMs }
        return Calendar.getInstance(zona).apply {
            clear()
            set(utc.get(Calendar.YEAR), utc.get(Calendar.MONTH), utc.get(Calendar.DAY_OF_MONTH), h, m, s)
        }.timeInMillis
    }
}

/** Filtro de la lista 7.10 por estado. */
enum class FiltroEstado(val etiqueta: String) { TODAS("Todas"), ACTIVAS("Activas"), INACTIVAS("Inactivas") }

/** Buscador y filtros de la lista 7.10 (FE-3.3; lógica pura, `FormularioAlertaTest`). */
internal object FiltrosAlertas {

    /** Sin tildes, en minúsculas y con los espacios reducidos (la regla de `q` del backend, §4.9 y §4.11). */
    fun normalizar(texto: String): String =
        Normalizer.normalize(texto, Normalizer.Form.NFKD).replace(Regex("\\p{M}+"), "")
            .lowercase(Locale.ROOT).trim().replace(Regex("\\s+"), " ")

    /**
     * Las que cumplen todo: el mensaje **contiene** la búsqueda normalizada (vacía = todas), y el tipo, la prioridad y el
     * estado elegidos (`null` / [FiltroEstado.TODAS] = sin filtro). Orden: primero las que tienen cambios sin
     * sincronizar ([pendientes]), después la modificada más recientemente (sin fecha, arriba).
     */
    fun filtrar(
        alertas: List<Alerta>,
        busqueda: String,
        tipo: String?,
        prioridad: String?,
        estado: FiltroEstado,
        pendientes: Set<String> = emptySet(),
    ): List<Alerta> {
        val q = normalizar(busqueda)
        return alertas.filter { a ->
            (q.isEmpty() || normalizar(a.mensaje).contains(q)) &&
                (tipo == null || a.tipo == tipo) &&
                (prioridad == null || a.prioridad == prioridad) &&
                when (estado) {
                    FiltroEstado.TODAS -> true
                    FiltroEstado.ACTIVAS -> a.activa
                    FiltroEstado.INACTIVAS -> !a.activa
                }
        }.sortedWith(
            compareBy<Alerta> { it.id !in pendientes }.thenByDescending { it.actualizadoEnMs ?: Long.MAX_VALUE },
        )
    }
}

/** Textos de la sincronización y de la carga de alertas (FE-3.3; lógica pura, `FormularioAlertaTest`). */
internal object TextosAlertas {
    const val SIN_CONEXION = "Sin conexión: los cambios siguen guardados en el teléfono. Inténtalo de nuevo."
    const val SIN_PERMISOS = "Tu cuenta no tiene permisos de administrador."
    const val ALGO_SALIO_MAL = "No se pudo sincronizar. Inténtalo de nuevo."
    const val CARGA_SIN_CONEXION = "Sin conexión: se muestran las alertas guardadas en el teléfono."
    const val CARGA_FALLIDA = "No se pudo leer la lista del servidor: se muestran las guardadas en el teléfono."
    const val SIN_POSICION = "No hay una posición reciente: graba un recorrido (Recolector) o ubícate primero."
    const val NO_SE_GUARDO = "No se pudo guardar la alerta en el teléfono."

    /** Lo que se dice tras sincronizar. */
    fun resultado(r: ResultadoSincronizacion): String {
        val partes = mutableListOf<String>()
        partes += if (r.enviados == 0) "No había cambios pendientes." else "Sincronizado: ${r.aplicados} de ${r.enviados} cambios."
        if (r.rechazados.isNotEmpty()) {
            partes += "${r.rechazados.size} rechazados por el servidor (datos no válidos): revísalos en la lista."
        }
        if (!r.releida) partes += "No se pudo releer la lista del servidor."
        return partes.joinToString(" ")
    }

    /** Error de una sincronización; `null` si la sesión se perdió (`AppNav` ya va a Login, no se muestra nada). */
    fun deExcepcion(e: Throwable): String? = when (MapeoErroresApi.deExcepcion(e)) {
        is FalloApi.SesionVencida -> null
        FalloApi.SinConexion -> SIN_CONEXION
        FalloApi.SinPermisos -> SIN_PERMISOS
        else -> ALGO_SALIO_MAL
    }

    /** Error al leer la lista del servidor (las guardadas se siguen viendo); `null` con la sesión perdida. */
    fun deCarga(e: Throwable): String? = when (MapeoErroresApi.deExcepcion(e)) {
        is FalloApi.SesionVencida -> null
        FalloApi.SinConexion -> CARGA_SIN_CONEXION
        else -> CARGA_FALLIDA
    }
}
