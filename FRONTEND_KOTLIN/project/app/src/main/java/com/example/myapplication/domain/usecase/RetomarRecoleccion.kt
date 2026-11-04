package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.PuntoRecorrido
import com.example.myapplication.domain.model.VideoEnCurso

/** Con qué estado vuelve la vista 7.4 a un video `en_curso` (FE-2.3). */
data class EstadoRetomado(
    val lat: Double,
    val lng: Double,
    /** 0…360. */
    val rumbo: Float,
    /** Pasos, distancia y duración acumulados antes de morir el proceso: el ViewModel les suma los del tracker nuevo. */
    val pasos: Int,
    val distanciaMetros: Double,
    val duracionSegundos: Long,
    val distanciaAnclaM: Double,
    val indiceAnclaFoto: Int,
    val indiceAnclaTrayectoria: Int,
    val trayectoria: List<PuntoRecorrido>,
    val modo: ModoCaptura,
    /** `false` = el manifest no traía `progress`: contadores en 0 y conviene re-anclarse antes de seguir. */
    val conProgreso: Boolean,
)

/**
 * Lógica pura (sin Android) para retomar una grabación tras matar el proceso (FE-2.3, criterio C4).
 *
 * - Con `progress`: se toma tal cual (índices recortados al tamaño real; trayectoria vacía → el punto de partida).
 *   Si la última foto es **posterior** al progreso guardado (comparando segundos), la posición y el rumbo salen de
 *   esa foto y su punto se añade a la trayectoria.
 * - Sin `progress`: la posición es la de la última foto (o el punto de partida si no hay fotos), la trayectoria es
 *   el punto de partida más las fotos, pasos, distancia y duración vuelven a 0, el intervalo es el por defecto y el
 *   ancla queda **al final** (un re-anclaje posterior no mueve las fotos que ya había: no se sabe si estaban bien).
 */
object RetomarRecoleccion {

    fun estado(video: VideoEnCurso): EstadoRetomado {
        val inicio = PuntoRecorrido(video.inicioLat, video.inicioLng)
        val ultima = video.fotos.lastOrNull()
        val p = video.progreso

        if (p == null) {
            val trayectoria = listOf(inicio) + video.fotos.map { PuntoRecorrido(it.lat, it.lng) }
            return EstadoRetomado(
                lat = ultima?.lat ?: video.inicioLat,
                lng = ultima?.lng ?: video.inicioLng,
                rumbo = normalizar(ultima?.rumbo ?: video.inicioRumbo),
                pasos = 0,
                distanciaMetros = 0.0,
                duracionSegundos = 0,
                distanciaAnclaM = 0.0,
                indiceAnclaFoto = video.fotos.size,
                indiceAnclaTrayectoria = trayectoria.size,
                trayectoria = trayectoria,
                modo = ModoCaptura.POR_DEFECTO,
                conProgreso = false,
            )
        }

        var trayectoria = p.trayectoria.ifEmpty { listOf(inicio) }
        var lat = p.lat
        var lng = p.lng
        var rumbo = p.rumbo
        if (ultima != null && ultima.capturadaEnMs / 1000 > p.guardadoEnMs / 1000) {
            lat = ultima.lat
            lng = ultima.lng
            rumbo = ultima.rumbo ?: p.rumbo
            trayectoria = trayectoria + PuntoRecorrido(ultima.lat, ultima.lng)
        }
        return EstadoRetomado(
            lat = lat,
            lng = lng,
            rumbo = normalizar(rumbo),
            pasos = p.pasos.coerceAtLeast(0),
            distanciaMetros = p.distanciaMetros.coerceAtLeast(0.0),
            duracionSegundos = p.duracionSegundos.coerceAtLeast(0),
            distanciaAnclaM = p.distanciaAnclaM.coerceIn(0.0, p.distanciaMetros.coerceAtLeast(0.0)),
            indiceAnclaFoto = p.indiceAnclaFoto.coerceIn(0, video.fotos.size),
            indiceAnclaTrayectoria = p.indiceAnclaTrayectoria.coerceIn(0, trayectoria.size),
            trayectoria = trayectoria,
            modo = p.modo,
            conProgreso = true,
        )
    }

    private fun normalizar(grados: Float): Float = ((grados % 360f) + 360f) % 360f
}
