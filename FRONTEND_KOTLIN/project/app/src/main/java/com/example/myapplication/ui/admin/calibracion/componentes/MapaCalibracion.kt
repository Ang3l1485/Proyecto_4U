package com.example.myapplication.ui.admin.calibracion.componentes

import android.webkit.JavascriptInterface
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalInspectionMode
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import com.example.myapplication.ui.admin.calibracion.ExtremoTramo
import com.example.myapplication.ui.admin.calibracion.PuntoTramo
import org.json.JSONObject

/** Encuadre inicial (EAFIT, aproximado). TODO: reemplazar por `CampusMapa.CENTRO` (7.3). */
private const val CENTRO_LAT = 6.2006
private const val CENTRO_LNG = -75.5783
private const val ZOOM_INICIAL = 18

/** Lo que el mapa le cuenta a la pantalla. Todo llega en el hilo principal. */
internal data class CalibracionMapaEventos(
    val onToque: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    val onPuntoMovido: (ExtremoTramo, lat: Double, lng: Double) -> Unit = { _, _, _ -> },
)

/**
 * Puente `CalibracionBridge` (web → app). Debe ser pública o `internal`, nunca `private`:
 * el `WebView` la invoca por reflexión (11.9).
 */
internal class CalibracionPuente(
    mapa: MapaWeb,
    private val eventos: () -> CalibracionMapaEventos,
) : PuenteWeb(mapa) {

    @JavascriptInterface
    fun toque(lat: Double, lng: Double) {
        enHiloPrincipal { eventos().onToque(lat, lng) }
    }

    @JavascriptInterface
    fun puntoMovido(extremo: String, lat: Double, lng: Double) {
        val e = if (extremo == "B") ExtremoTramo.B else ExtremoTramo.A
        enHiloPrincipal { eventos().onPuntoMovido(e, lat, lng) }
    }
}

/**
 * Mapa para marcar el tramo A → B. Solo dibuja el `WebView` y empuja el estado; no conoce el
 * ViewModel. El estado vive en el ViewModel: el mapa avisa (`toque`, `puntoMovido`) y la app
 * responde con `setPuntos`.
 */
@Composable
internal fun CalibracionMapaContent(
    puntoA: PuntoTramo?,
    puntoB: PuntoTramo?,
    bloqueado: Boolean,
    eventos: CalibracionMapaEventos,
    modifier: Modifier = Modifier,
) {
    if (LocalInspectionMode.current) {
        Box(modifier.background(Color(0xFF0A0E1A)), contentAlignment = Alignment.Center) {
            Text("Mapa (vista previa)", color = Color(0xFFA9B0D9))
        }
        return
    }

    val mapa = rememberMapaWeb()
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { CalibracionPuente(mapa) { eventosActuales } }

    MapaWebView(
        mapa = mapa,
        html = "calibracion_mapa.html",
        puente = puente,
        nombrePuente = "CalibracionBridge",
        tag = "CalibracionMapa",
        modifier = modifier,
        pasarInsets = false,
        manejarAtras = false,
    )

    // Encuadre inicial solo si aún no hay puntos (con puntos, setPuntos encuadra el tramo).
    LaunchedEffect(mapa.listo) {
        if (mapa.listo && puntoA == null) mapa.js("setCentro($CENTRO_LAT, $CENTRO_LNG, $ZOOM_INICIAL)")
    }
    LaunchedEffect(mapa.listo, puntoA, puntoB) {
        if (mapa.listo) mapa.js("setPuntos(${literalJs(puntosJson(puntoA, puntoB))})")
    }
    LaunchedEffect(mapa.listo, bloqueado) {
        if (mapa.listo) mapa.js("setBloqueado($bloqueado)")
    }
}

private fun puntosJson(a: PuntoTramo?, b: PuntoTramo?): String {
    fun JSONObject.punto(clave: String, p: PuntoTramo?) {
        put(clave, p?.let { JSONObject().put("lat", it.lat).put("lng", it.lng) } ?: JSONObject.NULL)
    }
    return JSONObject().apply { punto("a", a); punto("b", b) }.toString()
}