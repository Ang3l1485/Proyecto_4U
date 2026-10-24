package com.example.myapplication.domain.model

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** Estado de procesamiento de una foto en el dataset. */
enum class EstadoFoto(val etiqueta: String) {
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
 * Las URLs ya vienen resueltas: hoy son `file:///android_asset/...`; cuando exista S3
 * serán URLs prefirmadas que entrega el backend. Las pantallas no distinguen la diferencia.
 */
data class Foto(
    /** Identificador dentro del video, p. ej. "0001". */
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
) {
    /** Clave única en todo el dataset (el `id` solo es único dentro de su video). */
    val uid: String get() = "$videoId/$id"

    val nombreArchivo: String get() = urlFoto.substringAfterLast('/')
}

/** Un recorrido de recolección ("video") con sus fotos. */
data class Video(
    val id: String,
    val nombre: String,
    val creadoEn: String? = null,
    val fotos: List<Foto> = emptyList(),
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