package com.example.myapplication.usuarios

import com.example.myapplication.data.repository.AuthRepositoryStub
import com.example.myapplication.data.repository.UsuariosRepositoryEnMemoria
import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.usecase.PoliticaAcceso
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * HU-017 — Acceso al panel por rol. LoginViewModel y PanelAdminViewModel deciden con
 * PoliticaAcceso.puedeEntrarAlPanel, así que la regla se prueba aquí sin Android.
 */
class AccesoPanelTest {

    private lateinit var auth: AuthRepositoryStub

    @Before
    fun preparar() {
        auth = AuthRepositoryStub(UsuariosRepositoryEnMemoria(), retardoMs = 0)
    }

    @Test
    fun T13_loginInvestigador_esExitosoYEntraAlPanel() = runBlocking {
        // Given la cuenta activa investigador@campus.edu.co
        // When inicia sesión
        val sesion = auth.login("investigador@campus.edu.co", "clave")

        // Then obtiene el rol INVESTIGADOR y el panel se habilita
        assertEquals(Rol.INVESTIGADOR, sesion.usuario.rol)
        assertTrue(PoliticaAcceso.puedeEntrarAlPanel(sesion.usuario.rol))
    }

    @Test
    fun T14_investigador_sinAccesoARecoleccionNiUsuarios() {
        // Given el rol INVESTIGADOR
        val rol = Rol.INVESTIGADOR

        // When se calculan los módulos visibles en el panel
        val visibles = Modulo.entries.filter { PoliticaAcceso.puedeAcceder(rol, it) }.toSet()

        // Then RECOLECCION y USUARIOS quedan denegados; solo ve IMAGENES y VIDEOS
        assertFalse(PoliticaAcceso.puedeAcceder(rol, Modulo.RECOLECCION))
        assertFalse(PoliticaAcceso.puedeAcceder(rol, Modulo.USUARIOS))
        assertEquals(setOf(Modulo.IMAGENES, Modulo.VIDEOS), visibles)
    }

    @Test
    fun T15_loginUser_esRechazadoDelPanel() = runBlocking {
        // Given la cuenta activa user@campus.edu.co
        // When inicia sesión
        val sesion = auth.login("user@campus.edu.co", "clave")

        // Then las credenciales son válidas pero el panel no se habilita ("Sin permisos")
        assertEquals(Rol.USER, sesion.usuario.rol)
        assertFalse(PoliticaAcceso.puedeEntrarAlPanel(sesion.usuario.rol))
    }
}
