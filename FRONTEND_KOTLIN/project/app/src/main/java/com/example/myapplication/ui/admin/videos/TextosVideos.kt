package com.example.myapplication.ui.admin.videos

import com.example.myapplication.data.local.ManifestException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.MapeoErroresApi
import com.example.myapplication.data.repository.RecorridoNoEditableException
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.ResultadoLote
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.usecase.Fechas
import java.util.TimeZone

/**
 * Textos de 7.11, 7.13 y 7.14 (FE-4.1; lógica pura, `TextosVideosTest`). Los que lee `validate41.py` (§5.11) son
 * [total], [sinSubir], [descripcionFila] y los títulos de las pantallas: cambiarlos exige cambiar sus constantes.
 */
internal object TextosVideos {

    const val TITULO_LISTA = "Videos de recolección"
    const val SIN_CONEXION = "Sin conexión. Revisa tu conexión a internet e inténtalo de nuevo."

    /** Encabezado de 7.13: «1 video» / «N videos» (el `total` del servidor, sin separador de miles). */
    fun total(n: Int): String = if (n == 1) "1 video" else "$n videos"

    /** Indicador de 7.13: «1 sin subir en este teléfono» / «M sin subir en este teléfono». */
    fun sinSubir(m: Int): String = "$m sin subir en este teléfono"

    fun fotos(n: Int): String = if (n == 1) "1 foto" else "$n fotos"

    /** «340 m» o «1,25 km» (con el separador decimal de la región); `null` si no se midió. */
    fun distancia(m: Double?): String? = m?.let { if (it < 1000) "${Math.round(it)} m" else "%.2f km".format(it / 1000) }

    /** «8 min» (redondeado hacia abajo) o «45 s»; `null` si no se midió o es 0. */
    fun duracion(s: Long?): String? = when {
        s == null || s <= 0 -> null
        s < 60 -> "$s s"
        else -> "${s / 60} min"
    }

    fun estado(r: ResumenVideo): String = when {
        r.estado == EstadoVideo.SIN_SUBIR -> "Sin subir"
        r.estado == EstadoVideo.SUBIENDO -> "Subiendo desde este teléfono"
        r.fotos == 0 -> "Sin fotos"
        r.estado == EstadoVideo.SUBIDA_A_MEDIAS -> "Subida sin terminar"
        r.estado == EstadoVideo.PROCESANDO -> "Procesando"
        r.estado == EstadoVideo.PROCESADO -> "Procesado"
        else -> "Con errores"
    }

    /** «dd/MM/yyyy · N fotos · 340 m · 8 min» (lo que se sabe). La fecha, en la zona del teléfono. */
    fun detalleFila(r: ResumenVideo, zona: TimeZone = TimeZone.getDefault()): String =
        listOfNotNull(Fechas.fechaCorta(r.creadoEn, zona), fotos(r.fotos), distancia(r.distanciaMetros), duracion(r.duracionSegundos))
            .joinToString(" · ")

    /**
     * `content-desc` de una fila de 7.13: «Video <nombre>, [en este teléfono, ]<detalle>, <estado>». Empieza siempre por
     * «Video <nombre>,» (así lo busca `validate41.py`).
     */
    fun descripcionFila(r: ResumenVideo, zona: TimeZone = TimeZone.getDefault()): String =
        "Video ${r.nombre}, " + (if (r.local) "en este teléfono, " else "") + "${detalleFila(r, zona)}, ${estado(r)}"

    /**
     * Mensaje para la persona cuando falla [accion] («eliminar el video», «renombrar el video»…). `null` con la sesión
     * perdida (`AppNav` ya va a Login: no se muestra nada). Nunca lanza.
     */
    fun error(e: Throwable, accion: String): String? {
        if (e is RecorridoNoEditableException) return e.message
        if (e is ManifestException) return "No se pudo $accion: el recorrido del teléfono no se pudo leer."
        if (e is IllegalArgumentException) return "No se pudo $accion: el nombre no es válido (de 1 a 40 caracteres)."
        return when (val f = MapeoErroresApi.deExcepcion(e)) {
            is FalloApi.SesionVencida -> null
            FalloApi.SinConexion -> "Sin conexión: no se pudo $accion. Revisa tu conexión a internet e inténtalo de nuevo."
            FalloApi.SinPermisos -> "Tu cuenta no tiene permisos de administración: no se pudo $accion."
            FalloApi.DemasiadosIntentos -> "Demasiados intentos: espera un momento e inténtalo de nuevo."
            is FalloApi.Validacion -> "No se pudo $accion: ${f.mensaje ?: "datos no válidos"}."
            is FalloApi.Desconocido -> when (f.http) {
                404 -> "No se pudo $accion: ya no existe en el servidor (quizá lo borró otra persona)."
                else -> "Algo salió mal: no se pudo $accion. Inténtalo de nuevo."
            }
            else -> "Algo salió mal: no se pudo $accion. Inténtalo de nuevo."
        }
    }

    /** Resultado de un lote de la Galería: «Se eliminaron N fotos.» / «N fotos reasignadas a «X».» + las fallidas. */
    fun resultadoLote(accion: AccionLote, r: ResultadoLote, lugar: String?): String {
        val n = r.procesadas
        val hecho = when (accion) {
            AccionLote.ELIMINAR -> if (n == 1) "Se eliminó 1 foto." else "Se eliminaron $n fotos."
            AccionLote.REASIGNAR -> (if (n == 1) "1 foto reasignada" else "$n fotos reasignadas") + " a «${lugar ?: "Sin lugar"}»."
        }
        if (r.fallidas.isEmpty()) return hecho
        val porCodigo = r.fallidas.groupingBy { it.codigo }.eachCount()
        val partes = porCodigo.entries.joinToString("; ") { (codigo, k) ->
            when (codigo) {
                "NO_ENCONTRADO" -> "$k ya no existían"
                "VALIDACION" -> "$k porque el lugar ya no existe"
                else -> "$k por un error del servidor (inténtalo de nuevo)"
            }
        }
        val m = r.fallidas.size
        return "$hecho ${if (m == 1) "1 no se pudo" else "$m no se pudieron"}: $partes."
    }
}
