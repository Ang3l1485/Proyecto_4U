package com.example.myapplication.ui.admin.recoleccion

import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.domain.model.EstadoFoto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

/**
 * Propiedades calculadas de los estados de las vistas 7.2 (`UbicacionManualUiState`), 7.4 (`RecoleccionUiState`) y
 * 7.5 (`ResumenVideoUiState`, `SubidaUi`). Lógica pura: solo construye estados y lee sus propiedades.
 */
class EstadosRecoleccionTest {

    private fun foto(id: String, estado: EstadoFoto) = FotoResumen(id, "/fotos/$id.jpg", estado)

    private fun resumenListo() = ResumenVideoUiState(
        cargando = false,
        videoId = "rec_0001",
        nombre = "video_1",
        fotos = listOf(foto("f1", EstadoFoto.PENDIENTE), foto("f2", EstadoFoto.PENDIENTE)),
    )

    // --- 7.4 RecoleccionUiState ---------------------------------------------------------------------------------

    @Test
    fun grabandoOPausada_enCurso_esTrue() {
        assertTrue(RecoleccionUiState(fase = FaseRecoleccion.GRABANDO).enCurso)
        assertTrue(RecoleccionUiState(fase = FaseRecoleccion.PAUSADA).enCurso)
    }

    @Test
    fun iniciandoOFinalizando_enCurso_esFalse() {
        assertFalse(RecoleccionUiState(fase = FaseRecoleccion.INICIANDO).enCurso)
        assertFalse(RecoleccionUiState(fase = FaseRecoleccion.FINALIZANDO).enCurso)
    }

    @Test
    fun fotosEnElLimite_llegoAlMaximo_soloDesdeMaxFotosVideo() {
        assertFalse(RecoleccionUiState(fotosTomadas = MAX_FOTOS_VIDEO - 1).llegoAlMaximo)
        assertTrue(RecoleccionUiState(fotosTomadas = MAX_FOTOS_VIDEO).llegoAlMaximo)
    }

    @Test
    fun conOSinPuntoDeReanclaje_reubicando_loRefleja() {
        assertFalse(RecoleccionUiState().reubicando)
        assertTrue(RecoleccionUiState(reanclaje = PuntoReanclaje(6.2, -75.578)).reubicando)
    }

    // --- 7.5 ResumenVideoUiState y SubidaUi ----------------------------------------------------------------------

    @Test
    fun recorridoConNombreYFotosSinSubir_puedeSubirYEditable_sonTrue() {
        val estado = resumenListo()

        assertTrue(estado.puedeSubir)
        assertTrue(estado.editable)
    }

    @Test
    fun nombreEnBlancoOSinFotosOSinId_puedeSubir_esFalse() {
        assertFalse(resumenListo().copy(nombre = "  ").puedeSubir)
        assertFalse(resumenListo().copy(fotos = emptyList()).puedeSubir)
        assertFalse(resumenListo().copy(videoId = null).puedeSubir)
    }

    @Test
    fun subidaCompletadaOEnCurso_puedeSubirYEditable_sonFalse() {
        val completada = resumenListo().copy(estadoSubida = EstadoSubida.COMPLETADA)
        val subiendo = resumenListo().copy(subida = SubidaUi(fase = FaseCola.SUBIENDO))

        assertFalse(completada.puedeSubir)
        assertFalse(completada.editable)
        assertFalse(subiendo.puedeSubir)
        assertFalse(subiendo.editable)
    }

    @Test
    fun yaEnviadoAlBackend_editable_esFalse() {
        assertFalse(resumenListo().copy(enviadoAlBackend = true).editable)
    }

    @Test
    fun fasesDeLaCola_activa_soloMientrasTrabajaOEsperaConexion() {
        val activas = setOf(FaseCola.PREPARANDO, FaseCola.SUBIENDO, FaseCola.COMPLETANDO, FaseCola.SIN_CONEXION)
        for (fase in FaseCola.entries) {
            assertEquals("fase=$fase", fase in activas, SubidaUi(fase = fase).activa)
        }
    }

    @Test
    fun fotosEnVariosEstados_subidasYConteo_cuentanPorEstado() {
        val estado = resumenListo().copy(
            fotos = listOf(
                foto("f1", EstadoFoto.PENDIENTE),
                foto("f2", EstadoFoto.SUBIDA),
                foto("f3", EstadoFoto.PROCESADA),
                foto("f4", EstadoFoto.ERROR),
                foto("f5", EstadoFoto.PROCESADA),
            ),
        )

        assertEquals(4, estado.subidas)
        assertEquals(
            mapOf(EstadoFoto.PENDIENTE to 1, EstadoFoto.SUBIDA to 1, EstadoFoto.PROCESADA to 2, EstadoFoto.ERROR to 1),
            estado.conteo,
        )
    }

    @Test
    fun completadaYTodasProcesadasOConError_terminado_esTrue() {
        val estado = resumenListo().copy(
            estadoSubida = EstadoSubida.COMPLETADA,
            fotos = listOf(foto("f1", EstadoFoto.PROCESADA), foto("f2", EstadoFoto.ERROR)),
        )

        assertTrue(estado.terminado)
    }

    @Test
    fun fotoAunSubidaOSinFotos_terminado_esFalse() {
        val completada = resumenListo().copy(estadoSubida = EstadoSubida.COMPLETADA)

        assertFalse(completada.copy(fotos = listOf(foto("f1", EstadoFoto.PROCESADA), foto("f2", EstadoFoto.SUBIDA))).terminado)
        assertFalse(completada.copy(fotos = emptyList()).terminado)
    }

    // --- 7.2 UbicacionManualUiState -------------------------------------------------------------------------------

    @Test
    fun conPuntoYSinConfirmar_puedeConfirmar_esTrueYMuestraCoordenadas() {
        val estado = UbicacionManualUiState(punto = PuntoMapa(6.2006, -75.5783))

        assertTrue(estado.puedeConfirmar)
        assertEquals("6.200600", estado.latitudTexto)
        assertEquals("-75.578300", estado.longitudTexto)
    }

    @Test
    fun sinPuntoOConfirmando_puedeConfirmar_esFalse() {
        val sinPunto = UbicacionManualUiState()

        assertFalse(sinPunto.puedeConfirmar)
        assertEquals("—", sinPunto.latitudTexto)
        assertEquals("—", sinPunto.longitudTexto)
        assertFalse(UbicacionManualUiState(punto = PuntoMapa(6.2, -75.5), confirmando = true).puedeConfirmar)
    }

    @Test
    fun regionConComaDecimal_formatearCoordenada_usaPuntoYSeisDecimales() {
        val original = Locale.getDefault()
        try {
            Locale.setDefault(Locale.GERMANY)

            assertEquals("6.200512", formatearCoordenada(6.2005123))
        } finally {
            Locale.setDefault(original)
        }
    }
}
