package com.example.myapplication.ui.admin.recoleccion.componentes

import android.webkit.JavascriptInterface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import kotlin.math.roundToInt

/**
 * Mapa en vivo de la recolección (ARCHITECTURE 7.4). Página: `assets/recoleccion_mapa.html` (+ `.js`).
 * Reutiliza `MapaWebView`, `PuenteWeb`, `rememberMapaWeb` y `literalJs` (11.9). Igual que `EditorMapaContent`:
 * no conoce el ViewModel, solo recibe datos y entrega eventos.
 */

/** Lo que el mapa le avisa a la pantalla (`{}` por defecto, como `UbicacionManualAcciones`). */
data class RecoleccionMapaEventos(
    /** El admin movió el alfiler de re-anclaje (arrastre ~10/s o toque). → `viewModel.alMoverReanclaje`. */
    val onPuntoReanclaje: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    /** `false` si el admin arrastró el mapa (dejó de seguirlo); `true` tras «Centrar». Para resaltar el botón. */
    val onSeguimiento: (activo: Boolean) -> Unit = {},
)

/** Puente `RecoleccionBridge`, web → app. `internal`, nunca `private` (el WebView la invoca por reflexión). */
internal class RecoleccionPuente(
    mapa: MapaWeb,
    private val eventos: () -> RecoleccionMapaEventos,
) : PuenteWeb(mapa) {
    @JavascriptInterface
    fun puntoCambiado(lat: Double, lng: Double) = enHiloPrincipal { eventos().onPuntoReanclaje(lat, lng) }

    @JavascriptInterface
    fun seguimientoCambiado(activo: Boolean) = enHiloPrincipal { eventos().onSeguimiento(activo) }
}

/** Controles que dibuja Compose (Centrar, +, −) y llaman al JS. Se crea en la pantalla y se pasa al mapa. */
@Stable
class RecoleccionMapaControl internal constructor(internal val mapa: MapaWeb) {
    fun centrar() { if (mapa.listo) mapa.js("centrar()") }
    fun zoomMas() { if (mapa.listo) mapa.js("zoomMas()") }
    fun zoomMenos() { if (mapa.listo) mapa.js("zoomMenos()") }
}

@Composable
fun rememberRecoleccionMapaControl(): RecoleccionMapaControl {
    val mapa = rememberMapaWeb()
    return remember(mapa) { RecoleccionMapaControl(mapa) }
}

/**
 * @param lat lng posición actual del PDR (`ui.lat` / `ui.lng`); `null` hasta el primer fix.
 * @param rumbo 0…360 (`ui.rumbo`; si es `Double`, pasar `.toFloat()`).
 * @param fotosJson trayectoriaJson alertasJson los tres JSON ya armados por el ViewModel (11.6, 6b).
 * @param reanclaje `(lat, lng)` del alfiler mientras `ui.reanclaje != null`; `null` = modo cerrado.
 */
@Composable
fun RecoleccionMapaContent(
    control: RecoleccionMapaControl,
    lat: Double?,
    lng: Double?,
    rumbo: Float,
    fotosJson: String,
    trayectoriaJson: String,
    alertasJson: String,
    reanclaje: Pair<Double, Double>?,
    eventos: RecoleccionMapaEventos,
    modifier: Modifier = Modifier,
) {
    val mapa = control.mapa
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { RecoleccionPuente(mapa) { eventosActuales } }

    MapaWebView(
        mapa = mapa,
        html = "recoleccion_mapa.html",
        puente = puente,
        nombrePuente = "RecoleccionBridge",
        tag = "RecoleccionMapa",
        modifier = modifier,
        pasarInsets = false,    // es una tarjeta dentro de Compose, no pantalla completa
        manejarAtras = false,   // Atrás lo maneja la pantalla: BackHandler → alPedirFinalizar()
    )

    // Rumbo redondeado al grado: el sensor emite mucho más rápido de lo que se nota.
    val rumboGrados = rumbo.roundToInt()
    LaunchedEffect(mapa.listo, lat, lng, rumboGrados) {
        if (mapa.listo && lat != null && lng != null && lat.isFinite() && lng.isFinite()) {
            mapa.js("setPosicion($lat, $lng, $rumboGrados)")
        }
    }
    LaunchedEffect(mapa.listo, fotosJson) {
        if (mapa.listo) mapa.js("cargarFotos(${literalJs(fotosJson)})")
    }
    LaunchedEffect(mapa.listo, trayectoriaJson) {
        if (mapa.listo) mapa.js("cargarTrayectoria(${literalJs(trayectoriaJson)})")
    }
    LaunchedEffect(mapa.listo, alertasJson) {
        if (mapa.listo) mapa.js("cargarAlertas(${literalJs(alertasJson)})")
    }
    LaunchedEffect(mapa.listo, reanclaje) {
        if (!mapa.listo) return@LaunchedEffect
        if (reanclaje == null) mapa.js("quitarReanclaje()")
        else mapa.js("setReanclaje(${reanclaje.first}, ${reanclaje.second})")
    }
}