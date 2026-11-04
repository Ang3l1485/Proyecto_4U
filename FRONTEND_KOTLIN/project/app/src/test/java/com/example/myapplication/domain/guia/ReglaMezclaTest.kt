package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.ResultadoFrame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** FE-5.3: la regla simple de mezcla (aceptar o descartar una foto), el radio pedido y cuándo tomar la foto. */
class ReglaMezclaTest {

    private fun ubicado(dist: Double, nivel: NivelConfianza = NivelConfianza.ALTA, lat: Double = 6.2001, lng: Double = -75.5785) =
        ResultadoFrame.Ubicado(lat, lng, 5.0, 0.9, nivel, dist, 40.0, 12)

    @Test
    fun limiteYRadio() {
        assertEquals(8.0, ReglaMezcla.limiteCoherenciaM(0.0), 1e-9)
        assertEquals(10.5, ReglaMezcla.limiteCoherenciaM(5.0), 1e-9)
        assertEquals(13.0, ReglaMezcla.limiteCoherenciaM(10.0), 1e-9)
        assertEquals(40.0, ReglaMezcla.radioM(10.0), 1e-9)   // 23 → mínimo 40
        assertEquals(68.0, ReglaMezcla.radioM(100.0), 1e-9)  // 8 + 50 + 10
        assertEquals(100.0, ReglaMezcla.radioM(500.0), 1e-9) // máximo del backend
    }

    @Test
    fun unSaltoDe40MetrosTras5MetrosSeDescarta() {
        val d = ReglaMezcla.decidir(ubicado(40.0), 5.0, 6.2, -75.5, 6.2, -75.5)
        assertEquals(DecisionFrame.Descartar(MotivoDescarte.INCOHERENTE, 10.5), d)
    }

    @Test
    fun confiableYCoherenteReemplazaComoDesplazamiento() {
        // previa (6.2000, −75.5785); la foto dice 6.2001 (≈ 11 m al norte). Mientras llegaba la respuesta la persona
        // avanzó a 6.20003: la posición nueva es la actual + (foto − previa).
        val d = ReglaMezcla.decidir(ubicado(9.0), 10.0, 6.2000, -75.5785, 6.20003, -75.5785)
        d as DecisionFrame.Aceptar
        assertEquals(6.20013, d.lat, 1e-9)
        assertEquals(-75.5785, d.lng, 1e-9)
        assertEquals(13.0, d.limiteM, 1e-9)
    }

    @Test
    fun nivelBajoYSinCoincidenciasSeDescartan() {
        assertEquals(
            MotivoDescarte.NIVEL_BAJO,
            (ReglaMezcla.decidir(ubicado(2.0, NivelConfianza.BAJA), 5.0, 0.0, 0.0, 0.0, 0.0) as DecisionFrame.Descartar).motivo,
        )
        assertTrue(ReglaMezcla.decidir(ubicado(2.0, NivelConfianza.MEDIA), 5.0, 0.0, 0.0, 0.0, 0.0) is DecisionFrame.Aceptar)
        assertEquals(
            MotivoDescarte.SIN_COINCIDENCIAS,
            (ReglaMezcla.decidir(ResultadoFrame.SinCoincidencias(40.0, 0), 5.0, 0.0, 0.0, 0.0, 0.0) as DecisionFrame.Descartar).motivo,
        )
        // Solo «alta» si el campo muestra que «media» acepta fotos equivocadas (backend §4.14).
        val soloAlta = ParametrosGuia(nivelesAceptados = setOf(NivelConfianza.ALTA))
        assertTrue(ReglaMezcla.decidir(ubicado(2.0, NivelConfianza.MEDIA), 5.0, 0.0, 0.0, 0.0, 0.0, soloAlta) is DecisionFrame.Descartar)
    }

    @Test
    fun disparadorCadaDiezMetrosOAntesSiEsDudosa() {
        val d = DisparadorFoto()
        assertFalse(d.debeTomar(9.9, 0.0, ocupado = false))
        assertTrue(d.debeTomar(10.0, 0.0, ocupado = false))
        assertFalse(d.debeTomar(10.0, 0.0, ocupado = true))
        d.tomada(10.0)
        assertFalse(d.debeTomar(12.0, 9.0, ocupado = false)) // dudosa, pero solo 2 m desde la anterior
        assertTrue(d.debeTomar(13.0, 8.0, ocupado = false))  // dudosa y 3 m
        assertFalse(d.debeTomar(13.0, 7.9, ocupado = false))
        assertTrue(d.debeTomar(20.0, 0.0, ocupado = false))
    }

    @Test
    fun desvioConLecturasSeguidas() {
        val d = DetectorDesvio()
        assertFalse(d.lectura(16.0))
        assertFalse(d.lectura(16.0))
        assertFalse(d.lectura(16.0))
        assertFalse(d.lectura(15.0)) // a 15 m no cuenta: reinicia
        repeat(3) { assertFalse(d.lectura(20.0)) }
        assertTrue(d.lectura(20.0))
        assertEquals(0, d.seguidas)
    }
}
