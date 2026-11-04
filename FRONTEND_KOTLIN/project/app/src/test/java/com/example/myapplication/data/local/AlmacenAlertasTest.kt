package com.example.myapplication.data.local

import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.data.remote.RemoteAlertasRepository
import com.example.myapplication.data.repository.EstadoAlertas
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * `AlmacenAlertasArchivo` (FE-3.3; apoyo de C1: una alerta creada en 7.4 sobrevive a salir de la vista y a matar el
 * proceso). Se prueba con una carpeta temporal, como `AlmacenRecorridosTest`.
 */
class AlmacenAlertasTest {

    @get:Rule
    val carpeta = TemporaryFolder()

    private fun archivo() = File(carpeta.root, "alertas/editor.json")

    /** Un cliente que nunca se usa: guardar y cargar no llaman al backend. */
    private val sinApi = ClienteApi.crear(urlBase = "http://127.0.0.1:9/v1", registrar = {})

    @Test
    fun guardarYLeer_conservaServidorPendientesYRechazadas() = runBlocking {
        val completa = Alerta("a", 6.200512, -75.578311, "Ten cuidado, «bancas»", "mobiliario", "alta", 35, false, 1L, 2L, 3, 4L)
        val estado = EstadoAlertas(
            servidor = listOf(completa, Alerta("b", 6.2, -75.5, "b")),
            pendientes = listOf(OperacionAlerta.Upsert(Alerta("c", 6.1, -75.4, "c")), OperacionAlerta.Eliminar("b")),
            rechazadas = setOf("c"),
            cargado = true,
        )
        AlmacenAlertasArchivo(archivo()).guardar(estado)

        assertEquals(estado, AlmacenAlertasArchivo(archivo()).leer())
        assertTrue(File(carpeta.root, "alertas").list()!!.none { it.endsWith(".tmp") })
    }

    @Test
    fun sinArchivo_estaVacio_yUnoDanadoSeAparta() = runBlocking {
        assertEquals(EstadoAlertas(cargado = true), AlmacenAlertasArchivo(archivo()).leer())

        archivo().parentFile!!.mkdirs()
        archivo().writeText("{\"servidor\": [ {\"id\": ")
        val registros = mutableListOf<String>()
        assertEquals(EstadoAlertas(cargado = true), AlmacenAlertasArchivo(archivo(), registrar = { registros += it }).leer())
        assertTrue(File(carpeta.root, "alertas/editor.json.danado").exists())
        assertEquals(1, registros.size)
    }

    @Test
    fun loCreadoSeVeEnUnRepositorioNuevo_comoTrasMatarElProceso() = runBlocking {
        val primero = RemoteAlertasRepository(AlmacenAlertasArchivo(archivo()), api = sinApi, registrar = {})
        primero.guardar(Alerta("a", 6.2, -75.57, "validacion-3-3-c1"))

        val segundo = RemoteAlertasRepository(AlmacenAlertasArchivo(archivo()), api = sinApi, registrar = {})
        segundo.cargar()

        assertEquals(listOf("validacion-3-3-c1"), segundo.estado.value.visibles.map { it.mensaje })
        assertEquals(setOf("a"), segundo.estado.value.idsPendientes)
    }
}
