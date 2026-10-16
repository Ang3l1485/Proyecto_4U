package com.example.myapplication.ui.admin.mapa

import android.webkit.JavascriptInterface
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import org.json.JSONObject

/** Eventos que el mapa web (editor_mapa.js) envía a la app. */
interface EditorMapaEventos {
    fun abrirFormulario(id: String?, lat: Double, lng: Double)
    fun cancelarFormulario()
    fun moverAlerta(id: String, lat: Double, lng: Double)
    fun eliminarAlerta(id: String)
    fun sincronizar()
    fun verLista()
    fun pedirMiPosicion()
    fun salir()
}

/** Vista 7.8 — Editor de mapa y alertas. Es la que se usa en el NavHost. */
@Composable
fun EditorMapaScreen(
    onVolver: () -> Unit,
    onVerLista: () -> Unit,
    posicionAdmin: () -> Pair<Double, Double>?,
    modifier: Modifier = Modifier.fillMaxSize(),
    vm: EditorMapaViewModel = viewModel(),
) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    var miPos by remember { mutableStateOf<Pair<Double, Double>?>(null) }

    EditorMapaContent(
        alertasJson = ui.alertasJson,
        lugaresJson = ui.lugaresJson,
        pendientes = ui.pendientes.size,
        borradorJson = ui.borradorJson,
        miPosicion = miPos,
        modifier = modifier,
        eventos = object : EditorMapaEventos {
            override fun abrirFormulario(id: String?, lat: Double, lng: Double) = vm.abrirFormulario(id, lat, lng)
            override fun cancelarFormulario() = vm.cancelarFormulario()
            override fun moverAlerta(id: String, lat: Double, lng: Double) = vm.mover(id, lat, lng)
            override fun eliminarAlerta(id: String) = vm.eliminar(id)
            override fun sincronizar() = vm.sincronizar()
            override fun verLista() = onVerLista()
            override fun pedirMiPosicion() { miPos = posicionAdmin() }
            override fun salir() = onVolver()
        },
    )

    ui.formulario?.let { alerta ->
        AlertaFormSheet(
            alerta = alerta,
            esNueva = ui.formularioEsNuevo,
            error = ui.error,
            onCambio = vm::actualizarFormulario,
            onGuardar = vm::guardarFormulario,
            onCancelar = vm::cancelarFormulario,
            onEliminar = { vm.eliminar(alerta.id); vm.cancelarFormulario() },
        )
    }
}

/**
 * Solo dibuja el WebView (`assets/editor_mapa.html`: Leaflet + OpenStreetMap en línea) con el [MapaWebView] común.
 * Recibe todo como JSON; no conoce el ViewModel.
 */
@Composable
fun EditorMapaContent(
    alertasJson: String,
    lugaresJson: String,
    pendientes: Int,
    borradorJson: String?,
    eventos: EditorMapaEventos,
    modifier: Modifier = Modifier.fillMaxSize(),
    miPosicion: Pair<Double, Double>? = null,
) {
    val mapa = rememberMapaWeb()
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { EditorPuente(mapa) { eventosActuales } }

    // El JS sale de los modos temporales (mover, colocar, formulario) y al final llama a salir().
    MapaWebView(mapa, html = "editor_mapa.html", puente = puente, nombrePuente = "EditorBridge", tag = "EditorMapa", modifier = modifier)

    // Empuja el estado al mapa cuando la página avisa que está lista y cada vez que cambia.
    LaunchedEffect(mapa.listo, alertasJson) { if (mapa.listo) mapa.js("cargarAlertas(${literalJs(alertasJson)})") }
    LaunchedEffect(mapa.listo, lugaresJson) { if (mapa.listo) mapa.js("cargarLugares(${literalJs(lugaresJson)})") }
    LaunchedEffect(mapa.listo, pendientes) { if (mapa.listo) mapa.js("setPendientes($pendientes)") }
    LaunchedEffect(mapa.listo, borradorJson) { if (mapa.listo) mapa.js("setBorrador(${borradorJson?.let(::literalJs) ?: "null"})") }
    LaunchedEffect(mapa.listo, miPosicion) { if (mapa.listo && miPosicion != null) mapa.js("setMiPosicion(${miPosicion.first}, ${miPosicion.second})") }
}

/** Puente `EditorBridge` (web → app). `listo()` viene de [PuenteWeb]. Debe ser `internal` o público: el WebView lo invoca por reflexión. */
internal class EditorPuente(mapa: MapaWeb, private val eventos: () -> EditorMapaEventos) : PuenteWeb(mapa) {
    @JavascriptInterface
    fun abrirFormulario(json: String) {
        enHiloPrincipal {
            val o = JSONObject(json)
            val id = if (o.isNull("id")) null else o.getString("id")
            eventos().abrirFormulario(id, o.getDouble("lat"), o.getDouble("lng"))
        }
    }
    @JavascriptInterface fun cancelarFormulario() { enHiloPrincipal { eventos().cancelarFormulario() } }
    @JavascriptInterface fun moverAlerta(id: String, lat: Double, lng: Double) { enHiloPrincipal { eventos().moverAlerta(id, lat, lng) } }
    @JavascriptInterface fun eliminarAlerta(id: String) { enHiloPrincipal { eventos().eliminarAlerta(id) } }
    @JavascriptInterface fun sincronizar() { enHiloPrincipal { eventos().sincronizar() } }
    @JavascriptInterface fun verLista() { enHiloPrincipal { eventos().verLista() } }
    @JavascriptInterface fun pedirMiPosicion() { enHiloPrincipal { eventos().pedirMiPosicion() } }
    @JavascriptInterface fun salir() { enHiloPrincipal { eventos().salir() } }
}