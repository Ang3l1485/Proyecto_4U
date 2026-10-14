package com.example.myapplication.ui.admin.videos

import android.webkit.JavascriptInterface
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb

/** Eventos que el mapa web (video_detalle.js) envía a la app. */
interface VideoDetalleEventos {
    fun abrirFoto(fotoId: String)
    fun renombrar(nombre: String)
    fun eliminarFoto(fotoId: String)
    fun eliminarVideo()
    fun salir()
}

/** Vista 7.14 — Detalle de video. Es la que se usa en el NavHost. */
@Composable
fun VideoDetalleScreen(
    videoId: String,
    onVolver: () -> Unit,
    onAbrirImagen: (videoId: String, fotoId: String) -> Unit,
    modifier: Modifier = Modifier.fillMaxSize(),
    vm: VideoDetalleViewModel = viewModel(
        key = "video-$videoId",
        factory = VideoDetalleViewModel.Factory(LocalContext.current.applicationContext, videoId),
    ),
) {
    val ui by vm.ui.collectAsStateWithLifecycle()

    Box(modifier) {
        VideoDetalleContent(
            videoJson = ui.videoJson,
            otrosJson = ui.otrosJson,
            eventos = object : VideoDetalleEventos {
                override fun abrirFoto(fotoId: String) = onAbrirImagen(videoId, fotoId)
                override fun renombrar(nombre: String) = vm.renombrar(nombre)
                override fun eliminarFoto(fotoId: String) = vm.eliminarFoto(fotoId)
                override fun eliminarVideo() = vm.eliminarVideo()
                override fun salir() = onVolver()
            },
        )
        if (ui.noEncontrado) NoEncontrado(onVolver)
    }
}

/**
 * Solo dibuja el WebView (`assets/video_detalle.html`: Leaflet + OpenStreetMap en línea) con el [MapaWebView] común.
 * Recibe todo como JSON; no conoce el ViewModel.
 */
@Composable
fun VideoDetalleContent(
    videoJson: String?,
    otrosJson: String,
    eventos: VideoDetalleEventos,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    val mapa = rememberMapaWeb()
    val eventosActuales by rememberUpdatedState(eventos)
    val puente = remember(mapa) { VideoPuente(mapa) { eventosActuales } }

    // El JS cierra primero el diálogo o la foto seleccionada y al final llama a salir().
    MapaWebView(mapa, html = "video_detalle.html", puente = puente, nombrePuente = "VideoBridge", tag = "VideoDetalle", modifier = modifier)

    // Empuja el estado al mapa cuando la página avisa que está lista y cada vez que cambia.
    LaunchedEffect(mapa.listo, otrosJson) { if (mapa.listo) mapa.js("cargarOtros(${literalJs(otrosJson)})") }
    LaunchedEffect(mapa.listo, videoJson) { if (mapa.listo && videoJson != null) mapa.js("cargarVideo(${literalJs(videoJson)})") }
}

/** Puente `VideoBridge` (web → app). `listo()` viene de [PuenteWeb]. Debe ser `internal` o público: el WebView lo invoca por reflexión. */
internal class VideoPuente(mapa: MapaWeb, private val eventos: () -> VideoDetalleEventos) : PuenteWeb(mapa) {
    @JavascriptInterface fun abrirFoto(id: String) { enHiloPrincipal { eventos().abrirFoto(id) } }
    @JavascriptInterface fun renombrar(nombre: String) { enHiloPrincipal { eventos().renombrar(nombre) } }
    @JavascriptInterface fun eliminarFoto(id: String) { enHiloPrincipal { eventos().eliminarFoto(id) } }
    @JavascriptInterface fun eliminarVideo() { enHiloPrincipal { eventos().eliminarVideo() } }
    @JavascriptInterface fun salir() { enHiloPrincipal { eventos().salir() } }
}

@Composable
private fun NoEncontrado(onVolver: () -> Unit) {
    Column(
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0A0E1A))
            .padding(24.dp),
    ) {
        Text("No se encontró este video.", color = Color.White, fontSize = 16.sp)
        Button(onClick = onVolver, modifier = Modifier.padding(top = 16.dp)) { Text("Volver") }
    }
}