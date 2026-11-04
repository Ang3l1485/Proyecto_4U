package com.example.myapplication.data.local

import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.PuntoRecorrido

/**
 * Un recorrido grabado en el teléfono (`files/recoleccion/rec_NNNN/manifest.json`) tal como lo leen la vista 7.5, la
 * cola de subida y el `VideoRepository` compuesto (FE-2.1, ARCHITECTURE §5.6 y §5.10). Lo arma [ManifestRecorrido].
 */
data class RecorridoLocal(
    /** `rec_NNNN` (nombre de la carpeta). Es el `ref_cliente` del backend. */
    val id: String,
    val nombre: String,
    /** `created_at` (ISO-8601 con zona, p. ej. `2026-10-25T15:04:10-05:00`). */
    val creadoEn: String?,
    /** `ended_at`. */
    val finalizadoEn: String?,
    /** `estado = finalizado` (los `en_curso` se retoman en 7.4, no se suben). */
    val finalizado: Boolean,
    val inicioLat: Double?,
    val inicioLng: Double?,
    /** `start_heading`, 0…360. */
    val inicioRumbo: Double?,
    val duracionSegundos: Long?,
    val distanciaMetros: Double?,
    val pasos: Int?,
    val fotos: List<FotoLocal>,
    /** `progress.track` (FE-2.3); vacía si el manifest no lo tiene. */
    val trayectoria: List<PuntoRecorrido>,
    /** `remote_video_id`: UUID del video en el backend, o `null` si aún no se creó. */
    val remoteVideoId: String?,
    /** `subida_estado` (ausente = `SIN_SUBIR`). */
    val subida: EstadoSubida,
) {
    /** Fotos con `sync = pendiente`. */
    val fotosPendientes: Int get() = fotos.count { !it.subida }

    /** Nombre y fotos se pueden cambiar (descartar, renombrar) mientras el backend no conoce el video. */
    val editable: Boolean get() = remoteVideoId == null && subida != EstadoSubida.COMPLETADA
}

/** Una foto de un [RecorridoLocal]. */
data class FotoLocal(
    /** `"0001"`…: único dentro del recorrido; su número es el `orden` que se envía al backend. */
    val id: String,
    /** Ruta relativa a la carpeta del recorrido (`photos/0001.jpg`). */
    val archivo: String,
    val lat: Double,
    val lng: Double,
    /** `heading`, 0…360 (norte verdadero, del PDR), o `null`. */
    val rumbo: Double?,
    /** `captured_at`. */
    val capturadaEn: String?,
    /** `sync = subida`: su `PUT` respondió 2xx o el backend ya la tenía. */
    val subida: Boolean,
    /** Estado para mostrar (regla de `ManifestRecorrido.estadoFoto`). */
    val estado: EstadoFoto,
    /** `error`: motivo que dio el backend si la foto quedó en `error`. */
    val error: String?,
    /** `upload`: la copia re-codificada que se sube (o se subió). */
    val preparada: FotoPreparada?,
) {
    /** `orden` del backend (1…200): el número del id. `null` si el id no es un número en ese rango. */
    val orden: Int? get() = id.toIntOrNull()?.takeIf { it in 1..ORDEN_MAX }

    companion object {
        /** `REC_MAX_FOTOS_VIDEO` del backend (§5.10) y tope del `CHECK` de `orden`. */
        const val ORDEN_MAX = 200
    }
}

/** Copia re-codificada de una foto (clave `upload` del manifest): bytes y píxeles finales. */
data class FotoPreparada(val bytes: Long, val ancho: Int, val alto: Int)

/** `subida_estado` del manifest (ARCHITECTURE §5.10). */
enum class EstadoSubida(val clave: String) {
    /** Nunca se pidió subir, o la preparación falló antes de crear el video en el backend. */
    SIN_SUBIR("sin_subir"),

    /** Se pidió subir: la cola lo retoma cada vez que se abre el Panel o la vista 7.5 con sesión. */
    SUBIENDO("subiendo"),

    /** `complete` respondió sin fotos pendientes. */
    COMPLETADA("completada"),
    ;

    companion object {
        fun deClave(clave: String?): EstadoSubida = entries.firstOrNull { it.clave == clave } ?: SIN_SUBIR
    }
}
