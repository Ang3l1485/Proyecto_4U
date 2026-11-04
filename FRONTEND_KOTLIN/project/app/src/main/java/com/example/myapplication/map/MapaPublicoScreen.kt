package com.example.myapplication.map

import android.annotation.SuppressLint
import android.content.pm.ApplicationInfo
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.example.myapplication.data.local.GrafoDeLaApp
import com.example.myapplication.data.remote.AlertasPublicas
import com.example.myapplication.data.remote.CacheAlertasPublicas
import com.example.myapplication.domain.model.SesionDeNavegacion
import com.example.myapplication.domain.ruta.ResultadoRuta
import com.example.myapplication.domain.usecase.Deriva
import com.example.myapplication.domain.usecase.DetectarAlertasCercanas
import com.example.myapplication.domain.usecase.SeguimientoAlertas
import com.example.myapplication.logs.AppLog
import com.example.myapplication.sensors.PdrEvento
import com.example.myapplication.sensors.PdrTracker
import com.example.myapplication.ui.inicio.VoiceController
import com.example.myapplication.ui.ubicacion.FeedbackCaptura
import kotlin.math.roundToInt
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
 *
 * Ruta `mapa` (FE-3.1: desde Inicio por la voz «mapa» o la acción de TalkBack «Ver mapa»; Atrás vuelve a Inicio). Los
 * sensores siguen el ciclo de vida de la entrada de la pila de esta pantalla (ADR-FE-22): se quitan en su `ON_STOP`
 * (app en segundo plano, o el mapa tapado por otra pantalla) y se liberan al salir de la composición.
 *
 * FE-5.1: con un destino (el de `SesionDeNavegacion`, elegido en 6.4, o el de prueba de [PruebaMapa]) y una posición
 * (toque, GPS o la de prueba), calcula la ruta por el grafo (`GrafoDeLaApp`) en cada cambio de posición, la dibuja
 * (`onNativeRuta(json|null)`) y muestra arriba un aviso en Compose con la distancia por el camino y la primera
 * instrucción ([TextosRutaMapa]). La página avisa que está lista con `AndroidBridge.listo()`; en el APK de depuración,
 * la posición de prueba se envía con `onNativeInicio(lat, lng)` (como un toque).
 *
 * FE-3.6 (ADR-FE-41): con una ubicación vigente de «Ubicarme» (`SesionDeNavegacion.ubicacionVigente()`, y sin posición
 * de prueba de FE-5.1) el seguimiento empieza **sin tocar el mapa**: Kotlin fija esa posición en el [PdrTracker] y lo
 * inicia al abrir (no depende de la página ni de la red); cuando la página está lista, `onNativeRastreoIniciado(lat,
 * lng)` la pone en «Rastreando». En cada cambio de posición, [SeguimientoAlertas] busca en la caché local
 * (`AlertasPublicas`) las alertas que empiezan una aproximación (radio + incertidumbre = radio de «Ubicarme» o 0 tras
 * un toque, más la deriva del 4 % de lo caminado desde ese punto) y las anuncia: voz (la primera de prioridad alta
 * corta lo que se esté diciendo; las demás se encolan), vibración y un aviso «Alerta: …» arriba.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MapaPublicoScreen(modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    // FE-3.1 (ADR-FE-22): el tracker sigue el ciclo de vida de esta pantalla (la entrada de la pila), no el del
    // proceso: si el mapa queda en la pila sin ser lo visible (o en otra tarea), sus sensores no vuelven al primer plano.
    val cicloPantalla = LocalLifecycleOwner.current.lifecycle
    val lifecycleOwner = LocalLifecycleOwner.current
    val tracker = remember { PdrTracker(ctx, cicloDeVida = cicloPantalla) }
    var webView by remember { mutableStateOf<WebView?>(null) }

    // FE-3.6: inicio desde «Ubicarme» (la posición de prueba de FE-5.1, si la hay, gana: se usa como un toque).
    val inicioUbicarme = remember {
        if (PruebaMapa.posicion == null) SesionDeNavegacion.ubicacionVigente()?.ubicado?.posicion else null
    }
    val alertasPublicas = remember { AlertasPublicas.de(ctx) }
    val cacheAlertas by alertasPublicas.estado.collectAsState()
    val seguimiento = remember { SeguimientoAlertas() }
    val voz = remember { VoiceController(ctx) }
    val vibracion = remember { FeedbackCaptura(ctx) }
    // Incertidumbre del punto de partida y distancia del PDR en ese momento (la deriva cuenta desde ahí).
    var radioInicialM by remember { mutableStateOf(inicioUbicarme?.radioM ?: 0.0) }
    var anclaDistanciaM by remember { mutableStateOf(0.0) }
    var ultimaAlerta by remember { mutableStateOf<String?>(null) }

    // FE-5.1: ruta por el grafo. `null` = rutas desactivadas (grafo inválido o ilegible; nunca lanza).
    val planificador = remember { runCatching { GrafoDeLaApp.planificador(ctx) }.getOrNull() }
    val destinoSesion by SesionDeNavegacion.destino.collectAsState()
    val destinoPrueba = remember { PruebaMapa.destino }
    var paginaLista by remember { mutableStateOf(false) }
    var posicionActual by remember { mutableStateOf<Pair<Double, Double>?>(null) }
    var aviso by remember { mutableStateOf<AvisoRuta?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            tracker.liberar()
            webView?.destroy()
            PruebaMapa.limpiar()
            voz.release()
            vibracion.liberar()
        }
    }

    // FE-3.6: al dejar de verse el mapa, calla (los sensores ya se quitan solos, ADR-FE-22).
    DisposableEffect(lifecycleOwner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_STOP) voz.stopAll() }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
    }

    // FE-3.6: con una ubicación vigente de «Ubicarme», el seguimiento empieza aquí sin tocar el mapa ni pulsar ▶.
    LaunchedEffect(Unit) {
        val p = inicioUbicarme ?: return@LaunchedEffect
        tracker.fijarPosicion(p.lat, p.lng)
        tracker.iniciar()
        AppLog.i(TAG, "Inicio desde Ubicarme (radio ${p.radioM.roundToInt()} m): seguimiento iniciado sin tocar el mapa")
        voz.speak(INICIO_UBICARME)
    }

    // FE-3.6: el punto de partida (y el estado de las aproximaciones) cambia si la persona toca el mapa.
    val alFijarPosicion: (Double, Double) -> Unit = { _, _ ->
        radioInicialM = 0.0
        anclaDistanciaM = tracker.estado.value.distanciaMetros
        seguimiento.reiniciar()
    }

    // FE-3.6: alertas al cambiar la posición o la caché (la vigencia se evalúa ahora).
    LaunchedEffect(posicionActual, cacheAlertas.alertas) {
        val pos = posicionActual ?: return@LaunchedEffect
        val caminado = (tracker.estado.value.distanciaMetros - anclaDistanciaM).coerceAtLeast(0.0)
        val incertidumbre = radioInicialM + Deriva.estimar(caminado).derivaM
        val avisos = seguimiento.actualizar(
            cacheAlertas.alertas, pos.first, pos.second, incertidumbre, System.currentTimeMillis(),
        )
        avisos.forEachIndexed { i, a ->
            AppLog.i(CacheAlertasPublicas.TAG, DetectarAlertasCercanas.lineaAnunciada("mapa", a, incertidumbre))
            val texto = DetectarAlertasCercanas.texto(a.alerta)
            // La primera, si es de prioridad alta, corta lo que se esté diciendo; las demás esperan su turno.
            if (i == 0 && a.alta) voz.speak(texto) else voz.speakEncolado(texto)
        }
        if (avisos.isNotEmpty()) {
            vibracion.confirmar()
            ultimaAlerta = DetectarAlertasCercanas.texto(avisos.first().alerta)
        }
    }

    // FE-5.1: posición actual (solo cambia con la posición, no con el rumbo).
    LaunchedEffect(tracker) {
        tracker.estado
            .mapNotNull { e ->
                val la = e.lat
                val ln = e.lng
                if (la != null && ln != null) la to ln else null
            }
            .distinctUntilChanged()
            .collect { posicionActual = it }
    }

    // FE-5.1: posición de prueba (solo APK de depuración, PruebaMapa), una vez, cuando la página está lista.
    LaunchedEffect(paginaLista, webView) {
        val w = webView ?: return@LaunchedEffect
        if (!paginaLista) return@LaunchedEffect
        // FE-3.6: el seguimiento ya empezó en Kotlin desde «Ubicarme»: la página dibuja el inicio y la posición actual
        // y se pone en «Rastreando» sin volver a fijar la posición (no salta atrás si ya se caminó).
        inicioUbicarme?.let { p ->
            w.js("onNativeRastreoIniciado(${p.lat},${p.lng})")
            val e = tracker.estado.value
            val la = e.lat
            val ln = e.lng
            if (la != null && ln != null) {
                w.js("onNativePosition($la,$ln,${e.pasos},${e.distanciaMetros},${e.velocidadMps})")
            }
        }
        val p = PruebaMapa.posicion ?: return@LaunchedEffect
        PruebaMapa.posicion = null
        w.js("onNativeInicio(${p.first},${p.second})")
    }

    // FE-5.1: ruta en cada cambio de posición o de destino.
    LaunchedEffect(paginaLista, webView, posicionActual, destinoSesion) {
        val nombres: List<String>?
        val mostrar: String?
        if (destinoPrueba != null) {
            nombres = listOf(destinoPrueba)
            mostrar = TextosRutaMapa.nombrePrueba(planificador, destinoPrueba)
        } else {
            val d = destinoSesion
            // FE-5.1 (decisión del usuario del 2026-10-28): la meta sale de las coordenadas del lugar, no de su nombre.
            nombres = d?.let { listOf("${it.lat},${it.lng}") }
            mostrar = d?.nombre
        }
        val pos = posicionActual
        val resultado = if (planificador != null && nombres != null && mostrar != null && pos != null) {
            val e = tracker.estado.value
            val rumbo = if (e.activo) e.rumboGrados.toDouble() else null
            runCatching { planificador.calcular(pos.first, pos.second, nombres, mostrar, rumbo) }.getOrNull()
        } else {
            null
        }
        aviso = TextosRutaMapa.aviso(mostrar, planificador != null, pos != null, resultado)
        val w = webView
        if (w != null && paginaLista) {
            val ruta = (resultado as? ResultadoRuta.Encontrada)?.ruta
            w.js("onNativeRuta(${ruta?.json() ?: "null"})")
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

    Column(
        modifier = modifier
            .fillMaxSize()
            .systemBarsPadding(),
    ) {
        aviso?.let { AvisoRutaMapa(it) }
        ultimaAlerta?.let { AvisoAlertaMapa(it) }
        AndroidView(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
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
                    addJavascriptInterface(
                        PuentePdr(tracker, alListo = { paginaLista = true }, alFijarPosicion = alFijarPosicion),
                        "AndroidBridge",
                    )
                    loadUrl("file:///android_asset/index.html")
                    webView = this
                }
            },
        )
    }
}

/** FE-5.1: aviso de ruta sobre el mapa (lo lee TalkBack al cambiar y `uiautomator` en la validación). */
@Composable
private fun AvisoRutaMapa(aviso: AvisoRuta) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF0A0E1A))
            .padding(horizontal = 16.dp, vertical = 10.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
    ) {
        Text(aviso.titulo, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        aviso.detalle?.let { Text(it, color = Color(0xFFB9F6CA), fontSize = 16.sp) }
    }
}

/** FE-3.6: lo que se dice al abrir el mapa con el seguimiento empezado desde «Ubicarme». */
internal const val INICIO_UBICARME = "Sigo tus pasos desde tu última ubicación."

/** FE-3.6: prefijo del aviso de la última alerta anunciada (lo lee `validate36.py` con `uiautomator`). */
internal const val PREFIJO_ALERTA = "Alerta: "

/**
 * FE-3.6: la última alerta anunciada, sobre el mapa. Sin *live region*: ya la dice la voz de la app (TalkBack la lee si
 * se toca).
 */
@Composable
private fun AvisoAlertaMapa(texto: String) {
    Text(
        text = "$PREFIJO_ALERTA$texto",
        color = Color(0xFF1A1200),
        fontSize = 18.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFFFFC94D))
            .padding(horizontal = 16.dp, vertical = 10.dp),
    )
}