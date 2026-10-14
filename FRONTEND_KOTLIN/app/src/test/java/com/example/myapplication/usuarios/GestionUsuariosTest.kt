package com.example.myapplication.usuarios

import com.example.myapplication.data.repository.AuthRepositoryStub
import com.example.myapplication.data.repository.CuentaDesactivadaException
import com.example.myapplication.data.repository.UsuariosRepositoryEnMemoria
import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.domain.usecase.AutoDesactivacionException
import com.example.myapplication.domain.usecase.GestionUsuarios
import com.example.myapplication.domain.usecase.PoliticaAcceso
import com.example.myapplication.domain.usecase.UltimoAdministradorException
import com.example.myapplication.domain.usecase.UsuarioNoEncontradoException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** HU-017 — Gestión de usuarios: un test por escenario de aceptación. */
class GestionUsuariosTest {

    private val admin = Usuario("1", "Administrador", "admin@campus.edu.co", Rol.ADMIN)
    private val investigador = Usuario("2", "Investigador", "investigador@campus.edu.co", Rol.INVESTIGADOR)
    private val usuario = Usuario("3", "Usuario", "user@campus.edu.co", Rol.USER)

    private lateinit var repo: UsuariosRepositoryEnMemoria
    private lateinit var gestion: GestionUsuarios
    private lateinit var auth: AuthRepositoryStub

    @Before
    fun preparar() {
        repo = UsuariosRepositoryEnMemoria(listOf(admin, investigador, usuario))
        gestion = GestionUsuarios(repo)
        auth = AuthRepositoryStub(repo, retardoMs = 0)
    }

    // ── Listar ──

    @Test
    fun T1_listarUsuarios_devuelveUsuariosConRolYEstado() = runBlocking {
        // Given un repositorio con tres usuarios, uno de ellos desactivado
        repo.guardar(usuario.copy(activo = false))

        // When el admin lista los usuarios
        val lista = gestion.listar()

        // Then se obtienen todos con su rol y estado
        assertEquals(3, lista.size)
        assertEquals(Rol.ADMIN, lista.first { it.id == "1" }.rol)
        assertEquals(Rol.INVESTIGADOR, lista.first { it.id == "2" }.rol)
        assertTrue(lista.first { it.id == "1" }.activo)
        assertFalse(lista.first { it.id == "3" }.activo)
    }

    @Test
    fun T2_repositorioVacio_devuelveListaVacia() = runBlocking {
        // Given un repositorio sin usuarios
        val vacio = GestionUsuarios(UsuariosRepositoryEnMemoria(emptyList()))

        // When se listan los usuarios
        val lista = vacio.listar()

        // Then la lista está vacía
        assertTrue(lista.isEmpty())
    }

    // ── Cambiar rol ──

    @Test
    fun T3_cambiarUserAInvestigador_otorgaAccesoAImagenes() = runBlocking {
        // Given un usuario con rol USER sin acceso a IMAGENES
        assertFalse(PoliticaAcceso.puedeAcceder(usuario.rol, Modulo.IMAGENES))

        // When el admin le asigna el rol INVESTIGADOR
        val actualizado = gestion.cambiarRol(usuario.id, Rol.INVESTIGADOR)

        // Then queda como INVESTIGADOR y puede acceder a IMAGENES
        assertEquals(Rol.INVESTIGADOR, repo.obtener(usuario.id)?.rol)
        assertTrue(PoliticaAcceso.puedeAcceder(actualizado.rol, Modulo.IMAGENES))
    }

    @Test
    fun T4_degradarUltimoAdminActivo_esRechazadoYRolSinCambios() = runBlocking {
        // Given un único ADMIN activo
        var rechazado = false

        // When se intenta cambiarlo a USER
        try {
            gestion.cambiarRol(admin.id, Rol.USER)
        } catch (e: UltimoAdministradorException) {
            rechazado = true
        }

        // Then la acción es rechazada y conserva el rol ADMIN
        assertTrue(rechazado)
        assertEquals(Rol.ADMIN, repo.obtener(admin.id)?.rol)
    }

    // ── Activar / desactivar ──

    @Test
    fun T5_usuarioDesactivado_noPuedeIniciarSesion() = runBlocking {
        // Given un usuario desactivado por el admin
        gestion.desactivar(usuario.id, idSolicitante = admin.id)
        var rechazado = false

        // When intenta iniciar sesión
        try {
            auth.login(usuario.correo, "clave")
        } catch (e: CuentaDesactivadaException) {
            rechazado = true
        }

        // Then el login falla con CuentaDesactivadaException
        assertTrue(rechazado)
    }

    @Test
    fun T6_adminDesactivandoseASiMismo_esRechazado() = runBlocking {
        // Given un admin activo con otro admin en el sistema
        repo.guardar(Usuario("4", "Otro admin", "otro@campus.edu.co", Rol.ADMIN))
        var rechazado = false

        // When intenta desactivar su propia cuenta
        try {
            gestion.desactivar(admin.id, idSolicitante = admin.id)
        } catch (e: AutoDesactivacionException) {
            rechazado = true
        }

        // Then la acción es rechazada y sigue activo
        assertTrue(rechazado)
        assertTrue(repo.obtener(admin.id)!!.activo)
    }

    @Test
    fun T7_usuarioReactivado_puedeIniciarSesionDeNuevo() = runBlocking {
        // Given un usuario desactivado
        gestion.desactivar(usuario.id, idSolicitante = admin.id)

        // When el admin lo reactiva e intenta iniciar sesión
        gestion.activar(usuario.id)
        val sesion = auth.login(usuario.correo, "clave")

        // Then el login es exitoso
        assertEquals(usuario.id, sesion.usuario.id)
        assertTrue(sesion.usuario.activo)
    }

    @Test
    fun T8_activarUsuarioYaActivo_noCambiaNada() = runBlocking {
        // Given un usuario activo
        val antes = repo.listar()

        // When el admin lo activa de nuevo
        val resultado = gestion.activar(usuario.id)

        // Then el usuario y el repositorio quedan iguales
        assertEquals(usuario, resultado)
        assertEquals(antes, repo.listar())
    }

    // ── Control de acceso ──

    @Test
    fun T9_admin_puedeAccederAUsuarios() {
        // Given el rol ADMIN
        val rol = Rol.ADMIN

        // When se consulta el acceso al módulo USUARIOS
        val permitido = PoliticaAcceso.puedeAcceder(rol, Modulo.USUARIOS)

        // Then el acceso es permitido
        assertTrue(permitido)
    }

    @Test
    fun T10_investigadorSinAccesoAUsuarios_yUserSinNingunModulo() {
        // Given los roles INVESTIGADOR y USER

        // When se consulta el acceso a los módulos de administración
        val investigadorUsuarios = PoliticaAcceso.puedeAcceder(Rol.INVESTIGADOR, Modulo.USUARIOS)
        val userAlguno = Modulo.entries.any { PoliticaAcceso.puedeAcceder(Rol.USER, it) }

        // Then INVESTIGADOR no accede a USUARIOS y USER no accede a ninguno
        assertFalse(investigadorUsuarios)
        assertFalse(userAlguno)
    }

    @Test
    fun T11_trasCambioDeRol_siguienteLoginDevuelveNuevoRol() = runBlocking {
        // Given un usuario con rol USER
        // When el admin lo cambia a INVESTIGADOR y el usuario inicia sesión
        gestion.cambiarRol(usuario.id, Rol.INVESTIGADOR)
        val sesion = auth.login(usuario.correo, "clave")

        // Then la sesión trae el nuevo rol
        assertEquals(Rol.INVESTIGADOR, sesion.usuario.rol)
    }

    @Test
    fun T12_cambiarRolDeIdDesconocido_lanzaUsuarioNoEncontrado() = runBlocking {
        // Given un id que no existe
        var lanzada = false

        // When se intenta cambiar su rol
        try {
            gestion.cambiarRol("999", Rol.ADMIN)
        } catch (e: UsuarioNoEncontradoException) {
            lanzada = true
        }

        // Then se lanza UsuarioNoEncontradoException
        assertTrue(lanzada)
    }
}
