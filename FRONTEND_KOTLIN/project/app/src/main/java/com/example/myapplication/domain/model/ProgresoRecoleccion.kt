package com.example.myapplication.domain.model

import com.example.myapplication.domain.usecase.ModoCaptura

/** Punto de la trayectoria de una recolección (WGS84). */
data class PuntoRecorrido(val lat: Double, val lng: Double)

/**
 * Progreso de una grabación de la vista 7.4 que el ViewModel guarda en el manifest (clave `progress`) para poder
 * retomarla si Android mata el proceso (FE-2.3). Las fotos no van aquí: ya están en `photos`.
 */
data class ProgresoRecoleccion(
    val lat: Double,
    val lng: Double,
    /** 0…360, 0 = norte, sentido horario. */
    val rumbo: Float,
    val pasos: Int,
    val distanciaMetros: Double,
    /** Tiempo grabando, sin contar las pausas. */
    val duracionSegundos: Long,
    /** `distanciaMetros` en el último re-anclaje (0 = el inicio): la deriva se mide desde aquí. */
    val distanciaAnclaM: Double,
    /** Primera foto posterior al último re-anclaje (las anteriores ya están ancladas). */
    val indiceAnclaFoto: Int,
    /** Primer punto de [trayectoria] posterior al último re-anclaje. */
    val indiceAnclaTrayectoria: Int,
    val trayectoria: List<PuntoRecorrido>,
    val modo: ModoCaptura,
    /** Milisegundos epoch (en el manifest, ISO-8601 con segundos). */
    val guardadoEnMs: Long,
)

/** Un video que quedó `en_curso` en `files/recoleccion/`, tal como lo lee `RecoleccionRepository.leerEnCurso`. */
data class VideoEnCurso(
    val videoId: String,
    val nombre: String,
    val inicioLat: Double,
    val inicioLng: Double,
    /** 0…360 (`start_heading`). */
    val inicioRumbo: Float,
    /** En el orden del manifest, con las coordenadas ya corregidas por los re-anclajes. */
    val fotos: List<FotoRecolectada>,
    /** `null` si el manifest no trae `progress` (video anterior a FE-2.3, o progreso ilegible). */
    val progreso: ProgresoRecoleccion?,
)
