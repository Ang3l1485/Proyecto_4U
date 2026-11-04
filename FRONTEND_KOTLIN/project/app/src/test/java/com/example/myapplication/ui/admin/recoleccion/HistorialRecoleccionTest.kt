package com.example.myapplication.ui.admin.recoleccion

import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.model.Video
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * FE-4.1: 7.3 cuenta los videos del servidor y los recorridos del teléfono para el nombre autonumerado y «Usar mi
 * última posición», comparando fechas de zonas distintas (el servidor da UTC con `Z`; el manifest, la del teléfono).
 */
class HistorialRecoleccionTest {

    private fun foto(id: String, lat: Double, capturada: String) =
        Foto(id, "v", "v", "", "", lat, -75.5, rumbo = 90f, capturadaEn = capturada)

    private fun local(id: String, fin: String?, vararg fotos: Foto) =
        Video(id, id, creadoEn = "2026-10-25T08:00:00-05:00", fotos = fotos.toList(), local = true, finalizadoEn = fin)

    private fun remoto(id: String, fin: String?, fotos: Int = 5) = ResumenVideo(
        id, "video_$id", creadoEn = "2026-10-27T20:00:00Z", finalizadoEn = fin, fotos = fotos,
        distanciaMetros = null, duracionSegundos = null, estado = EstadoVideo.PROCESADO,
    )

    @Test
    fun siguienteNombre_cuentaServidorYTelefono_sinRepetir() {
        assertEquals("video_14", siguienteNombre(listOf("video_3", "video_13", "Entrada norte")))
        // Un recorrido subido aparece en las dos listas con el mismo nombre: no cambia el resultado.
        assertEquals("video_4", siguienteNombre(listOf("video_3", "video_3")))
        // Ninguno con el patrón: la cantidad de nombres distintos + 1, saltando los usados.
        assertEquals("video_3", siguienteNombre(listOf("Entrada", "Bloque 19")))
        assertEquals("video_1", siguienteNombre(emptyList()))
    }

    @Test
    fun masRecienteDelServidor_comparaEnMilisegundosEntreZonas() {
        // El local terminó a las 15:00 de Bogotá (20:00 UTC); el del servidor, a las 19:30 UTC: gana el local.
        val locales = listOf(local("rec_0013", "2026-10-27T15:00:00-05:00", foto("0001", 6.2, "2026-10-27T15:00:00-05:00")))
        assertNull(masRecienteDelServidor(locales, listOf(remoto("a", "2026-10-27T19:30:00Z"))))
        // Termina a las 20:30 UTC: gana el del servidor.
        assertEquals("b", masRecienteDelServidor(locales, listOf(remoto("a", "2026-10-27T19:30:00Z"), remoto("b", "2026-10-27T20:30:00Z"))))
        // Sin fotos registradas no cuenta; empate: el del teléfono (no necesita red).
        assertNull(masRecienteDelServidor(locales, listOf(remoto("c", "2026-10-28T00:00:00Z", fotos = 0))))
        assertNull(masRecienteDelServidor(locales, listOf(remoto("d", "2026-10-27T20:00:00Z"))))
        // Sin nada en el teléfono: el del servidor, aunque solo tenga creado_en.
        assertEquals("e", masRecienteDelServidor(emptyList(), listOf(remoto("e", null))))
    }

    @Test
    fun calcularUltimaPosicion_eligeElQueTerminoDespues_ySuUltimaFoto() {
        val viejo = local("rec_0001", "2026-10-25T09:00:00-05:00", foto("0001", 6.1, "2026-10-25T08:59:00-05:00"))
        val nuevo = Video(
            "srv", "video_9", creadoEn = "2026-10-26T00:00:00Z", finalizadoEn = "2026-10-25T15:00:00Z",
            fotos = listOf(foto("img-2", 6.3, "2026-10-25T14:59:00Z"), foto("img-1", 6.2, "2026-10-25T14:00:00Z")),
        )

        val ultima = calcularUltimaPosicion(listOf(nuevo, viejo))!!

        assertEquals("video_9", ultima.videoNombre)
        assertEquals(6.3, ultima.punto.lat, 0.0) // la de mayor capturadaEn
        assertEquals(90f, ultima.rumbo)
    }
}
