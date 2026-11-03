package com.example.myapplication.ui.admin.recoleccion

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Route
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.ui.admin.recoleccion.componentes.ColorAviso
import com.example.myapplication.ui.admin.recoleccion.componentes.ColorFinalizar
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaContent
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaControl
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaEventos
import com.example.myapplication.ui.admin.recoleccion.componentes.TarjetaContador
import com.example.myapplication.ui.admin.recoleccion.componentes.formatearDistancia
import com.example.myapplication.ui.admin.recoleccion.componentes.formatearDuracion
import com.example.myapplication.ui.admin.recoleccion.componentes.rememberRecoleccionMapaControl
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import java.io.File

/**
 * Vista 7.5 — Resumen de video (FE-2.1). Conecta [ResumenVideoViewModel] con el ciclo de vida y la navegación; **no
 * navega**: avisa con [onIrAlPanel] (la ruta decide). Atrás = «Guardar y subir después» (o solo salir si ya se envió).
 *
 * @param videoId `rec_NNNN` (argumento `video` de la ruta) o `null` (el de `SesionDeRecoleccion.resumen`).
 */
@Composable
fun ResumenVideoScreen(
    videoId: String?,
    onIrAlPanel: () -> Unit,
    modifier: Modifier = Modifier,
    vm: ResumenVideoViewModel = viewModel(key = "resumen-${videoId ?: "actual"}", factory = ResumenVideoViewModel.Factory(videoId)),
) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    val control = rememberRecoleccionMapaControl()
    val ciclo = LocalLifecycleOwner.current

    LaunchedEffect(vm) {
        vm.eventos.collect { evento ->
            when (evento) {
                ResumenVideoEvento.IrAlPanel -> onIrAlPanel()
            }
        }
    }
    DisposableEffect(ciclo, vm) {
        val observador = LifecycleEventObserver { _, evento ->
            when (evento) {
                Lifecycle.Event.ON_RESUME -> vm.alReanudar()
                Lifecycle.Event.ON_PAUSE -> vm.alPausar()
                else -> Unit
            }
        }
        ciclo.lifecycle.addObserver(observador)
        onDispose { ciclo.lifecycle.removeObserver(observador) }
    }
    BackHandler(onBack = vm::alVolver)

    ResumenVideoContent(
        ui = ui,
        acciones = ResumenVideoAcciones(
            onVolver = vm::alVolver,
            onNombre = vm::alCambiarNombre,
            onAbrirFoto = vm::alAbrirFoto,
            onCerrarFoto = vm::alCerrarFoto,
            onDescartarFoto = vm::alDescartarFoto,
            onSubir = vm::alSubir,
            onGuardarDespues = vm::alGuardarParaDespues,
            onPedirDescartar = vm::alPedirDescartar,
            onConfirmarDescartar = vm::alConfirmarDescartar,
            onCancelarDescartar = vm::alCancelarDescartar,
            onDescartarAviso = vm::alDescartarAviso,
            onIniciarSesion = vm::alIniciarSesion,
        ),
        control = control,
        modifier = modifier,
    )
}

/** Solo dibuja (patrón 5.1). [control] es el del mapa embebido (`RecoleccionMapaContent`). */
@Composable
fun ResumenVideoContent(
    ui: ResumenVideoUiState,
    acciones: ResumenVideoAcciones,
    control: RecoleccionMapaControl?,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CampusColors.Fondo)
            .systemBarsPadding()
            .imePadding(),
    ) {
        Encabezado(ui, acciones.onVolver)
        when {
            ui.cargando -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = CampusColors.Acento)
            }
            ui.noEncontrado -> SinRecorrido(acciones.onVolver)
            else -> Cuerpo(ui, acciones, control)
        }
    }

    ui.fotoAbierta?.let { id ->
        ui.fotos.firstOrNull { it.id == id }?.let { foto ->
            DialogoFoto(foto, ui.editable, onCerrar = acciones.onCerrarFoto, onDescartar = { acciones.onDescartarFoto(foto.id) })
        }
    }
    if (ui.confirmandoDescartar) {
        AlertDialog(
            onDismissRequest = acciones.onCancelarDescartar,
            title = { Text("¿Descartar «${ui.nombreGuardado}»?") },
            text = { Text("Se borrarán del teléfono sus ${ui.fotos.size} fotos. No se puede deshacer.") },
            confirmButton = {
                TextButton(onClick = acciones.onConfirmarDescartar, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("Descartar video", color = ColorFinalizar)
                }
            },
            dismissButton = {
                TextButton(onClick = acciones.onCancelarDescartar, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("Cancelar")
                }
            },
        )
    }
}

@Composable
private fun Encabezado(ui: ResumenVideoUiState, onVolver: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BotonIcono(Icons.AutoMirrored.Filled.ArrowBack, "Volver al panel", onVolver)
        Column(Modifier.weight(1f).padding(start = 4.dp)) {
            Text(
                "Resumen del video", color = CampusColors.TextoPrincipal, fontSize = 20.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            if (ui.videoId != null) Text(ui.videoId, color = CampusColors.TextoSuave, fontSize = 13.sp)
        }
        if (!ui.cargando && !ui.noEncontrado) ChipSubida(ui)
    }
}

@Composable
private fun ChipSubida(ui: ResumenVideoUiState) {
    val (texto, color) = when {
        ui.terminado -> "Procesado" to CampusColors.Exito
        ui.estadoSubida == EstadoSubida.COMPLETADA -> "Subido" to CampusColors.Exito
        ui.subida.activa -> "Subiendo" to CampusColors.Acento
        ui.estadoSubida == EstadoSubida.SUBIENDO -> "Subida a medias" to ColorAviso
        else -> "Sin subir" to CampusColors.TextoSuave
    }
    Text(
        texto, color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(color.copy(alpha = .14f))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
private fun Cuerpo(ui: ResumenVideoUiState, acciones: ResumenVideoAcciones, control: RecoleccionMapaControl?) {
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        ui.aviso?.let { aviso ->
            Text(
                aviso, color = CampusColors.TextoPrincipal, fontSize = 15.sp,
                modifier = Modifier.fillMaxWidth().tarjeta(14.dp).clickable(onClickLabel = "Descartar aviso", onClick = acciones.onDescartarAviso)
                    .semantics { liveRegion = LiveRegionMode.Polite }.padding(12.dp),
            )
        }

        // Nombre (editable mientras el backend no conoce el video)
        OutlinedTextField(
            value = ui.nombre,
            onValueChange = acciones.onNombre,
            enabled = ui.editable,
            singleLine = true,
            label = { Text("Nombre del video") },
            supportingText = {
                Text(
                    if (ui.editable) "${ui.nombre.length}/40. Se envía al servidor al subir."
                    else "El nombre ya se envió al servidor; se cambia desde Videos (FE-4.1).",
                )
            },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = CampusColors.TextoPrincipal, unfocusedTextColor = CampusColors.TextoPrincipal,
                disabledTextColor = CampusColors.TextoSuave, focusedBorderColor = CampusColors.Acento,
                unfocusedBorderColor = CampusColors.Borde, focusedLabelColor = CampusColors.Acento,
                unfocusedLabelColor = CampusColors.TextoSuave,
            ),
            modifier = Modifier.fillMaxWidth(),
        )

        // Estadísticas
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TarjetaContador(Icons.Filled.Timer, "Duración", formatearDuracion(ui.duracionSegundos), Modifier.weight(1f))
            TarjetaContador(Icons.Filled.Route, "Distancia", formatearDistancia(ui.distanciaMetros), Modifier.weight(1f))
            TarjetaContador(Icons.Filled.PhotoCamera, "Fotos", ui.fotos.size.toString(), Modifier.weight(1f))
        }

        // Trayectoria y cobertura
        Box(Modifier.fillMaxWidth().height(260.dp).tarjeta(18.dp)) {
            if (control == null || LocalInspectionMode.current) {
                Text("Mapa (vista previa)", color = CampusColors.TextoSuave, modifier = Modifier.align(Alignment.Center))
            } else {
                RecoleccionMapaContent(
                    control = control, lat = null, lng = null, rumbo = 0f,
                    fotosJson = ui.fotosJson, trayectoriaJson = ui.trayectoriaJson, alertasJson = "[]",
                    reanclaje = null, eventos = RecoleccionMapaEventos(),
                    modifier = Modifier.fillMaxSize().semantics {
                        contentDescription = "Mapa con la trayectoria del recorrido y sus ${ui.fotos.size} fotos"
                    },
                )
                LaunchedEffect(control.listo, ui.fotosJson, ui.trayectoriaJson) { control.encuadrar() }
            }
        }

        Carrusel(ui, acciones.onAbrirFoto)
        PanelSubida(ui, acciones.onIniciarSesion)
        Botones(ui, acciones)
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun Carrusel(ui: ResumenVideoUiState, onAbrir: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "Fotos (${ui.fotos.size})", color = CampusColors.TextoPrincipal, fontSize = 17.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.semantics { heading() },
        )
        Text(
            if (ui.editable) "Toca una foto para verla y descartarla." else "Toca una foto para verla.",
            color = CampusColors.TextoSuave, fontSize = 13.sp,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(ui.fotos, key = { it.id }) { foto ->
                Column(
                    modifier = Modifier.width(104.dp).clip(RoundedCornerShape(12.dp))
                        .clickable(role = Role.Button, onClickLabel = "Ver foto") { onAbrir(foto.id) }
                        .semantics(mergeDescendants = true) { contentDescription = "Foto ${foto.id}, ${foto.estado.etiqueta}" },
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    AsyncImage(
                        model = File(foto.ruta), contentDescription = null, contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxWidth().aspectRatio(3f / 4f).clip(RoundedCornerShape(12.dp))
                            .background(CampusColors.SuperficieAlta),
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(9.dp).clip(CircleShape).background(colorEstado(foto.estado)))
                        Text(
                            "${foto.id} · ${foto.estado.etiqueta}", color = CampusColors.TextoSuave, fontSize = 12.sp,
                            modifier = Modifier.padding(start = 4.dp), maxLines = 1,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PanelSubida(ui: ResumenVideoUiState, onIniciarSesion: () -> Unit) {
    val total = ui.fotos.size
    val conteo = ui.conteo
    val s = ui.subida
    val titulo = when {
        ui.terminado -> "Subida y procesamiento terminados"
        s.fase == FaseCola.PREPARANDO -> "Preparando fotos: ${s.hechas} de ${s.total}"
        s.fase == FaseCola.SUBIENDO || s.fase == FaseCola.COMPLETANDO -> "Subiendo: ${ui.subidas} de $total"
        s.fase == FaseCola.SIN_CONEXION -> "Sin conexión: reintento en ${s.reintentoEnS ?: 0} s"
        s.fase == FaseCola.ESPERANDO_SESION -> "Esperando sesión"
        s.fase == FaseCola.ERROR -> "La subida se detuvo"
        s.fase == FaseCola.FOTOS_ILEGIBLES -> "Hay fotos que no se pueden leer"
        ui.estadoSubida == EstadoSubida.COMPLETADA -> "Subido: procesando en el servidor (${ui.estadoRemoto ?: "consultando"})"
        ui.estadoSubida == EstadoSubida.SUBIENDO -> "Subida a medias: ${ui.subidas} de $total"
        else -> "Listo para subir: $total fotos"
    }
    val progreso = when {
        s.fase == FaseCola.PREPARANDO && s.total > 0 -> s.hechas.toFloat() / s.total
        total > 0 -> ui.subidas.toFloat() / total
        else -> 0f
    }
    Column(
        modifier = Modifier.fillMaxWidth().tarjeta(16.dp).padding(14.dp)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.CloudUpload, null, tint = CampusColors.Acento, modifier = Modifier.size(24.dp))
            Spacer(Modifier.width(10.dp))
            Text(titulo, color = CampusColors.TextoPrincipal, fontSize = 16.sp, fontWeight = FontWeight.Medium)
        }
        LinearProgressIndicator(
            progress = { progreso.coerceIn(0f, 1f) }, color = CampusColors.Acento, trackColor = CampusColors.Borde,
            modifier = Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(50)),
        )
        Text(
            "Pendientes ${conteo[EstadoFoto.PENDIENTE] ?: 0} · Subidas ${conteo[EstadoFoto.SUBIDA] ?: 0} · " +
                "Procesadas ${conteo[EstadoFoto.PROCESADA] ?: 0} · Con error ${conteo[EstadoFoto.ERROR] ?: 0}",
            color = CampusColors.TextoSuave, fontSize = 13.sp,
        )
        s.mensaje?.let { Text(it, color = if (s.fase == FaseCola.ERROR) ColorFinalizar else ColorAviso, fontSize = 14.sp) }
        if (s.fase == FaseCola.ESPERANDO_SESION) {
            OutlinedButton(onClick = onIniciarSesion, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                Text("Iniciar sesión", color = CampusColors.TextoPrincipal)
            }
        }
    }
}

@Composable
private fun Botones(ui: ResumenVideoUiState, acciones: ResumenVideoAcciones) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (ui.estadoSubida != EstadoSubida.COMPLETADA) {
            Button(
                onClick = acciones.onSubir, enabled = ui.puedeSubir,
                modifier = Modifier.fillMaxWidth().heightIn(min = 60.dp), shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(containerColor = CampusColors.Primario, contentColor = Color.White),
            ) {
                Icon(Icons.Filled.CloudUpload, null, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(10.dp))
                Text(if (ui.estadoSubida == EstadoSubida.SUBIENDO) "Reintentar subida" else "Subir y procesar", fontSize = 17.sp)
            }
        }
        OutlinedButton(
            onClick = acciones.onGuardarDespues,
            modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp), shape = RoundedCornerShape(16.dp),
        ) {
            Text(
                if (ui.editable) "Guardar y subir después" else "Volver al panel",
                color = CampusColors.TextoPrincipal, fontSize = 16.sp,
            )
        }
        if (ui.editable) {
            TextButton(onClick = acciones.onPedirDescartar, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)) {
                Text("Descartar video", color = ColorFinalizar, fontSize = 16.sp)
            }
        }
    }
}

@Composable
private fun DialogoFoto(foto: FotoResumen, puedeDescartar: Boolean, onCerrar: () -> Unit, onDescartar: () -> Unit) {
    AlertDialog(
        onDismissRequest = onCerrar,
        title = { Text("Foto ${foto.id}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                AsyncImage(
                    model = File(foto.ruta), contentDescription = "Foto ${foto.id} del recorrido", contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxWidth().aspectRatio(3f / 4f).clip(RoundedCornerShape(12.dp))
                        .border(1.dp, CampusColors.Borde, RoundedCornerShape(12.dp)),
                )
                Text("Estado: ${foto.estado.etiqueta}${foto.error?.let { " ($it)" }.orEmpty()}")
                if (!puedeDescartar) Text("Ya se envió al servidor: no se puede descartar aquí.")
            }
        },
        confirmButton = {
            if (puedeDescartar) {
                TextButton(onClick = onDescartar, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("Descartar foto", color = ColorFinalizar)
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onCerrar, modifier = Modifier.heightIn(min = 48.dp)) { Text("Cerrar") }
        },
    )
}

@Composable
private fun SinRecorrido(onVolver: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("No hay un recorrido para revisar.", color = CampusColors.TextoPrincipal, fontSize = 18.sp)
        Spacer(Modifier.height(16.dp))
        OutlinedButton(onClick = onVolver, modifier = Modifier.heightIn(min = 56.dp)) {
            Text("Volver al panel", color = CampusColors.TextoPrincipal)
        }
    }
}

private fun colorEstado(e: EstadoFoto): Color = when (e) {
    EstadoFoto.PENDIENTE -> CampusColors.TextoSuave
    EstadoFoto.SUBIDA -> CampusColors.Acento
    EstadoFoto.PROCESADA -> CampusColors.Exito
    EstadoFoto.ERROR -> ColorFinalizar
}

// ── Previews ────────────────────────────────────────────────────────────────────────────────────

private val FOTOS_PRUEBA = (1..8).map { i ->
    FotoResumen("%04d".format(i), "/no/existe/$i.jpg", if (i <= 3) EstadoFoto.SUBIDA else EstadoFoto.PENDIENTE)
}

@Preview(showBackground = true, widthDp = 390, heightDp = 1100)
@Composable
private fun PreviewResumenSinSubir() = ResumenVideoContent(
    ResumenVideoUiState(
        cargando = false, videoId = "rec_0003", nombre = "Entrada norte", nombreGuardado = "Entrada norte",
        duracionSegundos = 512, distanciaMetros = 340.5, pasos = 470, fotos = FOTOS_PRUEBA.map { it.copy(estado = EstadoFoto.PENDIENTE) },
    ),
    ResumenVideoAcciones(), control = null,
)

@Preview(showBackground = true, widthDp = 390, heightDp = 1100)
@Composable
private fun PreviewResumenSubiendo() = ResumenVideoContent(
    ResumenVideoUiState(
        cargando = false, videoId = "rec_0003", nombre = "Entrada norte", nombreGuardado = "Entrada norte",
        estadoSubida = EstadoSubida.SUBIENDO, enviadoAlBackend = true, duracionSegundos = 512, distanciaMetros = 340.5,
        fotos = FOTOS_PRUEBA, subida = SubidaUi(FaseCola.SIN_CONEXION, 3, 8, "Sin conexión con el backend", 20),
    ),
    ResumenVideoAcciones(), control = null,
)
