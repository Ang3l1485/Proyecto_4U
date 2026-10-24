package com.example.myapplication.map

import android.annotation.SuppressLint
import android.content.pm.ApplicationInfo
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import com.example.myapplication.logs.AppLog
import com.example.myapplication.sensors.PdrEvento
import com.example.myapplication.sensors.PdrTracker
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.coroutines.launch

private const val TAG = "MapaPublico"

private data class Posicion(
    val lat: Double,
    val lng: Double,
    val pasos: Int,
    val distanciaM: Double,
    val velocidadMps: Double,
)

/** Llama a `window.<codigo>` en la página; si la función no existe, no pasa nada. */
private fun WebView.js(codigo: String) {
    evaluateJavascript("try{window.$codigo}catch(e){}", null)
}

/**
 * Mapa público (Leaflet + OSM en un WebView) con seguimiento por pasos.
 * El cálculo de la posición NO está en la página: lo hace [PdrTracker] (sensors/) y aquí solo se
 * empuja el resultado a `app.js`.
 *
 * Kotlin → Web: `onNativePosition(lat, lng, pasos, distanciaM, velocidadMps)`,
 * `onNativeHeading(grados)`, `onNativeAccel(desviacion)`, `onNativeBrujula(disponible)`,
 * `onNativeStepUnavailable(motivo)`.
 * Web → Kotlin: ver [PuentePdr].
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MapaPublicoScreen(modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val tracker = remember { PdrTracker(ctx) }
    var webView by remember { mutableStateOf<WebView?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            tracker.liberar()
            webView?.destroy()
        }
    }

    // Kotlin → Web
    LaunchedEffect(webView) {
        val w = webView ?: return@LaunchedEffect
        tracker.onAceleracion = { d -> w.js("onNativeAccel($d)") }
        try {
            coroutineScope {
                launch {
                    tracker.estado
                        .mapNotNull { e ->
                            val la = e.lat
                            val ln = e.lng
                            if (la != null && ln != null) {
                                Posicion(la, ln, e.pasos, e.distanciaMetros, e.velocidadMps)
                            } else null
                        }
                        .distinctUntilChanged()
                        .collect { p ->
                            w.js("onNativePosition(${p.lat},${p.lng},${p.pasos},${p.distanciaM},${p.velocidadMps})")
                        }
                }
                launch {
                    tracker.estado
                        .filter { it.activo }
                        .map { it.rumboGrados }
                        .distinctUntilChanged()
                        .collect { w.js("onNativeHeading($it)") }
                }
                launch {
                    tracker.eventos.collect { ev ->
                        when (ev) {
                            is PdrEvento.Brujula -> w.js("onNativeBrujula(${ev.disponible})")
                            is PdrEvento.PasosPorAcelerometro ->
                                w.js("onNativeStepUnavailable('${ev.motivo}')")
                        }
                    }
                }
            }
        } finally {
            tracker.onAceleracion = null
        }
    }

    AndroidView(
        modifier = modifier
            .fillMaxSize()
            .systemBarsPadding(),
        factory = { c ->
            if (c.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {
                WebView.setWebContentsDebuggingEnabled(true)
            }
            WebView(c).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                setBackgroundColor(Color(0xFF0A0E1A).toArgb()) // = --bg-dark de index.html
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webChromeClient = object : WebChromeClient() {
                    override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                        AppLog.d(TAG, "JS: ${m.message()} (línea ${m.lineNumber()})")
                        return true
                    }
                    // Geolocalización: sin sobrescribir onGeolocationPermissionsShowPrompt el
                    // botón GPS falla con un aviso (decisión abierta 14 de ARCHITECTURE.md).
                }
                addJavascriptInterface(PuentePdr(tracker), "AndroidBridge")
                loadUrl("file:///android_asset/index.html")
                webView = this
            }
        },
    )
}