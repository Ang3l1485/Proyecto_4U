package com.example.myapplication.ui.admin.lugares.componentes

import android.webkit.JavascriptInterface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import org.json.JSONArray
import org.json.JSONObject

/**
 * Mapa de lugares (FE-3.4). Página: `assets/lugar_mapa.html` (+ `.js`), puente `LugarBridge` (ARCHITECTURE §5.9).
 * Dos modos: **editable** (formulario 7.7: tocar o arrastrar el alfiler cambia el punto de llegada) y **ver** (lista 7.6
 * en modo mapa: tocar un lugar lo abre). Embebido en una tarjeta de Compose (`pasarInsets = false`,
 * `manejarAtras = false`), como `RecoleccionMapaContent`. No conoce el ViewModel.
 */
data class LugarMapaEventos(
    /** Modo editable: el admin tocó el mapa o soltó el alfiler (coordenada sin redondear). */
    val onPunto: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    /** Modo ver: el admin tocó un lugar. */
    val onLugarTocado: (id: String) -> Unit = {},
)

/** Puente `LugarBridge`, web → app. `internal`, nunca `private` (el WebView la invoca por reflexión). */
internal class LugarPuente(
    mapa: MapaWeb,
    private val eventos: () -> LugarMapaEventos,
) : PuenteWeb(mapa) {
    @JavascriptInterface
    fun puntoCambiado(lat: Double, lng: Double) = enHiloPrincipal { eventos().onPunto(lat, lng) }

    @JavascriptInterface
    fun lugarTocado(id: String) = enHiloPrincipal { eventos().onLugarTocado(id) }
}

/** `[{id, nombre, lat, lng}]` para `cargarLugares` (con `org.json`, como el editor de mapa). */
fun lugaresJson(lugares: List<LugarDestino>): String {
    val arr = JSONArray()
    lugares.forEach { arr.put(JSONObject().put("id", it.id).put("nombre", it.nombre).put("lat", it.lat).put("lng", it.lng)) }
    return arr.toString()
}

/**
 * @param lugaresJson `[{id, nombre, lat, lng}]` ([lugaresJson]): en 7.7, los demás lugares; en 7.6, todos.
 * @param punto punto de llegada del lugar que se edita (`null` = sin elegir); solo en modo editable.
 * @param editable `true` en 7.7, `false` en 7.6.
 */
@Composable
fun LugarMapaContent(
    lugaresJson: String,
    punto: Pair<Double, Double>?,
    editable: Boolean,
    eventos: LugarMapaEventos,
    modifier: Modifier = Modifier,
) {
    val mapa = rememberMapaWeb()
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { LugarPuente(mapa) { eventosActuales } }

    MapaWebView(
        mapa = mapa,
        html = "lugar_mapa.html",
        puente = puente,
        nombrePuente = "LugarBridge",
        tag = "LugarMapa",
        modifier = modifier,
        pasarInsets = false,
        manejarAtras = false,
    )

    LaunchedEffect(mapa.listo, editable) {
        if (mapa.listo) mapa.js("setModo($editable)")
    }
    // El punto antes que los lugares: el primer encuadre usa el punto si lo hay.
    LaunchedEffect(mapa.listo, punto) {
        if (!mapa.listo) return@LaunchedEffect
        if (punto == null) mapa.js("quitarPunto()") else mapa.js("setPunto(${punto.first}, ${punto.second})")
    }
    LaunchedEffect(mapa.listo, lugaresJson) {
        if (mapa.listo) mapa.js("cargarLugares(${literalJs(lugaresJson)})")
    }
}
