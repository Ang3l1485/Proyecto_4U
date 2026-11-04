package com.example.myapplication.ui.admin.panel

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Place
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.VerifiedUser
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.foundation.BorderStroke
import com.example.myapplication.domain.model.ResumenAdmin
import com.example.myapplication.ui.theme.CampusColors as C

/** Callbacks de navegación y acciones del panel. */
data class PanelAcciones(
    val onRecolector: () -> Unit = {},
    val onLugares: () -> Unit = {},
    val onMapaAlertas: () -> Unit = {},
    val onImagenes: () -> Unit = {},
    val onVideos: () -> Unit = {},
    val onEstadisticas: () -> Unit = {},
    val onAjustes: () -> Unit = {},
    val onCerrarSesion: () -> Unit = {},
    val onVolverModoPublico: () -> Unit = {},
    val onReintentarResumen: () -> Unit = {},
    /** FE-2.1: tarjeta de subidas → vista 7.5 del recorrido. */
    val onAbrirSubida: (videoId: String) -> Unit = {},
)

/**
 * Vista 7.2 — Panel admin.
 *
 * @param onSesionCerrada se invoca tras cerrar sesión (volver al flujo público).
 * @param onSinSesion se invoca si no hay sesión ADMIN válida (ir a Login).
 */
@Composable
fun PanelAdminScreen(
    onRecolector: () -> Unit,
    onLugares: () -> Unit,
    onMapaAlertas: () -> Unit,
    onImagenes: () -> Unit,
    onVideos: () -> Unit,
    onEstadisticas: () -> Unit,
    onAjustes: () -> Unit,
    onVolverModoPublico: () -> Unit,
    onSesionCerrada: () -> Unit,
    onSinSesion: () -> Unit,
    onAbrirSubida: (videoId: String) -> Unit = {},
    viewModel: PanelAdminViewModel = viewModel(
        factory = PanelAdminViewModel.Factory(LocalContext.current.applicationContext),
    ),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                PanelEvento.SesionCerrada -> onSesionCerrada()
                PanelEvento.SinSesion -> onSinSesion()
            }
        }
    }
    // FE-2.2: al volver al Panel (p. ej. desde 7.5 con «Guardar y subir después», que regresa a esta misma entrada de
    // la pila con el mismo ViewModel), relee los recorridos locales: tarjeta de subidas y «Fotos pendientes» al día.
    val ciclo = LocalLifecycleOwner.current
    DisposableEffect(ciclo, viewModel) {
        val observador = LifecycleEventObserver { _, evento ->
            if (evento == Lifecycle.Event.ON_RESUME) viewModel.alReanudar()
        }
        ciclo.lifecycle.addObserver(observador)
        onDispose { ciclo.lifecycle.removeObserver(observador) }
    }

    PanelAdminContent(
        state = state,
        acciones = PanelAcciones(
            onRecolector = onRecolector,
            onLugares = onLugares,
            onMapaAlertas = onMapaAlertas,
            onImagenes = onImagenes,
            onVideos = onVideos,
            onEstadisticas = onEstadisticas,
            onAjustes = onAjustes,
            onCerrarSesion = viewModel::cerrarSesion,
            onVolverModoPublico = onVolverModoPublico,
            onReintentarResumen = viewModel::cargarResumen,
            onAbrirSubida = onAbrirSubida,
        ),
    )
}

@Composable
internal fun PanelAdminContent(state: PanelUiState, acciones: PanelAcciones) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(C.Fondo)
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 18.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Encabezado(state, acciones.onAjustes)
        state.avisoSubidas?.let { TarjetaSubidas(it, acciones.onAbrirSubida) }
        FilaTarjetas(
            izquierda = Acceso("Recolector de imágenes", "Captura y gestiona las imágenes del entorno.", Icons.Outlined.PhotoCamera, acciones.onRecolector, destacada = true),
            derecha = Acceso("Lugares", "Administra los lugares del campus.", Icons.Outlined.Place, acciones.onLugares),
        )
        FilaTarjetas(
            izquierda = Acceso("Mapa y alertas", "Gestiona el mapa, rutas y alertas de seguridad.", Icons.Outlined.Map, acciones.onMapaAlertas),
            derecha = Acceso("Imágenes", "Revisa y administra el dataset de imágenes.", Icons.Outlined.Image, acciones.onImagenes),
        )
        FilaTarjetas(
            izquierda = Acceso("Videos", "Gestiona los videos del sistema.", Icons.Outlined.Videocam, acciones.onVideos),
            derecha = Acceso("Estadísticas", "Consulta métricas y rendimiento del sistema.", Icons.Outlined.BarChart, acciones.onEstadisticas),
        )

        ResumenRapido(state, acciones.onReintentarResumen)

        Spacer(Modifier.height(4.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            OutlinedButton(
                onClick = acciones.onCerrarSesion,
                modifier = Modifier.weight(1f).heightIn(min = 64.dp),
                shape = RoundedCornerShape(18.dp),
                border = BorderStroke(1.5.dp, C.Peligro),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = C.Peligro),
            ) {
                Icon(Icons.AutoMirrored.Outlined.Logout, contentDescription = null, modifier = Modifier.size(26.dp))
                Spacer(Modifier.width(10.dp))
                Text("Cerrar sesión", fontSize = 16.sp, fontWeight = FontWeight.Medium)
            }
            Button(
                onClick = acciones.onVolverModoPublico,
                modifier = Modifier.weight(1f).heightIn(min = 64.dp),
                shape = RoundedCornerShape(18.dp),
                border = BorderStroke(1.dp, C.Borde),
                colors = ButtonDefaults.buttonColors(containerColor = C.SuperficieAlta, contentColor = Color.White),
            ) {
                Icon(Icons.Outlined.Person, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
                Spacer(Modifier.width(10.dp))
                Text("Volver a modo público", fontSize = 16.sp, fontWeight = FontWeight.Medium, lineHeight = 22.sp)
            }
        }

        Pie()
    }
}

// ───────────────────────────── Encabezado ─────────────────────────────

@Composable
private fun Encabezado(state: PanelUiState, onAjustes: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(68.dp)
                .clip(CircleShape)
                .background(Color(0xFF0C1340))
                .border(2.dp, C.Borde, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.Person, contentDescription = null, tint = C.Acento, modifier = Modifier.size(38.dp))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = if (state.nombre.isNotBlank()) "Hola, ${state.nombre}" else "Hola",
                color = C.TextoPrincipal,
                fontSize = 24.sp,
                lineHeight = 30.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Row(verticalAlignment = Alignment.Top) {
                Icon(
                    Icons.Outlined.VerifiedUser,
                    contentDescription = null,
                    tint = C.Acento,
                    modifier = Modifier.padding(top = 2.dp).size(18.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(state.rolTexto, color = C.TextoSecundario, fontSize = 15.sp, lineHeight = 20.sp)
            }
        }
        IconButton(onClick = onAjustes, modifier = Modifier.size(56.dp)) {
            Icon(Icons.Outlined.Settings, contentDescription = "Ajustes", tint = C.Acento, modifier = Modifier.size(28.dp))
        }
    }
}

// ───────────────────────────── Subidas (FE-2.1) ─────────────────────────────

@Composable
private fun TarjetaSubidas(aviso: AvisoSubidas, onAbrir: (String) -> Unit) {
    val forma = RoundedCornerShape(18.dp)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(forma)
            .background(C.Superficie)
            .border(1.5.dp, C.Acento, forma)
            .clickable(role = Role.Button, onClickLabel = aviso.accion) { onAbrir(aviso.videoId) }
            .semantics(mergeDescendants = true) {
                contentDescription = "${aviso.titulo}. ${aviso.detalle}. ${aviso.accion}"
                liveRegion = LiveRegionMode.Polite
            }
            .heightIn(min = 64.dp)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.CloudUpload, contentDescription = null, tint = C.Acento, modifier = Modifier.size(28.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(aviso.titulo, color = C.TextoPrincipal, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 21.sp)
            Text(aviso.detalle, color = C.TextoSuave, fontSize = 14.sp, lineHeight = 19.sp)
        }
        Spacer(Modifier.width(8.dp))
        Text(aviso.accion, color = C.Acento, fontSize = 14.sp, fontWeight = FontWeight.Medium)
    }
}

// ───────────────────────────── Tarjetas de acceso ─────────────────────────────

private data class Acceso(
    val titulo: String,
    val descripcion: String,
    val icono: ImageVector,
    val onClick: () -> Unit,
    val destacada: Boolean = false,
)

@Composable
private fun FilaTarjetas(izquierda: Acceso, derecha: Acceso) {
    Row(
        modifier = Modifier.height(IntrinsicSize.Max),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        TarjetaAcceso(izquierda, Modifier.weight(1f).fillMaxHeight())
        TarjetaAcceso(derecha, Modifier.weight(1f).fillMaxHeight())
    }
}

@Composable
private fun TarjetaAcceso(acceso: Acceso, modifier: Modifier = Modifier) {
    val forma = RoundedCornerShape(20.dp)
    val destacada = acceso.destacada

    Column(
        modifier = modifier
            .heightIn(min = 128.dp)
            .then(
                if (destacada) Modifier.shadow(16.dp, forma, ambientColor = C.Acento, spotColor = C.Acento)
                else Modifier
            )
            .clip(forma)
            .then(
                if (destacada) Modifier.background(Brush.linearGradient(listOf(Color(0xFF3F24C4), Color(0xFF241470))))
                else Modifier.background(C.Superficie)
            )
            .border(if (destacada) 2.dp else 1.dp, if (destacada) C.Acento else C.Borde, forma)
            .clickable(role = Role.Button, onClick = acceso.onClick)
            .semantics(mergeDescendants = true) { contentDescription = "${acceso.titulo}. ${acceso.descripcion}" }
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Ícono a la izquierda y chevron a la derecha: así el texto usa todo el ancho de la tarjeta.
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Box(
                modifier = Modifier
                    .size(46.dp)
                    .clip(CircleShape)
                    .background(Color(0xFF0C1340).copy(alpha = if (destacada) 0.5f else 1f))
                    .border(1.5.dp, if (destacada) C.Acento else C.Borde, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(acceso.icono, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
            }
            Icon(
                Icons.AutoMirrored.Outlined.KeyboardArrowRight,
                contentDescription = null,
                tint = C.Acento,
                modifier = Modifier.size(26.dp),
            )
        }
        Text(acceso.titulo, color = C.TextoPrincipal, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp)
        Text(acceso.descripcion, color = C.TextoSuave, fontSize = 14.sp, lineHeight = 19.sp)
    }
}

// ───────────────────────────── Resumen rápido ─────────────────────────────

private data class Dato(val icono: ImageVector, val valor: String, val etiqueta: String, val detalle: String? = null)

@Composable
private fun ResumenRapido(state: PanelUiState, onReintentar: () -> Unit) {
    val forma = RoundedCornerShape(22.dp)
    val r = state.resumen

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(forma)
            .background(C.Superficie)
            .border(1.dp, C.Borde, forma)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(44.dp).clip(CircleShape).background(Color(0xFF0C1340)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Outlined.BarChart, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
            }
            Spacer(Modifier.width(14.dp))
            Text(
                "Resumen rápido",
                color = C.TextoPrincipal,
                fontSize = 20.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.weight(1f).semantics { heading() },
            )
            if (r != null) ChipTiempoReal()
        }

        if (state.errorResumen) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("No se pudo cargar el resumen.", color = C.TextoSuave, fontSize = 16.sp, modifier = Modifier.weight(1f))
                TextButton(onClick = onReintentar, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("Reintentar", color = C.Acento, fontSize = 16.sp)
                }
            }
        }

        val datos = listOf(
            Dato(Icons.Outlined.PhotoCamera, TextosResumen.numero(r?.totalFotos), "Fotos en el dataset"),
            Dato(Icons.Outlined.Place, TextosResumen.numero(r?.totalLugares), "Lugares registrados"),
            Dato(Icons.Outlined.WarningAmber, TextosResumen.numero(r?.alertasActivas), "Alertas activas"),
            Dato(
                Icons.Outlined.Videocam,
                TextosResumen.numero(r?.ultimoVideoNumero),
                "Último video recolectado",
                r?.ultimoVideoFecha?.let { TextosResumen.fecha(it) },
            ),
            Dato(Icons.Outlined.CloudUpload, TextosResumen.numero(r?.fotosPendientes), "Fotos pendientes de subir"),
        )
        Row(
            modifier = Modifier.height(IntrinsicSize.Max),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            datos.forEach { TileDato(it, Modifier.weight(1f).fillMaxHeight()) }
        }
    }
}

@Composable
private fun TileDato(dato: Dato, modifier: Modifier = Modifier) {
    val forma = RoundedCornerShape(14.dp)
    Column(
        modifier = modifier
            .clip(forma)
            .border(1.dp, C.Borde, forma)
            .semantics(mergeDescendants = true) {
                contentDescription = "${dato.valor} ${dato.etiqueta.lowercase()}" + (dato.detalle?.let { ". $it" } ?: "")
            }
            .padding(horizontal = 4.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(dato.icono, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
        Text(dato.valor, color = C.TextoPrincipal, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        Text(dato.etiqueta, color = C.TextoSuave, fontSize = 11.sp, lineHeight = 14.sp, textAlign = TextAlign.Center)
        dato.detalle?.let {
            Text(it, color = C.TextoSuave, fontSize = 11.sp, lineHeight = 14.sp, textAlign = TextAlign.Center)
        }
    }
}

@Composable
private fun ChipTiempoReal() {
    val forma = RoundedCornerShape(50)
    Row(
        modifier = Modifier
            .clip(forma)
            .background(C.Exito.copy(alpha = 0.10f))
            .border(1.dp, C.Exito.copy(alpha = 0.45f), forma)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(10.dp).clip(CircleShape).background(C.Exito))
        Spacer(Modifier.width(8.dp))
        Text("En tiempo real", color = C.Exito, fontSize = 13.sp)
    }
}

// ───────────────────────────── Pie ─────────────────────────────

@Composable
private fun Pie() {
    val context = LocalContext.current
    val version = remember(context) {
        runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }
            .getOrNull() ?: "—"
    }
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.VerifiedUser, contentDescription = null, tint = C.Acento, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("Panel de administración · Campus Navi", color = C.TextoSuave, fontSize = 14.sp)
        }
        Text("Versión $version", color = C.TextoSuave, fontSize = 14.sp)
    }
}

// ───────────────────────────── Previews ─────────────────────────────

@Preview(showBackground = true, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewPanel() = PanelAdminContent(
    PanelUiState(
        nombre = "Alejandro",
        rolTexto = "Administrador del sistema",
        cargandoResumen = false,
        resumen = ResumenAdmin(2842, 48, 3, 12, System.currentTimeMillis(), 27),
    ),
    PanelAcciones(),
)

@Preview(showBackground = true, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewPanelSubiendo() = PanelAdminContent(
    PanelUiState(
        nombre = "Alejandro",
        rolTexto = "Administrador del sistema",
        cargandoResumen = false,
        resumen = ResumenAdmin(2842, 48, 3, 12, System.currentTimeMillis(), 27),
        avisoSubidas = AvisoSubidas("rec_0003", "Subiendo «Entrada norte»", "34 de 80 fotos", "Ver"),
    ),
    PanelAcciones(),
)

@Preview(showBackground = true, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewPanelCargando() = PanelAdminContent(
    PanelUiState(nombre = "Alejandro", rolTexto = "Administrador del sistema"),
    PanelAcciones(),
)

@Preview(showBackground = true, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewPanelError() = PanelAdminContent(
    PanelUiState(nombre = "Alejandro", rolTexto = "Administrador del sistema", cargandoResumen = false, errorResumen = true),
    PanelAcciones(),
)