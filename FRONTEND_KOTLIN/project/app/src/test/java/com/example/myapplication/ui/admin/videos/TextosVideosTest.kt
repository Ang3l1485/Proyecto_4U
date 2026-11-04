package com.example.myapplication.ui.admin.videos

import com.example.myapplication.data.local.ManifestException
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.SinConexionException
import com.example.myapplication.data.repository.RecorridoNoEditableException
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.FallidaLote
import com.example.myapplication.domain.model.ResultadoLote
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.usecase.Fechas
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

/**
 * Textos de 7.11, 7.13 y 7.14 (FE-4.1): lo que lee `validate41.py` (encabezado, fila), las fechas (UTC del servidor y
 * zona del teléfono) y los mensajes de error, que nunca cierran la app ni muestran nada con la sesión perdida (C2).
 */
class TextosVideosTest {

    private val bogota = TimeZone.getTimeZone("America/Bogota")

    private fun fila(estado: EstadoVideo, fotos: Int = 3, local: Boolean = false) = ResumenVideo(
        id = "v1", nombre = "validacion-4-1-a", creadoEn = "2026-10-28T03:00:00Z", finalizadoEn = null, fotos = fotos,
        distanciaMetros = 1250.0, duracionSegundos = 512, estado = estado, local = local,
    )

    @Test
    fun encabezado_yContadores() {
        assertEquals("1 video", TextosVideos.total(1))
        assertEquals("1234 videos", TextosVideos.total(1234)) // sin separador de miles (lo lee validate41.py)
        assertEquals("0 videos", TextosVideos.total(0))
        assertEquals("13 sin subir en este teléfono", TextosVideos.sinSubir(13))
        assertEquals("1 foto", TextosVideos.fotos(1))
        assertEquals("120 m", TextosVideos.distancia(120.4))
        assertNull(TextosVideos.distancia(null))
        assertEquals("8 min", TextosVideos.duracion(512))
        assertEquals("45 s", TextosVideos.duracion(45))
        assertNull(TextosVideos.duracion(0))
    }

    @Test
    fun fechas_delServidorEnLaZonaDelTelefono_yDelManifestTalCual() {
        // 03:00 UTC del 28 son las 22:00 del 27 en Bogotá: la Lista no debe mostrar el día siguiente.
        assertEquals("27/10/2026", Fechas.fechaCorta("2026-10-28T03:00:00Z", bogota))
        assertEquals("25/10/2026", Fechas.fechaCorta("2026-10-25T15:04:10-05:00", bogota))
        assertEquals("09/10/2026", Fechas.fechaCorta("2026-10-09", bogota)) // sin hora: los 10 primeros caracteres
        assertNull(Fechas.fechaCorta("ayer", bogota))
        assertNull(Fechas.fechaCorta(null, bogota))
        // La misma hora en dos zonas da los mismos milisegundos; las fracciones se descartan.
        assertEquals(Fechas.aMilis("2026-10-25T20:04:10Z"), Fechas.aMilis("2026-10-25T15:04:10-05:00"))
        assertEquals(Fechas.aMilis("2026-10-25T20:04:10Z"), Fechas.aMilis("2026-10-25T20:04:10.731Z"))
        assertEquals(Fechas.aMilis("2026-10-25T20:04:10Z"), Fechas.aMilis("2026-10-25T21:04:10+01:00"))
        assertNull(Fechas.aMilis("2026-10-25T20:04:10")) // sin zona
    }

    @Test
    fun estado_yDescripcionDeLaFila() {
        assertEquals("Procesado", TextosVideos.estado(fila(EstadoVideo.PROCESADO)))
        assertEquals("Sin fotos", TextosVideos.estado(fila(EstadoVideo.PROCESADO, fotos = 0)))
        assertEquals("Subida sin terminar", TextosVideos.estado(fila(EstadoVideo.SUBIDA_A_MEDIAS)))
        assertEquals("Sin subir", TextosVideos.estado(fila(EstadoVideo.SIN_SUBIR, fotos = 0, local = true)))
        val servidor = TextosVideos.descripcionFila(fila(EstadoVideo.PROCESANDO), bogota)
        assertTrue(servidor, servidor.startsWith("Video validacion-4-1-a, 27/10/2026 · 3 fotos · "))
        assertTrue(servidor, servidor.endsWith(" · 8 min, Procesando"))
        val local = TextosVideos.descripcionFila(fila(EstadoVideo.SIN_SUBIR, local = true), bogota)
        assertTrue(local, local.startsWith("Video validacion-4-1-a, en este teléfono, 27/10/2026"))
    }

    @Test
    fun errores_nuncaLanzan_yLaSesionPerdidaNoMuestraNada() {
        val accion = "eliminar el video"
        assertTrue(TextosVideos.error(SinConexionException(), accion)!!.startsWith("Sin conexión: no se pudo eliminar el video."))
        assertNull(TextosVideos.error(ApiException(FalloApi.SesionVencida("TOKEN_EXPIRADO"), 401, null), accion))
        assertTrue(
            TextosVideos.error(ApiException(FalloApi.Desconocido(404, "NO_ENCONTRADO"), 404, null), accion)!!
                .contains("ya no existe en el servidor"),
        )
        assertEquals(
            "No se pudo renombrar el video: Revisa los datos.",
            TextosVideos.error(ApiException(FalloApi.Validacion(422, "VALIDACION", "Revisa los datos", emptyList()), 422, null), "renombrar el video"),
        )
        assertEquals(
            "Algo salió mal: no se pudo eliminar el video. Inténtalo de nuevo.",
            TextosVideos.error(ApiException(FalloApi.Desconocido(500, "ERROR_INTERNO"), 500, "rid"), accion),
        )
        assertEquals("Se está subiendo.", TextosVideos.error(RecorridoNoEditableException("Se está subiendo."), accion))
        assertTrue(TextosVideos.error(ManifestException("roto"), accion)!!.contains("no se pudo leer"))
        assertTrue(TextosVideos.error(IllegalArgumentException("vacío"), "renombrar el video")!!.contains("de 1 a 40"))
    }

    @Test
    fun resultadoDelLote_conYSinFallidas() {
        assertEquals("Se eliminó 1 foto.", TextosVideos.resultadoLote(AccionLote.ELIMINAR, ResultadoLote(1, emptyList()), null))
        assertEquals(
            "3 fotos reasignadas a «Sin lugar».",
            TextosVideos.resultadoLote(AccionLote.REASIGNAR, ResultadoLote(3, emptyList()), null),
        )
        val conFallidas = ResultadoLote(
            2,
            listOf(FallidaLote("a", "NO_ENCONTRADO"), FallidaLote("b", "NO_ENCONTRADO"), FallidaLote("c", "ERROR_INTERNO")),
        )
        assertEquals(
            "2 fotos reasignadas a «Biblioteca». 3 no se pudieron: 2 ya no existían; 1 por un error del servidor (inténtalo de nuevo).",
            TextosVideos.resultadoLote(AccionLote.REASIGNAR, conFallidas, "Biblioteca"),
        )
    }
}
