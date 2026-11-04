package com.example.myapplication.ui.admin.panel

import com.example.myapplication.data.repository.ContadorCambios
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.4: el Panel vuelve a pedir `GET /v1/admin/stats` al volver a él solo si los lugares cambiaron desde la última
 * carga (aviso de FE-2.2: «Lugares registrados» quedaba viejo tras crear un lugar en 7.7). Lógica pura.
 */
class RecargaResumenTest {

    @Test
    fun contador_subeEnUnoPorAviso() {
        val c = ContadorCambios()
        assertEquals(0, c.version.value)
        c.avisar()
        c.avisar()
        assertEquals(2, c.version.value)
    }

    @Test
    fun recarga_soloSiCambiaronLosLugaresDesdeLaUltimaCarga() {
        val c = ContadorCambios()
        val cargada = c.version.value

        assertFalse(debeRecargarResumen(cargada, c.version.value, cargando = false)) // volver de 7.5 o de la Galería
        c.avisar() // se guardó un lugar en 7.7
        assertTrue(debeRecargarResumen(cargada, c.version.value, cargando = false))
        assertFalse(debeRecargarResumen(c.version.value, c.version.value, cargando = false)) // ya recargado
    }

    @Test
    fun noRecarga_conUnaCargaEnCurso_niSinContador() {
        assertFalse(debeRecargarResumen(0, 1, cargando = true))
        assertFalse(debeRecargarResumen(0, null, cargando = false))
        assertTrue(debeRecargarResumen(null, 0, cargando = false)) // nunca cargó (p. ej. error antes de empezar)
    }
}
