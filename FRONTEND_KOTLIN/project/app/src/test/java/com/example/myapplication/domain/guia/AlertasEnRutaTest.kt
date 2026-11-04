package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.ruta.GrafosDePrueba
import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-5.3 (fase 2): las alertas públicas de FE-3.6 en la guía. Solo las cercanas a la ruta (centro a ≤ radio +
 * `alertaRutaM` de la polilínea; decisión abierta 3), alta primero, una vez por aproximación, con la línea del registro.
 */
class AlertasEnRutaTest {

    private val g = GrafosDePrueba
    // Ruta en el cuadrado desde (50, −5): por A–B hasta B y por B–C hasta C (150 m).
    private val ruta = (
        Planificador(g.cuadrado()).calcular(g.lat(-5.0), g.lng(50.0), g.lat(100.0), g.lng(100.0), "Meta", null)
            as ResultadoRuta.Encontrada
        ).ruta
    private val enLaRutaAlta = Alerta("alta", g.lat(52.0), g.lng(100.0), "Ten cuidado, hay escalones", prioridad = "alta", radio = 5)
    private val enLaRuta = Alerta("normal", g.lat(50.0), g.lng(101.0), "Hay bancas", radio = 5)
    // 25 m al este de B–C, radio 12: con 20 m de incertidumbre la persona en (100, 50) queda dentro de su umbral (32 m),
    // pero la alerta no está cerca de la ruta (25 > 12 + 10).
    private val paralela = Alerta("paralela", g.lat(50.0), g.lng(125.0), "Obra en el otro camino", radio = 12)

    @Test
    fun soloLasDeLaRuta_altaPrimero_unaVez() {
        val lineas = mutableListOf<String>()
        val a = AlertasEnRuta({ listOf(enLaRuta, paralela, enLaRutaAlta) }, ahoraMs = { 0L }, registrar = { lineas += it })
        val avisos = a.avisos(g.lat(50.0), g.lng(100.0), 20.0, ruta)
        assertEquals(
            listOf(AvisoAlerta("Ten cuidado, hay escalones.", alta = true), AvisoAlerta("Hay bancas.", alta = false)),
            avisos,
        )
        assertEquals(2, lineas.size)
        assertTrue(lineas[0], lineas[0].startsWith("Alerta anunciada (navegacion): alta a 2 m (radio 5 m, incertidumbre 20 m"))
        assertEquals(emptyList<AvisoAlerta>(), a.avisos(g.lat(51.0), g.lng(100.0), 20.0, ruta))
    }

    @Test
    fun conMasMargenTambienLaParalela() {
        val a = AlertasEnRuta({ listOf(paralela) }, ParametrosGuia(alertaRutaM = 20.0), ahoraMs = { 0L })
        assertEquals(listOf("Obra en el otro camino."), a.avisos(g.lat(50.0), g.lng(100.0), 20.0, ruta).map { it.texto })
        val t = TrazadoRuta(ruta)
        assertTrue(a.cercaDeLaRuta(paralela, t))
        assertFalse(AlertasEnRuta({ emptyList() }).cercaDeLaRuta(paralela, t))
    }
}
