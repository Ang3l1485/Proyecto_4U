package com.example.myapplication.ui.admin.videos

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.OrdenVideos
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.ui.admin.imagenes.GaleriaColores

/** Acciones de 7.13 (FE-4.1), con valores por defecto para el preview. */
data class VideosAcciones(
    val onVolver: () -> Unit = {},
    val onAbrirVideo: (String) -> Unit = {},
    val onNuevoVideo: () -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onBuscar: (String) -> Unit = {},
    val onOrden: (OrdenVideos) -> Unit = {},
)

/**
 * Vista 7.13 — Lista de videos (FE-4.1): los del servidor y, arriba, los recorridos de este teléfono sin subir. **No
 * navega**: [onAbrirVideo] (7.14) y [onNuevoVideo] (7.3) los conecta `AppNav`.
 */
@Composable
fun VideosScreen(
    onVolver: () -> Unit,
    onAbrirVideo: (videoId: String) -> Unit,
    onNuevoVideo: () -> Unit,
    viewModel: VideosViewModel = viewModel(factory = VideosViewModel.Factory()),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    VideosContent(
        state = state,
        acciones = VideosAcciones(
            onVolver = onVolver,
            onAbrirVideo = onAbrirVideo,
            onNuevoVideo = onNuevoVideo,
            onReintentar = viewModel::reintentar,
            onBuscar = viewModel::buscar,
            onOrden = viewModel::ordenar,
        ),
    )
}

@Composable
fun VideosContent(state: VideosUiState, acciones: VideosAcciones, modifier: Modifier = Modifier) {
    Scaffold(
        modifier = modifier,
        containerColor = GaleriaColores.Fondo,
        topBar = { Encabezado(state, acciones.onVolver) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = acciones.onNuevoVideo,
                containerColor = GaleriaColores.Primario,
                contentColor = Color.White,
                icon = { Icon(Icons.Filled.Add, contentDescription = null) },
                text = { Text("Nuevo video", fontSize = 16.sp) },
                modifier = Modifier.navigationBarsPadding(),
            )
        },
    ) { padding ->
        LazyColumn(
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 96.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            item { Busqueda(state.busqueda, acciones.onBuscar) }
            item { FilaOrden(state.orden, acciones.onOrden) }
            if (state.errorServidor != null) {
                item { Mensaje(state.errorServidor, "Reintentar", acciones.onReintentar) }
            }
            if (state.cargando && state.locales.isEmpty() && state.servidor.isEmpty()) {
                item {
                    Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = GaleriaColores.Primario)
                    }
                }
            }
            if (state.locales.isNotEmpty()) {
                item { Seccion("En este teléfono (sin subir)") }
                items(state.locales, key = { "local-${it.id}" }) { v -> TarjetaVideo(v) { acciones.onAbrirVideo(v.id) } }
                if (state.servidor.isNotEmpty()) item { Seccion("En el servidor") }
            }
            items(state.servidor, key = { it.id }) { v -> TarjetaVideo(v) { acciones.onAbrirVideo(v.id) } }
            if (state.vacia) {
                item {
                    Mensaje(
                        if (state.busqueda.isBlank()) "Todavía no hay videos." else "No hay videos con «${state.busqueda.trim()}».",
                    )
                }
            }
        }
    }
}

@Composable
private fun Encabezado(state: VideosUiState, onVolver: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().background(GaleriaColores.Fondo).padding(horizontal = 4.dp, vertical = 4.dp),
    ) {
        IconButton(onClick = onVolver, modifier = Modifier.size(48.dp)) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver", tint = GaleriaColores.Primario)
        }
        Column(Modifier.weight(1f)) {
            Text(
                TextosVideos.TITULO_LISTA,
                color = GaleriaColores.Texto,
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                state.totalServidor?.let {
                    Text(TextosVideos.total(it), color = GaleriaColores.Acento, fontSize = 15.sp)
                }
                if (state.locales.isNotEmpty()) {
                    Text(TextosVideos.sinSubir(state.locales.size), color = GaleriaColores.Naranja, fontSize = 15.sp)
                }
            }
        }
    }
}

@Composable
private fun Busqueda(valor: String, onCambio: (String) -> Unit) {
    OutlinedTextField(
        value = valor,
        onValueChange = onCambio,
        singleLine = true,
        placeholder = { Text("Buscar por nombre…", color = GaleriaColores.TextoSuave) },
        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null, tint = GaleriaColores.Primario) },
        trailingIcon = if (valor.isNotEmpty()) {
            {
                IconButton(onClick = { onCambio("") }) {
                    Icon(Icons.Filled.Close, contentDescription = "Borrar búsqueda", tint = GaleriaColores.TextoSuave)
                }
            }
        } else null,
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = GaleriaColores.Texto,
            unfocusedTextColor = GaleriaColores.Texto,
            focusedBorderColor = GaleriaColores.Primario,
            unfocusedBorderColor = GaleriaColores.Borde,
            cursorColor = GaleriaColores.Primario,
        ),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).semantics { contentDescription = "Buscar videos por nombre" },
    )
}

@Composable
private fun FilaOrden(orden: OrdenVideos, onOrden: (OrdenVideos) -> Unit) {
    Row(
        Modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Ordenar:", color = GaleriaColores.TextoSuave, fontSize = 14.sp)
        OrdenVideos.entries.forEach { o ->
            FilterChip(
                selected = o == orden,
                onClick = { onOrden(o) },
                label = { Text(o.etiqueta, fontSize = 14.sp) },
                colors = FilterChipDefaults.filterChipColors(
                    labelColor = GaleriaColores.Texto,
                    selectedContainerColor = GaleriaColores.Primario.copy(alpha = 0.35f),
                    selectedLabelColor = GaleriaColores.Texto,
                ),
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "Ordenar por ${o.etiqueta}" },
            )
        }
    }
}

@Composable
private fun Seccion(texto: String) {
    Text(
        texto,
        color = GaleriaColores.Acento,
        fontSize = 14.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 4.dp).semantics { heading() },
    )
}

@Composable
private fun TarjetaVideo(video: ResumenVideo, onClick: () -> Unit) {
    val forma = RoundedCornerShape(16.dp)
    val colorEstado = video.colorEstado()
    Column(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .clip(forma)
            .background(GaleriaColores.Tarjeta)
            .border(1.dp, if (video.local) GaleriaColores.Naranja.copy(alpha = 0.7f) else GaleriaColores.Borde, forma)
            .clickable(role = Role.Button, onClickLabel = "Abrir detalle del video", onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = TextosVideos.descripcionFila(video) }
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (video.local) {
                Icon(Icons.Filled.PhoneAndroid, contentDescription = null, tint = GaleriaColores.Naranja, modifier = Modifier.size(18.dp))
            }
            Text(video.nombre, color = GaleriaColores.Texto, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        }
        Text(TextosVideos.detalleFila(video), color = GaleriaColores.TextoSuave, fontSize = 14.sp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).background(colorEstado, CircleShape))
            Text(
                TextosVideos.estado(video) + if (video.local) " · en este teléfono" else "",
                color = GaleriaColores.TextoSuave,
                fontSize = 13.sp,
                modifier = Modifier.padding(start = 6.dp),
            )
        }
    }
}

private fun ResumenVideo.colorEstado(): Color = when {
    estado == EstadoVideo.SIN_SUBIR || estado == EstadoVideo.SUBIENDO -> GaleriaColores.Naranja
    fotos == 0 -> GaleriaColores.TextoSuave
    estado == EstadoVideo.SUBIDA_A_MEDIAS -> GaleriaColores.TextoSuave
    estado == EstadoVideo.PROCESANDO -> GaleriaColores.Azul
    estado == EstadoVideo.PROCESADO -> GaleriaColores.Verde
    else -> GaleriaColores.Rojo
}

@Composable
private fun Mensaje(texto: String, accion: String? = null, onAccion: () -> Unit = {}) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp).semantics { liveRegion = LiveRegionMode.Polite },
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

@Preview(showBackground = true, backgroundColor = 0xFF0A0A1E, heightDp = 800, widthDp = 380)
@Composable
private fun VideosPreview() {
    val servidor = ResumenVideo(
        "9c1d0000-0000-4000-8000-000000000001", "Entrada norte", "2026-10-27T15:04:05Z", null, 120, 340.5, 512,
        EstadoVideo.PROCESADO, numero = 12,
    )
    val local = ResumenVideo(
        "rec_0013", "video_14", "2026-10-27T09:00:00-05:00", null, 42, 120.0, 300, EstadoVideo.SIN_SUBIR, local = true,
    )
    VideosContent(
        state = VideosUiState(cargando = false, locales = listOf(local), servidor = listOf(servidor), totalServidor = 1),
        acciones = VideosAcciones(),
    )
}