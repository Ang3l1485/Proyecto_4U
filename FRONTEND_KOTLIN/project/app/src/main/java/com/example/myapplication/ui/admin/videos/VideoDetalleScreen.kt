package com.example.myapplication.ui.admin.videos

import android.webkit.JavascriptInterface
import android.webkit.WebResourceResponse
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.data.local.MiniaturasLocales
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import com.example.myapplication.ui.admin.imagenes.GaleriaColores

/** Eventos que el mapa web (video_detalle.js) envía a la app. */
interface VideoDetalleEventos {
    fun abrirFoto(fotoId: String)
    fun renombrar(nombre: String)
    fun eliminarFoto(fotoId: String)
    fun eliminarVideo()
    fun salir()

    /** FE-4.1: la página activó «Mostrar otros videos» por primera vez. */
    fun pedirOtros() {}
}

/**
 * Vista 7.14 — Detalle de video (FE-4.1: contra el backend o un recorrido del teléfono sin subir). Es la que usa el
 * NavHost. Tapa el mapa mientras renombra o elimina ([VideoDetalleUiState.operacion]; Atrás no hace nada mientras
 * tanto), muestra los errores en un diálogo con «Reintentar» y, al confirmarse el borrado del video, avisa con un
 * `Toast` y llama a [onVolver]. «Ver detalle» de una foto (7.12) no está: la página lo muestra deshabilitado.
 */
@Composable
fun VideoDetalleScreen(
    videoId: String,
    onVolver: () -> Unit,
    modifier: Modifier = Modifier.fillMaxSize(),
    vm: VideoDetalleViewModel = viewModel(key = "video-$videoId", factory = VideoDetalleViewModel.Factory(videoId)),
) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    val contexto = LocalContext.current
    val app = contexto.applicationContext
    val miniaturas = remember(app) { MiniaturasLocales.deLaApp(app) }
    val volver by rememberUpdatedState(onVolver)

    LaunchedEffect(vm) {
        vm.eventos.collect { evento ->
            when (evento) {
                is VideoDetalleEvento.Eliminado -> {
                    val fotos = evento.fotos?.let { " (${TextosVideos.fotos(it)} retiradas)" } ?: ""
                    Toast.makeText(contexto, "«${evento.nombre}» eliminado$fotos.", Toast.LENGTH_SHORT).show()
                    volver()
                }
            }
        }
    }
    LifecycleResumeEffect(vm) {
        vm.alReanudar()
        onPauseOrDispose { vm.alPausar() }
    }

    Box(modifier) {
        VideoDetalleContent(
            videoJson = ui.videoJson,
            otrosJson = ui.otrosJson,
            eventos = object : VideoDetalleEventos {
                override fun abrirFoto(fotoId: String) = Unit // 7.12 Detalle de imagen: fuera de FE-4.1
                override fun renombrar(nombre: String) = vm.renombrar(nombre)
                override fun eliminarFoto(fotoId: String) = vm.eliminarFoto(fotoId)
                override fun eliminarVideo() = vm.eliminarVideo()
                override fun salir() = onVolver()
                override fun pedirOtros() = vm.pedirOtros()
            },
            recursos = { url -> miniaturaWeb(miniaturas, url) },
        )
        when {
            ui.noEncontrado -> MensajeCompleto("No se encontró este video.", null, null, onVolver)
            ui.errorCarga != null && ui.videoJson == null ->
                MensajeCompleto(ui.errorCarga!!, "Reintentar", vm::reintentarCarga, onVolver)
            ui.operacion != null -> Ocupado(ui.operacion!!.texto)
        }
    }
    // Mientras se renombra o elimina, Atrás no hace nada: no se sale antes de que el servidor confirme.
    BackHandler(enabled = ui.operacion != null) {}

    ui.aviso?.let { aviso ->
        AlertDialog(
            onDismissRequest = vm::descartarAviso,
            containerColor = GaleriaColores.Tarjeta,
            titleContentColor = GaleriaColores.Texto,
            textContentColor = GaleriaColores.TextoSuave,
            title = { Text(aviso.titulo) },
            text = { Text(aviso.mensaje, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) },
            confirmButton = {
                if (aviso.reintento != null) {
                    TextButton(onClick = vm::reintentar) { Text("Reintentar", color = GaleriaColores.Acento) }
                }
            },
            dismissButton = { TextButton(onClick = vm::descartarAviso) { Text("Cerrar", color = GaleriaColores.TextoSuave) } },
        )
    }
}

/** Respuesta del `WebView` para una miniatura local (`https://miniaturas.local/…`), o `null` si la URL no es de esas. */
private fun miniaturaWeb(miniaturas: MiniaturasLocales, url: String): WebResourceResponse? {
    if (MiniaturasLocales.ruta(url) == null) return null
    val archivo = miniaturas.archivo(url)
        ?: return WebResourceResponse("text/plain", "utf-8", 404, "No encontrada", emptyMap(), ByteArray(0).inputStream())
    return WebResourceResponse("image/jpeg", null, archivo.inputStream())
}

/**
 * Solo dibuja el WebView (`assets/video_detalle.html`: Leaflet + OpenStreetMap en línea) con el [MapaWebView] común.
 * Recibe todo como JSON; no conoce el ViewModel. [recursos] sirve las miniaturas de los recorridos del teléfono.
 */
@Composable
fun VideoDetalleContent(
    videoJson: String?,
    otrosJson: String?,
    eventos: VideoDetalleEventos,
    modifier: Modifier = Modifier.fillMaxSize(),
    recursos: ((String) -> WebResourceResponse?)? = null,
) {
    val mapa = rememberMapaWeb()
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { VideoPuente(mapa) { eventosActuales } }

    // El JS cierra primero el diálogo o la foto seleccionada y al final llama a salir().
    MapaWebView(
        mapa, html = "video_detalle.html", puente = puente, nombrePuente = "VideoBridge", tag = "VideoDetalle",
        modifier = modifier, recursos = recursos,
    )

    // Empuja el estado al mapa cuando la página avisa que está lista y cada vez que cambia.
    LaunchedEffect(mapa.listo, otrosJson) { if (mapa.listo && otrosJson != null) mapa.js("cargarOtros(${literalJs(otrosJson)})") }
    LaunchedEffect(mapa.listo, videoJson) { if (mapa.listo && videoJson != null) mapa.js("cargarVideo(${literalJs(videoJson)})") }
}

/** Puente `VideoBridge` (web → app). `listo()` viene de [PuenteWeb]. Debe ser `internal` o público: el WebView lo invoca por reflexión. */
internal class VideoPuente(mapa: MapaWeb, private val eventos: () -> VideoDetalleEventos) : PuenteWeb(mapa) {
    @JavascriptInterface fun abrirFoto(id: String) { enHiloPrincipal { eventos().abrirFoto(id) } }
    @JavascriptInterface fun renombrar(nombre: String) { enHiloPrincipal { eventos().renombrar(nombre) } }
    @JavascriptInterface fun eliminarFoto(id: String) { enHiloPrincipal { eventos().eliminarFoto(id) } }
    @JavascriptInterface fun eliminarVideo() { enHiloPrincipal { eventos().eliminarVideo() } }
    @JavascriptInterface fun salir() { enHiloPrincipal { eventos().salir() } }
    @JavascriptInterface fun pedirOtros() { enHiloPrincipal { eventos().pedirOtros() } }
}

/** Tapa la pantalla (y sus toques) mientras dura una operación. */
@Composable
private fun Ocupado(texto: String) {
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xCC0A0E1A))
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier
                .background(GaleriaColores.Tarjeta, RoundedCornerShape(16.dp))
                .padding(24.dp)
                .semantics { liveRegion = LiveRegionMode.Polite },
        ) {
            CircularProgressIndicator(color = GaleriaColores.Primario)
            Text(texto, color = Color.White, fontSize = 17.sp)
        }
    }
}

/** Pantalla completa con un mensaje (no encontrado o error al cargar) y sus botones. */
@Composable
private fun MensajeCompleto(texto: String, accion: String?, onAccion: (() -> Unit)?, onVolver: () -> Unit) {
    Column(
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0A0E1A))
            .padding(24.dp),
    ) {
        Text(texto, color = Color.White, fontSize = 16.sp, textAlign = TextAlign.Center)
        if (accion != null && onAccion != null) {
            Button(onClick = onAccion, modifier = Modifier.heightIn(min = 48.dp)) { Text(accion) }
        }
        OutlinedButton(onClick = onVolver, modifier = Modifier.heightIn(min = 48.dp)) { Text("Volver", color = Color.White) }
    }
}