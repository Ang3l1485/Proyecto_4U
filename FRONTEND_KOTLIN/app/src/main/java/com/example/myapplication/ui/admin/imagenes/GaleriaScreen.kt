package com.example.myapplication.ui.admin.imagenes

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.Video
import java.text.NumberFormat

// Paleta de la maqueta. TODO: moverla a ui/theme/CampusColors.kt cuando se unifique con el resto de vistas admin.
internal object GaleriaColores  {
    val Fondo = Color(0xFF0A0A1E)
    val Tarjeta = Color(0xFF12122B)
    val Placeholder = Color(0xFF1C1C3C)
    val Borde = Color(0xFF3D2F8F)
    val Primario = Color(0xFF7C4DFF)
    val Acento = Color(0xFFB39DFF)
    val Texto = Color.White
    val TextoSuave = Color(0xFFB4B4CC)
    val Verde = Color(0xFF2ECC71)
    val Azul = Color(0xFF29B6F6)
    val Rojo = Color(0xFFFF5252)
}

private enum class DialogoGaleria { ELIMINAR, REASIGNAR }

/** Acciones que la pantalla delega al ViewModel / navegación. Con valores por defecto para los previews. */
data class GaleriaAcciones(
    val onVolver: () -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onBuscar: (String) -> Unit = {},
    val onLugar: (String?) -> Unit = {},
    val onVideo: (String?) -> Unit = {},
    val onEstado: (EstadoFoto?) -> Unit = {},
    val onCalidad: (CalidadFoto?) -> Unit = {},
    val onLimpiarFiltros: () -> Unit = {},
    val onModo: (ModoVista) -> Unit = {},
    val onPagina: (Int) -> Unit = {},
    val onAbrirFoto: (Foto) -> Unit = {},
    val onAlternarSeleccion: (String) -> Unit = {},
    val onEliminar: () -> Unit = {},
    val onReasignar: (String) -> Unit = {},
)

/** Pantalla conectada al ViewModel (la que usa el NavHost). */
@Composable
fun GaleriaScreen(
    onVolver: () -> Unit,
    onAbrirImagen: (videoId: String, fotoId: String) -> Unit,
    viewModel: GaleriaViewModel = viewModel(
        factory = GaleriaViewModel.Factory(LocalContext.current.applicationContext)
    ),
) {
    val state by viewModel.uiState.collectAsState()

    val acciones = remember(viewModel, onVolver, onAbrirImagen) {
        GaleriaAcciones(
            onVolver = onVolver,
            onReintentar = viewModel::cargar,
            onBuscar = viewModel::buscar,
            onLugar = viewModel::filtrarLugar,
            onVideo = viewModel::filtrarVideo,
            onEstado = viewModel::filtrarEstado,
            onCalidad = viewModel::filtrarCalidad,
            onLimpiarFiltros = viewModel::limpiarFiltros,
            onModo = viewModel::cambiarModo,
            onPagina = viewModel::irAPagina,
            onAbrirFoto = { onAbrirImagen(it.videoId, it.id) },
            onAlternarSeleccion = viewModel::alternarSeleccion,
            onEliminar = viewModel::eliminarSeleccion,
            onReasignar = viewModel::reasignarSeleccion,
        )
    }

    // Con selección activa, "atrás" primero cancela la selección.
    BackHandler(enabled = state.seleccion.isNotEmpty()) { viewModel.limpiarSeleccion() }

    GaleriaContent(state = state, acciones = acciones)
}

/** Contenido sin estado: recibe todo por parámetros, por eso es fácil de previsualizar. */
@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
fun GaleriaContent(
    state: GaleriaUiState,
    acciones: GaleriaAcciones,
    modifier: Modifier = Modifier,
) {
    var dialogo by remember { mutableStateOf<DialogoGaleria?>(null) }

    val filtradas = state.filtradas
    val paginaFotos = state.paginaActual
    val totalPaginas = state.totalPaginas
    val enModoSeleccion = state.seleccion.isNotEmpty()
    val miles = remember { NumberFormat.getIntegerInstance() }

    Scaffold(
        modifier = modifier,
        containerColor = GaleriaColores.Fondo,
        topBar = { BarraSuperior(onVolver = acciones.onVolver) },
        bottomBar = {
            Column(Modifier.background(GaleriaColores.Fondo)) {
                BarraSeleccion(
                    cantidad = state.seleccion.size,
                    onReasignar = { dialogo = DialogoGaleria.REASIGNAR },
                    onEliminar = { dialogo = DialogoGaleria.ELIMINAR },
                )
                if (totalPaginas > 1) {
                    Paginador(actual = state.pagina, total = totalPaginas, onPagina = acciones.onPagina)
                }
            }
        },
    ) { padding ->
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier
                .padding(padding)
                .fillMaxSize(),
        ) {
            // ── Cabecera (hace scroll junto con la cuadrícula para dejar espacio a las fotos) ──
            item(span = { GridItemSpan(maxLineSpan) }) {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                "Imágenes del dataset",
                                color = GaleriaColores.Texto,
                                fontSize = 20.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                "${miles.format(filtradas.size)} imágenes",
                                color = GaleriaColores.Acento,
                                fontSize = 16.sp,
                            )
                        }
                        Text(
                            "Página ${state.pagina} de $totalPaginas",
                            color = GaleriaColores.Acento,
                            fontSize = 14.sp,
                            modifier = Modifier
                                .border(1.dp, GaleriaColores.Borde, RoundedCornerShape(50))
                                .padding(horizontal = 14.dp, vertical = 8.dp),
                        )
                    }

                    CampoTexto(
                        valor = state.filtros.busqueda,
                        onCambio = acciones.onBuscar,
                        placeholder = "Buscar imágenes…",
                        descripcion = "Buscar imágenes por nombre, lugar o video",
                        icono = {
                            Icon(Icons.Default.Search, contentDescription = null, tint = GaleriaColores.Primario)
                        },
                        trailing = if (state.filtros.busqueda.isNotEmpty()) {
                            {
                                IconButton(onClick = { acciones.onBuscar("") }) {
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "Borrar búsqueda",
                                        tint = GaleriaColores.TextoSuave,
                                    )
                                }
                            }
                        } else null,
                    )

                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        FiltroChip(
                            etiqueta = "Lugar",
                            seleccionado = state.filtros.lugar,
                            opciones = state.lugares,
                            textoDe = { it },
                            onSeleccionar = acciones.onLugar,
                        )
                        FiltroChip(
                            etiqueta = "Video",
                            seleccionado = state.videos.firstOrNull { it.id == state.filtros.videoId },
                            opciones = state.videos,
                            textoDe = { it.nombre },
                            onSeleccionar = { video: Video? -> acciones.onVideo(video?.id) },
                        )
                        FiltroChip(
                            etiqueta = "Estado",
                            seleccionado = state.filtros.estado,
                            opciones = EstadoFoto.values().toList(),
                            textoDe = { it.etiqueta },
                            onSeleccionar = acciones.onEstado,
                        )
                        FiltroChip(
                            etiqueta = "Calidad",
                            seleccionado = state.filtros.calidad,
                            opciones = CalidadFoto.values().toList(),
                            textoDe = { it.etiqueta },
                            textoTodos = "Todas",
                            onSeleccionar = acciones.onCalidad,
                        )
                    }

                    SelectorModo(modo = state.modo, onModo = acciones.onModo)
                }
            }

            // ── Cuerpo ──
            when {
                state.cargando -> item(span = { GridItemSpan(maxLineSpan) }) {
                    Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = GaleriaColores.Primario)
                    }
                }

                state.error != null -> item(span = { GridItemSpan(maxLineSpan) }) {
                    MensajeVacio(
                        texto = state.error,
                        accion = "Reintentar",
                        onAccion = acciones.onReintentar,
                    )
                }

                state.modo == ModoVista.MAPA -> item(span = { GridItemSpan(maxLineSpan) }) {
                    // TODO: dibujar las fotos filtradas en el mapa Leaflet (se resuelve junto con 7.14).
                    MensajeVacio(
                        texto = "La vista de mapa se conectará junto con el detalle de video. " +
                            "Fotos con coordenadas: ${filtradas.size}.",
                    )
                }

                filtradas.isEmpty() -> item(span = { GridItemSpan(maxLineSpan) }) {
                    MensajeVacio(
                        texto = "No hay imágenes con estos filtros.",
                        accion = if (state.filtros.hayActivos) "Limpiar filtros" else null,
                        onAccion = acciones.onLimpiarFiltros,
                    )
                }

                else -> items(items = paginaFotos, key = { it.uid }) { foto ->
                    val seleccionada = foto.uid in state.seleccion
                    TarjetaFoto(
                        foto = foto,
                        seleccionada = seleccionada,
                        enModoSeleccion = enModoSeleccion,
                        onClick = {
                            if (enModoSeleccion) acciones.onAlternarSeleccion(foto.uid)
                            else acciones.onAbrirFoto(foto)
                        },
                        onLongClick = { acciones.onAlternarSeleccion(foto.uid) },
                        onAlternar = { acciones.onAlternarSeleccion(foto.uid) },
                    )
                }
            }
        }
    }

    // ── Diálogos de acciones en lote ──
    when (dialogo) {
        DialogoGaleria.ELIMINAR -> {
            val n = state.seleccion.size
            AlertDialog(
                onDismissRequest = { dialogo = null },
                containerColor = GaleriaColores.Tarjeta,
                titleContentColor = GaleriaColores.Texto,
                textContentColor = GaleriaColores.TextoSuave,
                title = { Text(if (n == 1) "Eliminar 1 foto" else "Eliminar $n fotos") },
                text = {
                    Text(
                        "Vas a quitar ${if (n == 1) "esta foto" else "estas fotos"} del dataset y del " +
                            "sistema de ubicación. Esto no se puede deshacer."
                    )
                },
                confirmButton = {
                    TextButton(onClick = { acciones.onEliminar(); dialogo = null }) {
                        Text("Eliminar", color = GaleriaColores.Rojo)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { dialogo = null }) {
                        Text("Cancelar", color = GaleriaColores.Acento)
                    }
                },
            )
        }

        DialogoGaleria.REASIGNAR -> {
            var lugar by remember { mutableStateOf("") }
            AlertDialog(
                onDismissRequest = { dialogo = null },
                containerColor = GaleriaColores.Tarjeta,
                titleContentColor = GaleriaColores.Texto,
                textContentColor = GaleriaColores.TextoSuave,
                title = { Text("Reasignar a lugar") },
                text = {
                    // TODO: reemplazar por un selector de lugares reales (vista 7.6) cuando exista.
                    CampoTexto(
                        valor = lugar,
                        onCambio = { lugar = it },
                        placeholder = "Nombre del lugar",
                        descripcion = "Nombre del lugar al que se reasignan las fotos",
                    )
                },
                confirmButton = {
                    TextButton(
                        enabled = lugar.isNotBlank(),
                        onClick = { acciones.onReasignar(lugar); dialogo = null },
                    ) { Text("Reasignar", color = GaleriaColores.Acento) }
                },
                dismissButton = {
                    TextButton(onClick = { dialogo = null }) {
                        Text("Cancelar", color = GaleriaColores.TextoSuave)
                    }
                },
            )
        }

        null -> Unit
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Componentes
// ─────────────────────────────────────────────────────────────────────────────

@Composable
private fun BarraSuperior(onVolver: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(GaleriaColores.Fondo)
            .padding(horizontal = 4.dp, vertical = 4.dp),
    ) {
        IconButton(onClick = onVolver, modifier = Modifier.size(48.dp)) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "Volver",
                tint = GaleriaColores.Primario,
            )
        }
        Text(
            "Galería de imágenes",
            color = GaleriaColores.Texto,
            fontSize = 20.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier
                .weight(1f)
                .semantics { heading() },
        )
        // Equilibra visualmente el botón de volver para centrar el título.
        Box(Modifier.size(48.dp))
    }
}

@Composable
private fun CampoTexto(
    valor: String,
    onCambio: (String) -> Unit,
    placeholder: String,
    descripcion: String,
    modifier: Modifier = Modifier,
    icono: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    val forma = RoundedCornerShape(16.dp)
    BasicTextField(
        value = valor,
        onValueChange = onCambio,
        singleLine = true,
        textStyle = TextStyle(color = GaleriaColores.Texto, fontSize = 16.sp),
        cursorBrush = SolidColor(GaleriaColores.Primario),
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clip(forma)
            .border(1.dp, GaleriaColores.Borde, forma)
            .semantics { contentDescription = descripcion },
        decorationBox = { campo ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(start = 16.dp, end = 4.dp),
            ) {
                icono?.invoke()
                Box(
                    Modifier
                        .weight(1f)
                        .padding(horizontal = if (icono != null) 12.dp else 0.dp, vertical = 12.dp)
                ) {
                    if (valor.isEmpty()) {
                        Text(placeholder, color = GaleriaColores.TextoSuave, fontSize = 16.sp)
                    }
                    campo()
                }
                trailing?.invoke()
            }
        },
    )
}

@Composable
private fun <T> FiltroChip(
    etiqueta: String,
    seleccionado: T?,
    opciones: List<T>,
    textoDe: (T) -> String,
    onSeleccionar: (T?) -> Unit,
    textoTodos: String = "Todos",
) {
    var abierto by remember { mutableStateOf(false) }
    val forma = RoundedCornerShape(50)
    val valor = seleccionado?.let(textoDe) ?: textoTodos
    val activo = seleccionado != null

    Box {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .heightIn(min = 48.dp)
                .clip(forma)
                .background(if (activo) GaleriaColores.Primario.copy(alpha = 0.25f) else Color.Transparent)
                .border(1.dp, if (activo) GaleriaColores.Primario else GaleriaColores.Borde, forma)
                .clickable(role = Role.Button, onClickLabel = "Filtrar por $etiqueta") { abierto = true }
                .padding(start = 16.dp, end = 8.dp),
        ) {
            Text("$etiqueta: $valor", color = GaleriaColores.Texto, fontSize = 14.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 180.dp))
            Icon(Icons.Default.ArrowDropDown, contentDescription = null, tint = GaleriaColores.Acento)
        }
        DropdownMenu(
            expanded = abierto,
            onDismissRequest = { abierto = false },
            containerColor = GaleriaColores.Tarjeta,
        ) {
            DropdownMenuItem(
                text = { Text(textoTodos, color = GaleriaColores.Texto) },
                onClick = { onSeleccionar(null); abierto = false },
            )
            opciones.forEach { opcion ->
                DropdownMenuItem(
                    text = { Text(textoDe(opcion), color = GaleriaColores.Texto) },
                    onClick = { onSeleccionar(opcion); abierto = false },
                )
            }
        }
    }
}

@Composable
private fun SelectorModo(modo: ModoVista, onModo: (ModoVista) -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(forma)
            .border(1.dp, GaleriaColores.Borde, forma)
    ) {
        listOf(ModoVista.CUADRICULA to "Cuadrícula", ModoVista.MAPA to "Mapa").forEach { (valor, texto) ->
            val activo = modo == valor
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 48.dp)
                    .background(if (activo) GaleriaColores.Primario else Color.Transparent)
                    .clickable(role = Role.Tab) { onModo(valor) }
                    .semantics { selected = activo },
            ) {
                Text(
                    texto,
                    color = if (activo) Color.White else GaleriaColores.Acento,
                    fontSize = 16.sp,
                    fontWeight = if (activo) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TarjetaFoto(
    foto: Foto,
    seleccionada: Boolean,
    enModoSeleccion: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onAlternar: () -> Unit,
) {
    val forma = RoundedCornerShape(16.dp)
    val descripcion = buildString {
        append("Foto ${foto.nombreArchivo}, video ${foto.videoNombre}")
        foto.lugar?.let { append(", lugar $it") }
        append(", ${foto.estado.etiqueta}")
        if (foto.calidad == CalidadFoto.ALTA) append(", alta calidad")
        if (seleccionada) append(", seleccionada")
    }

    Column(
        Modifier
            .clip(forma)
            .background(GaleriaColores.Tarjeta)
            .border(if (seleccionada) 2.dp else 1.dp, if (seleccionada) GaleriaColores.Primario else GaleriaColores.Borde, forma)
            .combinedClickable(
                onClickLabel = if (enModoSeleccion) "Alternar selección" else "Abrir detalle",
                onClick = onClick,
                onLongClickLabel = "Seleccionar",
                onLongClick = onLongClick,
            )
            .semantics(mergeDescendants = true) { contentDescription = descripcion }
            .padding(8.dp)
    ) {
        Box {
            AsyncImage(
                model = foto.urlMiniatura,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(4f / 3f)
                    .clip(RoundedCornerShape(12.dp))
                    .background(GaleriaColores.Placeholder),
            )
            CirculoSeleccion(
                seleccionada = seleccionada,
                onClick = onAlternar,
                modifier = Modifier.align(Alignment.TopEnd),
            )
        }

        Text(
            foto.nombreArchivo,
            color = GaleriaColores.Texto,
            fontSize = 16.sp,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 8.dp),
        )
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
            Icon(
                Icons.Default.Place,
                contentDescription = null,
                tint = GaleriaColores.Acento,
                modifier = Modifier.size(14.dp),
            )
            Text(
                foto.lugar ?: "Sin lugar",
                color = GaleriaColores.TextoSuave,
                fontSize = 13.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 4.dp),
            )
        }
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(10.dp)
                        .background(foto.estado.color(), CircleShape)
                )
                Text(
                    foto.estado.etiqueta,
                    color = if (foto.estado == EstadoFoto.ERROR) GaleriaColores.Rojo else GaleriaColores.TextoSuave,
                    fontSize = 13.sp,
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
            when (foto.calidad) {
                CalidadFoto.ALTA -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Default.Star, contentDescription = null, tint = GaleriaColores.Acento,
                        modifier = Modifier.size(14.dp))
                    Text("Alta calidad", color = GaleriaColores.Acento, fontSize = 12.sp,
                        modifier = Modifier.padding(start = 3.dp))
                }
                CalidadFoto.BAJA -> Text("Baja calidad", color = GaleriaColores.TextoSuave, fontSize = 12.sp)
                CalidadFoto.NORMAL -> Unit
            }
        }
    }
}

private fun EstadoFoto.color(): Color = when (this) {
    EstadoFoto.SUBIDA -> GaleriaColores.Azul
    EstadoFoto.PROCESADA -> GaleriaColores.Verde
    EstadoFoto.ERROR -> GaleriaColores.Rojo
}

@Composable
private fun CirculoSeleccion(seleccionada: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    // Área táctil de 48 dp; el círculo visible es de 26 dp. Para TalkBack la selección se hace con
    // pulsación larga sobre la tarjeta, por eso este control se oculta de la accesibilidad.
    Box(
        contentAlignment = Alignment.Center,
        modifier = modifier
            .size(48.dp)
            .clickable(onClick = onClick)
            .clearAndSetSemantics { },
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .size(26.dp)
                .background(
                    if (seleccionada) GaleriaColores.Primario else Color.Black.copy(alpha = 0.35f),
                    CircleShape,
                )
                .border(2.dp, Color.White.copy(alpha = 0.9f), CircleShape),
        ) {
            if (seleccionada) {
                Icon(Icons.Default.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
            }
        }
    }
}

@Composable
private fun BarraSeleccion(cantidad: Int, onReasignar: () -> Unit, onEliminar: () -> Unit) {
    val forma = RoundedCornerShape(16.dp)
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .clip(forma)
            .border(1.dp, GaleriaColores.Borde, forma)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Text(
            if (cantidad == 1) "1 seleccionada" else "$cantidad seleccionadas",
            color = GaleriaColores.Texto,
            fontSize = 16.sp,
            modifier = Modifier
                .weight(1f)
                .semantics { contentDescription = "$cantidad fotos seleccionadas" },
        )
        BotonLote("Reasignar", Icons.Default.Edit, GaleriaColores.Acento, cantidad > 0, onReasignar)
        BotonLote("Eliminar", Icons.Default.Delete, GaleriaColores.Rojo, cantidad > 0, onEliminar,
            modifier = Modifier.padding(start = 8.dp))
    }
}

@Composable
private fun BotonLote(
    texto: String,
    icono: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color,
    habilitado: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = habilitado,
        modifier = modifier.heightIn(min = 48.dp),
        shape = RoundedCornerShape(12.dp),
        border = androidx.compose.foundation.BorderStroke(
            1.dp, if (habilitado) color.copy(alpha = 0.7f) else GaleriaColores.Borde.copy(alpha = 0.5f)
        ),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = color,
            disabledContentColor = GaleriaColores.TextoSuave.copy(alpha = 0.5f),
        ),
    ) {
        Icon(icono, contentDescription = null, modifier = Modifier.size(18.dp))
        Text(texto, fontSize = 14.sp, modifier = Modifier.padding(start = 6.dp))
    }
}

@Composable
private fun Paginador(actual: Int, total: Int, onPagina: (Int) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 8.dp),
    ) {
        IconButton(onClick = { onPagina(actual - 1) }, enabled = actual > 1) {
            Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = "Página anterior",
                tint = if (actual > 1) GaleriaColores.Primario else GaleriaColores.Borde,
            )
        }
        paginasVisibles(actual, total).forEach { pagina ->
            if (pagina == null) {
                Text("…", color = GaleriaColores.TextoSuave, modifier = Modifier.padding(horizontal = 8.dp))
            } else {
                val activa = pagina == actual
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(48.dp)
                        .clip(CircleShape)
                        .clickable(role = Role.Button, onClickLabel = "Ir a la página $pagina") { onPagina(pagina) }
                        .semantics { selected = activa },
                ) {
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .size(36.dp)
                            .background(if (activa) GaleriaColores.Primario else Color.Transparent, CircleShape),
                    ) {
                        Text(
                            "$pagina",
                            color = if (activa) Color.White else GaleriaColores.Texto,
                            fontSize = 16.sp,
                        )
                    }
                }
            }
        }
        IconButton(onClick = { onPagina(actual + 1) }, enabled = actual < total) {
            Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = "Página siguiente",
                tint = if (actual < total) GaleriaColores.Primario else GaleriaColores.Borde,
            )
        }
    }
}

/** Páginas a mostrar; `null` representa los puntos suspensivos. Ej.: 1 2 3 … 8 */
private fun paginasVisibles(actual: Int, total: Int): List<Int?> {
    if (total <= 5) return (1..total).toList()
    val mostrar = listOf(1, total, actual - 1, actual, actual + 1)
        .filter { it in 1..total }
        .distinct()
        .sorted()
    val resultado = mutableListOf<Int?>()
    var anterior = 0
    for (p in mostrar) {
        if (p - anterior > 1) resultado.add(null)
        resultado.add(p)
        anterior = p
    }
    return resultado
}

@Composable
private fun MensajeVacio(texto: String, accion: String? = null, onAccion: () -> Unit = {}) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 32.dp, horizontal = 8.dp),
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

// ─────────────────────────────────────────────────────────────────────────────
// Previews
// ─────────────────────────────────────────────────────────────────────────────

private fun fotoDePrueba(n: Int, lugar: String?, estado: EstadoFoto, calidad: CalidadFoto) = Foto(
    id = "%04d".format(n),
    videoId = "vid_0001",
    videoNombre = "video1",
    urlFoto = "file:///android_asset/videos/vid_0001/photos/%04d.png".format(n),
    urlMiniatura = "",
    lat = 6.2017, lng = -75.5788,
    lugar = lugar, estado = estado, calidad = calidad,
)

@Preview(showBackground = true, backgroundColor = 0xFF0A0A1E, heightDp = 900, widthDp = 380)
@Composable
private fun GaleriaPreview() {
    val fotos = listOf(
        fotoDePrueba(1, "Biblioteca Central", EstadoFoto.PROCESADA, CalidadFoto.ALTA),
        fotoDePrueba(2, "Bloque 3", EstadoFoto.SUBIDA, CalidadFoto.NORMAL),
        fotoDePrueba(3, null, EstadoFoto.ERROR, CalidadFoto.BAJA),
        fotoDePrueba(4, "Plazoleta", EstadoFoto.PROCESADA, CalidadFoto.NORMAL),
    )
    GaleriaContent(
        state = GaleriaUiState(
            cargando = false,
            videos = listOf(Video("vid_0001", "video1", fotos = fotos)),
            todas = fotos,
            seleccion = setOf(fotos[0].uid),
        ),
        acciones = GaleriaAcciones(),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF0A0A1E, heightDp = 600, widthDp = 380)
@Composable
private fun GaleriaCargandoPreview() {
    GaleriaContent(state = GaleriaUiState(cargando = true), acciones = GaleriaAcciones())
}