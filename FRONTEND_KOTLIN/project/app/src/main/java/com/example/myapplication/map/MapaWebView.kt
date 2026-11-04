package com.example.myapplication.map

import android.annotation.SuppressLint
import android.content.pm.ApplicationInfo
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.systemBars
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject

/**
 * Lo único que las pantallas necesitan del `WebView` de un mapa: saber cuándo la página avisó que está lista
 * (`listo`) y ejecutarle JavaScript (`js`). Se crea con [rememberMapaWeb] y se pasa a [MapaWebView].
 */
class MapaWeb internal constructor() {
    internal var webView: WebView? = null

    /** `true` cuando la página llamó a `listo()` por el puente. Hasta entonces no se le envía nada. */
    var listo by mutableStateOf(false)
        internal set

    /** Ejecuta JavaScript en la página. Siempre en el hilo principal. */
    fun js(codigo: String) { webView?.evaluateJavascript(codigo, null) }
}

@Composable
fun rememberMapaWeb(): MapaWeb = remember { MapaWeb() }

/** Texto → literal de JavaScript entre comillas (para pasar un JSON como `JSON.parse(literal)` sin escapar a mano). */
fun literalJs(s: String): String = JSONObject.quote(s)

/**
 * Base de los puentes `WebView` → Kotlin que usan [MapaWebView]. Las funciones `@JavascriptInterface` llegan en un hilo
 * del `WebView`: todo lo que toque la interfaz o el estado debe pasar por [enHiloPrincipal]. Ya trae `listo()`.
 *
 * La clase y sus subclases deben ser públicas o `internal` (nunca `private`): `WebView` las invoca por reflexión.
 */
open class PuenteWeb(private val mapa: MapaWeb) {
    private val principal = Handler(Looper.getMainLooper())

    protected fun enHiloPrincipal(bloque: () -> Unit) { principal.post(bloque) }

    @JavascriptInterface
    fun listo() { enHiloPrincipal { mapa.listo = true } }
}

/**
 * `WebView` común de las pantallas de mapa (Leaflet + OpenStreetMap en línea, páginas en `assets/`).
 *
 * @param html nombre de la página en `assets/` (p. ej. `"editor_mapa.html"`).
 * @param puente objeto con los métodos `@JavascriptInterface` (normalmente una subclase de [PuenteWeb]).
 * @param nombrePuente nombre con el que la página lo ve (`window.<nombrePuente>`).
 * @param tag etiqueta de Logcat para los mensajes de la consola JS y los errores de carga.
 * @param pasarInsets si es `true` envía `setInsets(top, bottom)` (alto de las barras del sistema en dp) cuando la página
 *   está lista. Ponerlo en `false` si la pantalla ya aplica `systemBarsPadding()` y la página no define `setInsets`.
 * @param manejarAtras si es `true` el botón Atrás del sistema llama a `window.onAtras()` de la página, que decide qué
 *   cerrar (diálogo, selección, modo…) y al final llama a `salir()` por el puente.
 * @param recursos (FE-4.1) responde peticiones de la página sin red: recibe la URL y devuelve la respuesta, o `null`
 *   para que el `WebView` la pida como siempre. Se llama **en un hilo del `WebView`** (no el principal) y puede
 *   bloquear; una excepción se convierte en `404`. Lo usa 7.14 para las miniaturas de los recorridos del teléfono
 *   (`https://miniaturas.local/…`, `MiniaturasLocales`).
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MapaWebView(
    mapa: MapaWeb,
    html: String,
    puente: Any,
    nombrePuente: String,
    tag: String,
    modifier: Modifier = Modifier.fillMaxSize(),
    pasarInsets: Boolean = true,
    manejarAtras: Boolean = true,
    recursos: ((String) -> WebResourceResponse?)? = null,
) {
    // Con edge-to-edge el WebView ocupa toda la pantalla y `env(safe-area-inset-*)` no funciona en WebView,
    // así que el alto de las barras del sistema se lo pasamos a la página.
    val density = LocalDensity.current
    val barras = WindowInsets.systemBars
    val topDp = barras.getTop(density) / density.density
    val bottomDp = barras.getBottom(density) / density.density

    if (manejarAtras) BackHandler { mapa.js("window.onAtras()") }

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            WebView(ctx).apply {
                // Sin tamaño explícito el WebView puede quedar en 0×0 y la pantalla se ve en blanco.
                layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                setBackgroundColor(Color.parseColor("#0A0E1A"))   // mismo fondo oscuro que las páginas
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true   // caché de teselas
                if (ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {
                    WebView.setWebContentsDebuggingEnabled(true)   // chrome://inspect en la PC
                }
                // Diagnóstico: errores de carga y mensajes de consola en Logcat (con el tag de cada pantalla).
                webChromeClient = object : WebChromeClient() {
                    override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                        Log.d(tag, "JS ${m.messageLevel()}: ${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                        return true
                    }
                }
                webViewClient = object : WebViewClient() {
                    override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                        Log.e(tag, "Error cargando ${request.url}: ${error.description}")
                    }

                    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                        val responder = recursos ?: return null
                        return try {
                            responder(request.url.toString())
                        } catch (e: Exception) {
                            Log.w(tag, "No se pudo servir un recurso local: ${e.javaClass.simpleName}")
                            WebResourceResponse("text/plain", "utf-8", 404, "No encontrado", emptyMap(), ByteArray(0).inputStream())
                        }
                    }
                }
                addJavascriptInterface(puente, nombrePuente)
                loadUrl("file:///android_asset/$html")
                mapa.webView = this
            }
        },
        onRelease = { it.destroy(); mapa.webView = null },
    )

    // Empuja las barras del sistema cuando la página avisa que está lista y cada vez que cambian.
    LaunchedEffect(mapa.listo, topDp, bottomDp, pasarInsets) {
        if (pasarInsets && mapa.listo) mapa.js("setInsets($topDp, $bottomDp)")
    }
}