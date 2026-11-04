package com.example.myapplication.domain.model

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Estado de procesamiento de una foto en el dataset. `PENDIENTE` (FE-2.1): todavía no se subió (`pendiente_subida` del
 * backend, o `sync = pendiente` en un recorrido local; ARCHITECTURE §5.6 y §5.10).
 */
enum class EstadoFoto(val etiqueta: String) {
    PENDIENTE("Pendiente"),
    SUBIDA("Subida"),
    PROCESADA("Procesada"),
    ERROR("Error"),
}

/** Calidad de la foto (hoy viene del manifest; luego la calculará el backend). */
enum class CalidadFoto(val etiqueta: String) {
    ALTA("Alta calidad"),
    NORMAL("Normal"),
    BAJA("Baja calidad"),
}

/**
 * Una foto del dataset.
 *
 * Las URLs ya vienen resueltas (FE-4.1): del backend, URLs GET prefirmadas de 1 h (`url`, `url_miniatura`); de un
 * recorrido del teléfono, la miniatura es `https://miniaturas.local/<rec>/<archivo>` (la sirve `MiniaturasLocales` dentro
 * del `WebView` de 7.14) y la foto, `file://` + la ruta del JPG. Las pantallas no distinguen la diferencia.
 */
data class Foto(
    /** Identificador: el UUID de la imagen en el backend; en un recorrido del teléfono, "0001"… (único en su video). */
    val id: String,
    val videoId: String,
    val videoNombre: String,
    val urlFoto: String,
    val urlMiniatura: String,
    val lat: Double,
    val lng: Double,
    /** Grados, 0 = norte, sentido horario. Null si no se conoce. */
    val rumbo: Float? = null,
    val capturadaEn: String? = null,
    val lugar: String? = null,
    val estado: EstadoFoto = EstadoFoto.PROCESADA,
    val calidad: CalidadFoto = CalidadFoto.NORMAL,
    /** FE-4.1: id del lugar asignado (`lugar.id` del backend), o `null`. */
    val lugarId: String? = null,
    /** FE-4.1: `orden` de la foto en su video (1…200), o `null`. */
    val orden: Int? = null,
) {
    /** Clave única en todo el dataset (el `id` de una foto local solo es único dentro de su video). */
    val uid: String get() = "$videoId/$id"

    /** Último tramo de la URL de la foto sin la *query* (la de una URL prefirmada lleva la firma). */
    val nombreArchivo: String get() = urlFoto.substringBefore('?').substringAfterLast('/')

    /** Lo que muestra la Galería: «Foto N» (su `orden`) o, sin orden, el nombre del archivo. */
    val titulo: String get() = orden?.let { "Foto $it" } ?: nombreArchivo
}

/**
 * Un recorrido de recolección ("video") con sus fotos: el detalle que dibuja 7.14 y que usa 7.3 para «Usar mi última
 * posición». FE-4.1 añade [local], [editable], [nota], [urlsVencenEnMs] y [finalizadoEn] (con valor por defecto).
 */
data class Video(
    val id: String,
    val nombre: String,
    val creadoEn: String? = null,
    val fotos: List<Foto> = emptyList(),
    /** Recorrido de este teléfono que el backend aún no conoce (`files/recoleccion/`, sin `remote_video_id`). */
    val local: Boolean = false,
    /** Se puede renombrar y eliminar (en uno local: no se está subiendo). */
    val editable: Boolean = true,
    /** Aviso visible en 7.14 (p. ej. por qué no se puede editar), o `null`. */
    val nota: String? = null,
    /** Vencimiento más temprano de las URLs prefirmadas de sus fotos (ms epoch), o `null` si no hay. */
    val urlsVencenEnMs: Long? = null,
    /** `finalizado_en` del backend o `ended_at` del manifest (ISO-8601 con zona), o `null`. */
    val finalizadoEn: String? = null,
) {
    /** Longitud de la trayectoria uniendo las fotos en orden (haversine). */
    val distanciaMetros: Double
        get() = fotos.zipWithNext { a, b -> distanciaEntre(a, b) }.sum()
}

private fun distanciaEntre(a: Foto, b: Foto): Double {
    val radio = 6_371_000.0
    val dLat = Math.toRadians(b.lat - a.lat)
    val dLng = Math.toRadians(b.lng - a.lng)
    val h = sin(dLat / 2).pow(2) + cos(Math.toRadians(a.lat)) * cos(Math.toRadians(b.lat)) * sin(dLng / 2).pow(2)
    return 2 * radio * asin(sqrt(h))
}