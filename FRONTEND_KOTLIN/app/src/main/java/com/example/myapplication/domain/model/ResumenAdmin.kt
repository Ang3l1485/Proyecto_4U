package com.example.myapplication.domain.model

/** Datos del "Resumen rápido" del Panel admin (vista 7.2). */
data class ResumenAdmin(
    val totalFotos: Int,
    val totalLugares: Int,
    val alertasActivas: Int,
    /** Número del último video recolectado (video12 → 12). Null si aún no hay videos. */
    val ultimoVideoNumero: Int?,
    /** Fecha/hora de ese video, en milisegundos epoch. */
    val ultimoVideoFecha: Long?,
    /** Fotos guardadas en el teléfono que aún no se han subido (cola local). */
    val fotosPendientes: Int,
)