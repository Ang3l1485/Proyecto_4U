package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.FotoRecolectada
import com.example.myapplication.domain.model.ProgresoRecoleccion
import com.example.myapplication.domain.model.PuntoRecorrido
import com.example.myapplication.domain.model.VideoEnCurso
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-2.3 (C4): con qué estado se retoma un video `en_curso` tras matar el proceso (ARCHITECTURE §5.6 y §5.7). */
class RetomarRecoleccionTest {

    private val delta = 1e-9

    private fun foto(n: Int, lat: Double, lng: Double, rumbo: Float? = 90f, capturadaEnMs: Long = 1_000_000L + n * 1_000) =
        FotoRecolectada("%04d".format(n), "rec_0003", "/x/$n.jpg", lat, lng, rumbo, capturadaEnMs)

    private fun video(fotos: List<FotoRecolectada>, progreso: ProgresoRecoleccion?) =
        VideoEnCurso("rec_0003", "video_3", 6.2000, -75.5780, 45f, fotos, progreso)

    private fun progreso(
        trayectoria: List<PuntoRecorrido> = listOf(PuntoRecorrido(6.2000, -75.5780), PuntoRecorrido(6.2001, -75.5780)),
        indiceAnclaFoto: Int = 1,
        indiceAnclaTrayectoria: Int = 1,
        guardadoEnMs: Long = 1_010_000L,
    ) = ProgresoRecoleccion(
        lat = 6.20012, lng = -75.57795, rumbo = 370f, pasos = 30, distanciaMetros = 21.6, duracionSegundos = 95,
        distanciaAnclaM = 7.2, indiceAnclaFoto = indiceAnclaFoto, indiceAnclaTrayectoria = indiceAnclaTrayectoria,
        trayectoria = trayectoria, modo = ModoCaptura.PorTiempo(3), guardadoEnMs = guardadoEnMs,
    )

    @Test
    fun con_progreso_se_toma_tal_cual() {
        val fotos = listOf(foto(1, 6.2000, -75.5780), foto(2, 6.20005, -75.5780))
        val r = RetomarRecoleccion.estado(video(fotos, progreso()))
        assertTrue(r.conProgreso)
        assertEquals(6.20012, r.lat, delta)
        assertEquals(-75.57795, r.lng, delta)
        assertEquals(10f, r.rumbo, 1e-4f) // 370° normalizado
        assertEquals(30, r.pasos)
        assertEquals(21.6, r.distanciaMetros, delta)
        assertEquals(95, r.duracionSegundos)
        assertEquals(7.2, r.distanciaAnclaM, delta)
        assertEquals(1, r.indiceAnclaFoto)
        assertEquals(1, r.indiceAnclaTrayectoria)
        assertEquals(2, r.trayectoria.size)
        assertEquals(ModoCaptura.PorTiempo(3), r.modo)
    }

    @Test
    fun una_foto_posterior_al_progreso_da_la_posicion() {
        val fotos = listOf(foto(1, 6.2000, -75.5780), foto(2, 6.2002, -75.5779, rumbo = 180f, capturadaEnMs = 1_020_000L))
        val r = RetomarRecoleccion.estado(video(fotos, progreso(guardadoEnMs = 1_010_000L)))
        assertEquals(6.2002, r.lat, delta)
        assertEquals(-75.5779, r.lng, delta)
        assertEquals(180f, r.rumbo, 1e-4f)
        assertEquals(PuntoRecorrido(6.2002, -75.5779), r.trayectoria.last())
        assertEquals(3, r.trayectoria.size)
    }

    @Test
    fun la_foto_del_mismo_segundo_que_el_progreso_no_cuenta_como_posterior() {
        val fotos = listOf(foto(1, 6.2002, -75.5779, capturadaEnMs = 1_010_400L))
        val r = RetomarRecoleccion.estado(video(fotos, progreso(guardadoEnMs = 1_010_900L)))
        assertEquals(6.20012, r.lat, delta)
    }

    @Test
    fun indices_fuera_de_rango_se_recortan_y_trayectoria_vacia_es_el_inicio() {
        val r = RetomarRecoleccion.estado(
            video(listOf(foto(1, 6.2, -75.578)), progreso(trayectoria = emptyList(), indiceAnclaFoto = 9, indiceAnclaTrayectoria = 9)),
        )
        assertEquals(listOf(PuntoRecorrido(6.2000, -75.5780)), r.trayectoria)
        assertEquals(1, r.indiceAnclaFoto)
        assertEquals(1, r.indiceAnclaTrayectoria)
    }

    @Test
    fun sin_progreso_se_parte_de_la_ultima_foto_con_contadores_en_cero() {
        val fotos = listOf(foto(1, 6.2000, -75.5780, rumbo = null), foto(2, 6.2001, -75.5781, rumbo = -90f))
        val r = RetomarRecoleccion.estado(video(fotos, null))
        assertFalse(r.conProgreso)
        assertEquals(6.2001, r.lat, delta)
        assertEquals(-75.5781, r.lng, delta)
        assertEquals(270f, r.rumbo, 1e-4f)
        assertEquals(0, r.pasos)
        assertEquals(0.0, r.distanciaMetros, delta)
        assertEquals(0, r.duracionSegundos)
        assertEquals(ModoCaptura.POR_DEFECTO, r.modo)
        assertEquals(
            listOf(PuntoRecorrido(6.2000, -75.5780), PuntoRecorrido(6.2000, -75.5780), PuntoRecorrido(6.2001, -75.5781)),
            r.trayectoria,
        )
        // El ancla queda al final: un re-anclaje no mueve las fotos que ya había.
        assertEquals(2, r.indiceAnclaFoto)
        assertEquals(3, r.indiceAnclaTrayectoria)
    }

    @Test
    fun sin_progreso_ni_fotos_vuelve_al_punto_de_partida() {
        val r = RetomarRecoleccion.estado(video(emptyList(), null))
        assertEquals(6.2000, r.lat, delta)
        assertEquals(-75.5780, r.lng, delta)
        assertEquals(45f, r.rumbo, 1e-4f)
        assertEquals(listOf(PuntoRecorrido(6.2000, -75.5780)), r.trayectoria)
        assertEquals(0, r.indiceAnclaFoto)
    }
}
