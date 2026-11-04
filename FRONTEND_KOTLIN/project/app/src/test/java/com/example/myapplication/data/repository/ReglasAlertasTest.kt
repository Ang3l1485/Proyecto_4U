package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.OperacionAlerta
import com.example.myapplication.domain.model.OperacionAlerta.Eliminar
import com.example.myapplication.domain.model.OperacionAlerta.Upsert
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reglas puras de los pendientes de alertas (FE-3.3; apoyo de C1 y C2): una operación por id, la última (backend §4.11,
 * «Para la app»), y cómo se aplica la respuesta de `sincronizar`.
 */
class ReglasAlertasTest {

    private fun alerta(id: String, mensaje: String = "m-$id", activa: Boolean = true) =
        Alerta(id, 6.2, -75.57, mensaje, activa = activa)

    private fun EstadoAlertas.con(vararg ops: OperacionAlerta) = ops.fold(this) { e, op -> ReglasAlertas.registrar(e, op) }

    @Test
    fun crearYEditar_dejaUnSoloUpsertConLaUltimaVersion() {
        val e = EstadoAlertas().con(Upsert(alerta("a", "uno")), Upsert(alerta("a", "dos")))
        assertEquals(listOf<OperacionAlerta>(Upsert(alerta("a", "dos"))), e.pendientes)
        assertEquals(listOf(alerta("a", "dos")), e.visibles)
    }

    @Test
    fun crearYBorrarAntesDeSincronizar_dejaSoloEliminar_yNoSeVe() {
        // C2: con un id que el servidor no conoce, `eliminar` es `ok` y no deja rastro (backend §4.11).
        val e = EstadoAlertas().con(Upsert(alerta("a")), Eliminar("a"))
        assertEquals(listOf<OperacionAlerta>(Eliminar("a")), e.pendientes)
        assertTrue(e.visibles.isEmpty())
        assertEquals(setOf("a"), e.idsPendientes)
    }

    @Test
    fun registrar_mueveElIdAlFinal_yLimpiaLaMarcaDeRechazada() {
        val e = EstadoAlertas(rechazadas = setOf("a")).con(Upsert(alerta("a")), Upsert(alerta("b")), Upsert(alerta("a", "otra")))
        assertEquals(listOf("b", "a"), e.pendientes.map { it.id })
        assertTrue(e.rechazadas.isEmpty())
    }

    @Test
    fun aplicar_reemplazaPorIdEnSuSitio_anadeLasNuevas_yQuitaLasEliminadas() {
        val servidor = listOf(alerta("a"), alerta("b"), alerta("c"))
        val visibles = ReglasAlertas.aplicar(servidor, listOf(Upsert(alerta("b", "nuevo")), Eliminar("c"), Upsert(alerta("d"))))
        assertEquals(listOf(alerta("a"), alerta("b", "nuevo"), alerta("d")), visibles)
    }

    @Test
    fun confirmar_okPasaAlServidorYSaleDePendientes() {
        val e = EstadoAlertas(servidor = listOf(alerta("x"))).con(Upsert(alerta("a")), Eliminar("x"))
        val r = ReglasAlertas.confirmar(e, e.pendientes, ok = setOf("a", "x"), rechazados = emptySet())
        assertTrue(r.pendientes.isEmpty())
        assertEquals(listOf(alerta("a")), r.servidor)
        assertEquals(r.servidor, r.visibles)
    }

    @Test
    fun confirmar_unCambioHechoDuranteElEnvioSigueEnPendientes() {
        val e = EstadoAlertas().con(Upsert(alerta("a", "enviado")))
        val enviados = e.pendientes
        val durante = ReglasAlertas.registrar(e, Upsert(alerta("a", "nuevo")))
        val r = ReglasAlertas.confirmar(durante, enviados, ok = setOf("a"), rechazados = emptySet())
        assertEquals(listOf<OperacionAlerta>(Upsert(alerta("a", "nuevo"))), r.pendientes)
        assertEquals(listOf(alerta("a", "enviado")), r.servidor)
        assertEquals(listOf(alerta("a", "nuevo")), r.visibles)
    }

    @Test
    fun confirmar_rechazadoQuedaPendienteYMarcado_eIgnoraIdsQueNoSeEnviaron() {
        val e = EstadoAlertas().con(Upsert(alerta("a")), Upsert(alerta("b")))
        val r = ReglasAlertas.confirmar(e, e.pendientes, ok = setOf("b", "z"), rechazados = setOf("a"))
        assertEquals(listOf("a"), r.pendientes.map { it.id })
        assertEquals(setOf("a"), r.rechazadas)
        assertEquals(listOf(alerta("b")), r.servidor)
    }

    @Test
    fun fusionarPublicas_reemplazaLasActivas_conservaLasInactivasQueNoVienen() {
        val servidor = listOf(alerta("a", "viejo"), alerta("b"), alerta("i", activa = false))
        val publicas = listOf(alerta("a", "nuevo"), alerta("c"))
        // `b` (activa) ya no viene: se borró o se desactivó en el servidor → sale; `i` (inactiva) no la trae la pública.
        assertEquals(
            listOf(alerta("a", "nuevo"), alerta("c"), alerta("i", activa = false)),
            ReglasAlertas.fusionarPublicas(servidor, publicas),
        )
    }
}
