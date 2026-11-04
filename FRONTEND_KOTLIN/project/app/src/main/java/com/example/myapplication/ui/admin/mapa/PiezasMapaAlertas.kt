package com.example.myapplication.ui.admin.mapa

import com.example.myapplication.domain.model.Alerta
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject

/**
 * Una alerta en el JSON de los mapas web (`editor_mapa.js` y `recoleccion_mapa.js`): `id, lat, lng, mensaje, tipo,
 * prioridad, radio, activa` (FE-3.3: antes cada ViewModel tenía su copia privada). `org.json`: solo en Android.
 */
fun Alerta.jsonMapa(): JSONObject = JSONObject()
    .put("id", id).put("lat", lat).put("lng", lng).put("mensaje", mensaje)
    .put("tipo", tipo).put("prioridad", prioridad).put("radio", radio).put("activa", activa)

/** Lista de alertas para `cargarAlertas(texto)` de los mapas web. */
fun alertasJson(alertas: List<Alerta>): String =
    JSONArray().also { arr -> alertas.forEach { arr.put(it.jsonMapa()) } }.toString()

/** Lo que la lista 7.10 le pide al editor 7.8 al volver a él (FE-3.3). */
sealed interface PedidoEditor {
    /** Seleccionar y centrar esa alerta («Ver en el mapa»). */
    data class VerAlerta(val id: String) : PedidoEditor

    /** Entrar en el modo colocar («Nueva alerta» de la lista). */
    data object NuevaAlerta : PedidoEditor
}

/**
 * Pedidos de 7.10 a 7.8 (FE-3.3). 7.10 se abre encima de 7.8 y vuelve con `popBackStack()`: deja aquí el pedido y la
 * pantalla del editor lo atiende cuando su mapa está listo (y lo borra con [atendido]). Solo memoria.
 */
object PedidosEditorMapa {
    private val _pedido = MutableStateFlow<PedidoEditor?>(null)
    val pedido: StateFlow<PedidoEditor?> = _pedido.asStateFlow()

    fun pedir(p: PedidoEditor) {
        _pedido.value = p
    }

    fun atendido(p: PedidoEditor) {
        _pedido.compareAndSet(p, null)
    }
}
