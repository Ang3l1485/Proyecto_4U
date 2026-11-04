package com.example.myapplication.ui.ubicacion

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.CampoInvalido
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.RespuestaInesperadaException
import com.example.myapplication.data.remote.SinConexionException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * FE-3.2, apoyo del criterio C4: qué dice el Escaneo (6.2) ante cada error de `POST /v1/localize` (ARCHITECTURE §5.10,
 * «Ubicarse»). Con `embedding` apagado: «El servicio de ubicación no está disponible en este momento».
 */
class ErrorEscaneoTest {

    @Test
    fun embeddingNoDisponible_diceElTextoDe510() {
        val e = ApiException(FalloApi.EmbeddingNoDisponible, 503, "rid-1")
        val error = ErrorEscaneo.deExcepcion(e)
        assertEquals(ErrorEscaneo.SERVICIO_NO_DISPONIBLE, error)
        assertEquals("El servicio de ubicación no está disponible en este momento", error.mensaje)
    }

    @Test
    fun otro503_tambienEsServicioNoDisponible() {
        val e = ApiException(FalloApi.Desconocido(503, "BASE_NO_DISPONIBLE"), 503, null)
        assertEquals(ErrorEscaneo.SERVICIO_NO_DISPONIBLE, ErrorEscaneo.deExcepcion(e))
    }

    @Test
    fun sinRed_y_5xxDeApiGateway_sonSinConexion() {
        assertEquals(ErrorEscaneo.SIN_CONEXION, ErrorEscaneo.deExcepcion(SinConexionException()))
        assertEquals(ErrorEscaneo.SIN_CONEXION, ErrorEscaneo.deExcepcion(java.io.IOException("x")))
    }

    @Test
    fun demasiadosIntentos() {
        val e = ApiException(FalloApi.DemasiadosIntentos, 429, null)
        assertEquals(ErrorEscaneo.DEMASIADOS_INTENTOS, ErrorEscaneo.deExcepcion(e))
    }

    @Test
    fun fotosInvalidas_delBackend_o_alRecodificar() {
        val e = ApiException(FalloApi.FotosInvalidas(2, "embeddings la rechazó (IMAGEN_INVALIDA)"), 400, null)
        assertEquals(ErrorEscaneo.FOTOS_INVALIDAS, ErrorEscaneo.deExcepcion(e))
        assertEquals(ErrorEscaneo.FOTOS_INVALIDAS, ErrorEscaneo.deExcepcion(FotoIlegibleException("x")))
    }

    @Test
    fun loDemas_esDesconocido() {
        val validacion = FalloApi.Validacion(422, "VALIDACION", "m", listOf(CampoInvalido("metadatos.rumbos.1", "m")))
        assertEquals(ErrorEscaneo.DESCONOCIDO, ErrorEscaneo.deExcepcion(ApiException(validacion, 422, null)))
        val solicitud = ApiException(FalloApi.Desconocido(400, "SOLICITUD_INVALIDA"), 400, null)
        assertEquals(ErrorEscaneo.DESCONOCIDO, ErrorEscaneo.deExcepcion(solicitud))
        assertEquals(ErrorEscaneo.DESCONOCIDO, ErrorEscaneo.deExcepcion(RespuestaInesperadaException("x")))
        assertEquals(ErrorEscaneo.DESCONOCIDO, ErrorEscaneo.deExcepcion(IllegalStateException("x")))
    }

    @Test
    fun tiempoAgotado() {
        val e = runBlocking {
            try {
                withTimeout(1) { delay(1_000) }
                null
            } catch (t: TimeoutCancellationException) {
                t
            }
        }
        assertEquals(ErrorEscaneo.TIEMPO_AGOTADO, ErrorEscaneo.deExcepcion(e!!))
    }
}
