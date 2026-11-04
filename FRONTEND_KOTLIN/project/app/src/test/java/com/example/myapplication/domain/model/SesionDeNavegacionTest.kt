package com.example.myapplication.domain.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.2, decisión abierta 15 (ADR-FE-24): el holder del flujo público guarda destino y ubicación en memoria; una
 * ubicación es vigente con nivel alta o media y como mucho 2 min. Se prueba [SesionNavegacion] con un reloj falso
 * (el objeto `SesionDeNavegacion` usa `System.nanoTime`).
 */
class SesionDeNavegacionTest {

    private var ahora = 1_000_000L
    private val sesion = SesionNavegacion { ahora }

    private fun ubicado(nivel: NivelConfianza = NivelConfianza.ALTA) = ResultadoUbicacion.Ubicado(
        posicion = PosicionEstimada(6.2001, -75.5786, 8.5),
        confianza = 0.78,
        nivel = nivel,
        correccionRumboGrados = null,
        lugarCercano = null,
        referencias = emptyList(),
        fotosUsadas = 5,
        fotosConCoincidencia = 4,
    )

    private val biblioteca = LugarDestino("b", "Biblioteca Central", CategoriaLugar.BIBLIOTECA, 6.2009, -75.5783)

    @Test
    fun registrar_guardaLaHoraYElRumbo_yEsVigenteDosMinutos() {
        val u = sesion.registrar(ubicado(), 354.0)
        assertEquals(1_000_000L, u.obtenidaEnMs)
        assertEquals(354.0, u.rumboAlTerminar!!, 0.0)
        assertEquals(u, sesion.ubicacion.value)
        assertEquals(6.2001 to -75.5786, sesion.posicionVigente())

        ahora += UbicacionEstimada.VIGENCIA_MS
        assertNotNull(sesion.ubicacionVigente())
        ahora += 1
        assertNull(sesion.ubicacionVigente())
        assertNull(sesion.posicionVigente())
        // Sigue guardada (para la declinación y para 6.3), aunque ya no sea vigente.
        assertEquals(6.2001, sesion.ultimaPosicion()!!.lat, 0.0)
    }

    @Test
    fun media_esVigente_baja_y_sinCoincidencias_no() {
        sesion.registrar(ubicado(NivelConfianza.MEDIA), null)
        assertNotNull(sesion.ubicacionVigente())
        sesion.registrar(ubicado(NivelConfianza.BAJA), null)
        assertNull(sesion.ubicacionVigente())
        assertNotNull(sesion.ultimaPosicion())
        sesion.registrar(ResultadoUbicacion.SinCoincidencias(5), null)
        assertNull(sesion.ubicacionVigente())
        assertNull(sesion.ultimaPosicion())
    }

    @Test
    fun relojHaciaAtras_noEsVigente() {
        sesion.registrar(ubicado(), null)
        ahora -= 1
        assertNull(sesion.ubicacionVigente())
    }

    @Test
    fun destino_elegir_quitar_y_limpiar() {
        assertNull(sesion.destino.value)
        sesion.elegirDestino(biblioteca)
        assertEquals(biblioteca, sesion.destino.value)
        sesion.quitarDestino()
        assertNull(sesion.destino.value)

        sesion.elegirDestino(biblioteca)
        sesion.registrar(ubicado(), null)
        sesion.limpiar()
        assertNull(sesion.destino.value)
        assertNull(sesion.ubicacion.value)
    }

    @Test
    fun holderDelProceso_usaElRelojMonotono() {
        SesionDeNavegacion.limpiar()
        SesionDeNavegacion.registrar(ubicado(), null)
        assertTrue(SesionDeNavegacion.ubicacionVigente() != null)
        SesionDeNavegacion.limpiar()
    }
}
