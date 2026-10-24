package com.example.myapplication.domain.model

/**
 * Una foto tomada durante una recolección (vista 7.4).
 *
 * `id` es único solo dentro del video y va con ceros a la izquierda ("0001"), igual que en el
 * `manifest.json` de `assets/videos/` (11.6): así se ordena bien como texto.
 */
data class FotoRecolectada(
    val id: String,
    val videoId: String,
    /** Ruta absoluta del JPG en el almacenamiento privado de la app. */
    val rutaArchivo: String,
    val lat: Double,
    val lng: Double,
    /** Grados 0..360, 0 = norte, sentido horario; `null` si se desconoce. */
    val rumbo: Float?,
    /** Milisegundos epoch. */
    val capturadaEnMs: Long,
    /** `true` hasta que se suba al backend (alimenta "fotos pendientes" del panel, 7.2). */
    val pendienteSubida: Boolean = true,
) {
    /** Clave única entre videos (misma convención que `Foto.uid`). */
    val uid: String get() = "$videoId/$id"
}

/** Datos que acompañan a una foto recién tomada. */
data class DatosFoto(
    val lat: Double,
    val lng: Double,
    val rumbo: Float?,
    val capturadaEnMs: Long,
)

/** Resumen guardado al finalizar un video (lo consumirá la vista 7.5). */
data class ResumenRecoleccion(
    val videoId: String,
    val nombre: String,
    val duracionSegundos: Long,
    val distanciaMetros: Double,
    val pasos: Int,
    val totalFotos: Int,
)