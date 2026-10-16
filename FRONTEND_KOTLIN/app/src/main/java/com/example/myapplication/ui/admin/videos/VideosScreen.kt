package com.example.myapplication.ui.admin.videos

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Video
import com.example.myapplication.ui.admin.imagenes.GaleriaColores

/** Vista 7.13 (versión mínima) — Lista de videos. Pendiente: búsqueda, orden y filtros. */
@Composable
fun VideosScreen(
    onVolver: () -> Unit,
    onAbrirVideo: (videoId: String) -> Unit,
    viewModel: VideosViewModel = viewModel(
        factory = VideosViewModel.Factory(LocalContext.current.applicationContext)
    ),
) {
    val state by viewModel.uiState.collectAsState()
    VideosContent(state, onVolver, onAbrirVideo, viewModel::reintentar)
}

@Composable
fun VideosContent(
    state: VideosUiState,
    onVolver: () -> Unit,
    onAbrirVideo: (String) -> Unit,
    onReintentar: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(
        modifier = modifier,
        containerColor = GaleriaColores.Fondo,
        topBar = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().background(GaleriaColores.Fondo).padding(horizontal = 4.dp, vertical = 4.dp),
            ) {
                IconButton(onClick = onVolver, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver", tint = GaleriaColores.Primario)
                }
                Text(
                    "Videos de recolección",
                    color = GaleriaColores.Texto,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f).semantics { heading() },
                )
                Box(Modifier.size(48.dp))
            }
        },
    ) { padding ->
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            when {
                state.cargando -> item {
                    Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = GaleriaColores.Primario)
                    }
                }
                state.error != null -> item { Mensaje(state.error, "Reintentar", onReintentar) }
                state.videos.isEmpty() -> item { Mensaje("Todavía no hay videos.") }
                else -> {
                    item {
                        Text(
                            if (state.videos.size == 1) "1 video" else "${state.videos.size} videos",
                            color = GaleriaColores.Acento,
                            fontSize = 16.sp,
                        )
                    }
                    items(state.videos, key = { it.id }) { video ->
                        TarjetaVideo(video) { onAbrirVideo(video.id) }
                    }
                }
            }
        }
    }
}

@Composable
private fun TarjetaVideo(video: Video, onClick: () -> Unit) {
    val forma = RoundedCornerShape(16.dp)
    val (estado, colorEstado) = video.estado()
    val fecha = video.creadoEn?.take(10)?.split("-")?.reversed()?.joinToString("/")
    val detalle = listOfNotNull(
        fecha,
        if (video.fotos.size == 1) "1 foto" else "${video.fotos.size} fotos",
        formatearDistancia(video.distanciaMetros),
    ).joinToString(" · ")

    Column(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .clip(forma)
            .background(GaleriaColores.Tarjeta)
            .border(1.dp, GaleriaColores.Borde, forma)
            .clickable(role = Role.Button, onClickLabel = "Abrir detalle del video", onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = "Video ${video.nombre}, $detalle, $estado" }
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(video.nombre, color = GaleriaColores.Texto, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Text(detalle, color = GaleriaColores.TextoSuave, fontSize = 14.sp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).background(colorEstado, CircleShape))
            Text(estado, color = GaleriaColores.TextoSuave, fontSize = 13.sp, modifier = Modifier.padding(start = 6.dp))
        }
    }
}

private fun Video.estado(): Pair<String, Color> = when {
    fotos.isEmpty() -> "Sin fotos" to GaleriaColores.TextoSuave
    fotos.any { it.estado == EstadoFoto.ERROR } -> "Con errores" to GaleriaColores.Rojo
    fotos.all { it.estado == EstadoFoto.PROCESADA } -> "Procesado" to GaleriaColores.Verde
    else -> "Pendiente de proceso" to GaleriaColores.Azul
}

private fun formatearDistancia(m: Double): String =
    if (m < 1000) "${Math.round(m)} m" else "%.2f km".format(m / 1000)

@Composable
private fun Mensaje(texto: String, accion: String? = null, onAccion: () -> Unit = {}) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp),
    ) {
        Text(texto, color = GaleriaColores.TextoSuave, fontSize = 16.sp)
        if (accion != null) {
            Button(
                onClick = onAccion,
                colors = ButtonDefaults.buttonColors(containerColor = GaleriaColores.Primario),
                modifier = Modifier.heightIn(min = 48.dp),
            ) { Text(accion) }
        }
    }
}