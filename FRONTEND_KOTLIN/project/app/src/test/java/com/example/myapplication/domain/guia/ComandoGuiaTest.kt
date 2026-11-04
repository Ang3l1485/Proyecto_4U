package com.example.myapplication.domain.guia

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.RespuestaInesperadaException
import com.example.myapplication.data.remote.SinConexionException
import com.example.myapplication.ui.navegacion.falloFrameDe
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-5.3: el comando de voz «guíame» de 6.3 y cómo se clasifica un fallo de `POST /v1/localize/frame`. */
class ComandoGuiaTest {

    @Test
    fun comandoGuiar() {
        assertTrue(ComandoGuia.esGuiar("Guíame"))
        assertTrue(ComandoGuia.esGuiar("guiame guía me guiar"))
        assertTrue(ComandoGuia.esGuiar("llévame, por favor"))
        assertTrue(ComandoGuia.esGuiar("¡Vamos!"))
        assertFalse(ComandoGuia.esGuiar("no me guíes no guía"))
        assertFalse(ComandoGuia.esGuiar("repetir"))
        assertFalse(ComandoGuia.esGuiar("guianza"))
        assertFalse(ComandoGuia.esGuiar(""))
    }

    @Test
    fun falloDeLaFoto() {
        assertEquals(FalloFrame.SIN_CONEXION, falloFrameDe(SinConexionException()))
        assertEquals(FalloFrame.FOTO_NO_VALIDA, falloFrameDe(FotoIlegibleException("x")))
        assertEquals(FalloFrame.SERVICIO_NO_DISPONIBLE, falloFrameDe(ApiException(FalloApi.EmbeddingNoDisponible, 503, null)))
        assertEquals(FalloFrame.SERVICIO_NO_DISPONIBLE, falloFrameDe(ApiException(FalloApi.Desconocido(503, "BASE_NO_DISPONIBLE"), 503, null)))
        assertEquals(FalloFrame.FOTO_NO_VALIDA, falloFrameDe(ApiException(FalloApi.FotosInvalidas(0, "m"), 400, null)))
        assertEquals(FalloFrame.OTRO, falloFrameDe(ApiException(FalloApi.Validacion(422, "VALIDACION", "m", emptyList()), 422, null)))
        assertEquals(FalloFrame.OTRO, falloFrameDe(RespuestaInesperadaException("x")))
    }
}
