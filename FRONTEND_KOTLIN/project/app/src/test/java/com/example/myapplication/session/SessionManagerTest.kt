package com.example.myapplication.session

import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `SessionManager` con un almacén en memoria (como `SesionVencidaTest`): sesión vigente, rol y cierre. Los casos de
 * sesión vencida contra el backend están en `SesionVencidaTest`.
 */
class SessionManagerTest {

    private class AlmacenPrueba : AlmacenSesion {
        var sesion: Sesion? = null
        var borrados = 0
        override fun leer(): Sesion? = sesion
        override fun escribir(sesion: Sesion) { this.sesion = sesion }
        override fun borrar() { sesion = null; borrados++ }
    }

    private val almacen = AlmacenPrueba()
    private var ahora = 1_800_000_000_000L
    private val session = SessionManager(almacen, reloj = { ahora })

    private fun sesion(rol: Rol = Rol.ADMIN, expiraEnMs: Long = ahora + HORA) = Sesion(
        token = "token-1",
        usuario = Usuario("u1", "Admin", "admin@campus.edu.co", rol),
        expiraEnMs = expiraEnMs,
    )

    @Test
    fun sesionVigente_obtener_laDevuelveSinBorrarla() {
        val guardada = sesion()
        session.guardar(guardada)

        assertEquals(guardada, session.obtener())
        assertEquals(0, almacen.borrados)
    }

    @Test
    fun sesionVigenteDeAdmin_esAdmin_esTrue() {
        session.guardar(sesion(rol = Rol.ADMIN))

        assertTrue(session.esAdmin())
    }

    @Test
    fun sesionVigenteDeUser_esAdmin_esFalse() {
        session.guardar(sesion(rol = Rol.USER))

        assertFalse(session.esAdmin())
    }

    @Test
    fun sinSesionGuardada_obtenerYEsAdmin_sonNullYFalse() {
        assertNull(session.obtener())
        assertFalse(session.esAdmin())
        assertEquals(0, almacen.borrados)
    }

    @Test
    fun sesionQueVenceDespues_alPasarLaHora_obtenerLaBorra() {
        session.guardar(sesion(expiraEnMs = ahora + HORA))
        assertTrue(session.obtener() != null)

        ahora += HORA

        assertNull(session.obtener())
        assertNull(almacen.sesion)
        assertEquals(1, almacen.borrados)
    }

    @Test
    fun sesionVigente_cerrarSesion_laBorra() {
        session.guardar(sesion())

        session.cerrarSesion()

        assertNull(session.obtener())
        assertEquals(1, almacen.borrados)
    }

    private companion object {
        const val HORA = 3_600_000L
    }
}
