package com.example.myapplication.ui.admin.mapa

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.Lugar
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

const val MAX_MENSAJE = 200

data class EditorMapaUi(
    val alertas: List<Alerta> = emptyList(),
    val lugares: List<Lugar> = emptyList(),
    val pendientes: Set<String> = emptySet(),   // ids con cambios sin sincronizar
    val formulario: Alerta? = null,             // alerta en edición (borrador); null = sin formulario
    val formularioEsNuevo: Boolean = false,
    val error: String? = null,
    val sincronizando: Boolean = false,
) {
    val alertasJson: String
        get() = JSONArray().also { arr -> alertas.forEach { arr.put(it.toJson()) } }.toString()

    val lugaresJson: String
        get() = JSONArray().also { arr ->
            lugares.forEach { arr.put(JSONObject().put("nombre", it.nombre).put("lat", it.lat).put("lng", it.lng)) }
        }.toString()

    /** Lo que el mapa dibuja en vivo mientras el formulario está abierto. */
    val borradorJson: String?
        get() = formulario?.toJson()?.toString()
}

private fun Alerta.toJson() = JSONObject()
    .put("id", id).put("lat", lat).put("lng", lng).put("mensaje", mensaje)
    .put("tipo", tipo).put("prioridad", prioridad).put("radio", radio).put("activa", activa)

/**
 * Local primero: guardar/mover/eliminar se aplica de inmediato y queda como cambio pendiente.
 * TODO: reemplazar la lista en memoria por el repositorio local (Room) y `sincronizar()` por la API
 *       (`GET/POST/PUT/DELETE /admin/alerts`).
 */
class EditorMapaViewModel : ViewModel() {
    private val _ui = MutableStateFlow(
        EditorMapaUi(
            // Datos de ejemplo para probar sin backend: bórralos cuando conectes el repositorio.
            alertas = listOf(
                Alerta("demo1", 6.2004, -75.5785, "Ten cuidado, hay bancas cerca, no te vayas a estrellar", "mobiliario", "normal", 15),
                Alerta("demo2", 6.2010, -75.5777, "Rampa de acceso bloqueada por obras de mantenimiento.", "obra", "alta", 50),
            ),
            lugares = listOf(Lugar("Biblioteca", 6.2007, -75.5781)),
        )
    )
    val ui: StateFlow<EditorMapaUi> = _ui.asStateFlow()

    // ── Formulario (vista 7.9) ──
    fun abrirFormulario(id: String?, lat: Double, lng: Double) {
        _ui.update { s ->
            val existente = id?.let { i -> s.alertas.firstOrNull { it.id == i } }
            s.copy(
                formulario = existente ?: Alerta(UUID.randomUUID().toString(), lat, lng, ""),
                formularioEsNuevo = existente == null,
                error = null,
            )
        }
    }

    fun actualizarFormulario(a: Alerta) = _ui.update { it.copy(formulario = a, error = null) }

    fun cancelarFormulario() = _ui.update { it.copy(formulario = null, error = null) }

    fun guardarFormulario() {
        val a = _ui.value.formulario ?: return
        val msg = a.mensaje.trim()
        when {
            msg.isEmpty() -> { _ui.update { it.copy(error = "Escribe el mensaje que se leerá al usuario.") }; return }
            msg.length > MAX_MENSAJE -> { _ui.update { it.copy(error = "Máximo $MAX_MENSAJE caracteres.") }; return }
        }
        val limpia = a.copy(mensaje = msg)
        _ui.update { s ->
            val lista = if (s.alertas.any { it.id == limpia.id }) s.alertas.map { if (it.id == limpia.id) limpia else it }
                        else s.alertas + limpia
            s.copy(alertas = lista, pendientes = s.pendientes + limpia.id, formulario = null, error = null)
        }
    }

    // ── Acciones desde el mapa ──
    fun mover(id: String, lat: Double, lng: Double) = _ui.update { s ->
        s.copy(alertas = s.alertas.map { if (it.id == id) it.copy(lat = lat, lng = lng) else it }, pendientes = s.pendientes + id)
    }

    fun eliminar(id: String) = _ui.update { s ->
        s.copy(alertas = s.alertas.filterNot { it.id == id }, pendientes = s.pendientes + id,
               formulario = s.formulario?.takeIf { it.id != id })
    }

    fun sincronizar() {
        if (_ui.value.sincronizando || _ui.value.pendientes.isEmpty()) return
        viewModelScope.launch {
            _ui.update { it.copy(sincronizando = true) }
            delay(600)   // TODO: enviar al backend; si falla, dejar `pendientes` intacto
            _ui.update { it.copy(pendientes = emptySet(), sincronizando = false) }
        }
    }
}