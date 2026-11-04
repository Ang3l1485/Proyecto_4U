package com.example.myapplication.ui.admin.recoleccion

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.DirectionsWalk
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Videocam
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.camera.crearImageCapture
import com.example.myapplication.camera.liberarCamara
import com.example.myapplication.camera.tomarFoto
import com.example.myapplication.domain.model.ResumenRecoleccion
import com.example.myapplication.domain.usecase.ModoCaptura
import com.example.myapplication.ui.admin.mapa.AlertaFormSheet
import com.example.myapplication.ui.admin.recoleccion.componentes.BotonAccion
import com.example.myapplication.ui.admin.recoleccion.componentes.BotonFinalizar
import com.example.myapplication.ui.admin.recoleccion.componentes.ChipEstadoVideo
import com.example.myapplication.ui.admin.recoleccion.componentes.ColorAviso
import com.example.myapplication.ui.admin.recoleccion.componentes.FilaAccion
import com.example.myapplication.ui.admin.recoleccion.componentes.FilaAlertasCercanas
import com.example.myapplication.ui.admin.recoleccion.componentes.PanelAvisos
import com.example.myapplication.ui.admin.recoleccion.componentes.PanelReanclaje
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaContent
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaControl
import com.example.myapplication.ui.admin.recoleccion.componentes.RecoleccionMapaEventos
import com.example.myapplication.ui.admin.recoleccion.componentes.TarjetaCalidad
import com.example.myapplication.ui.admin.recoleccion.componentes.TarjetaCaptura
import com.example.myapplication.ui.admin.recoleccion.componentes.TarjetaContador
import com.example.myapplication.ui.admin.recoleccion.componentes.formatearDistancia
import com.example.myapplication.ui.admin.recoleccion.componentes.formatearDuracion
import com.example.myapplication.ui.admin.recoleccion.componentes.rememberRecoleccionMapaControl
import com.example.myapplication.ui.ubicacion.componentes.VistaCamara
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.theme.CampusColors
import kotlinx.coroutines.delay

/**
 * Vista 7.4 · Recolección en curso (ARCHITECTURE 7.4). Diseño: `assets/recoleccion_en_curso.png`.
 *
 * La pantalla es dueña de CameraX; el ViewModel, del PDR (6b). **No navega**: avisa por lambdas.
 * Permisos de cámara y actividad física: se piden en la **ruta** (`PedirPermisos(Permisos.INICIALES)`).
 */
@Composable
fun RecoleccionScreen(
    onFinalizado: (ResumenRecoleccion) -> Unit,
    onDescartado: () -> Unit,
    onVolver: () -> Unit,
    onAjustes: () -> Unit = {},
    modifier: Modifier = Modifier,
    vm: RecoleccionViewModel = viewModel(),
) {
    val ui by vm.ui.collectAsState()
    val ctx = LocalContext.current
    val vista = LocalView.current
    val ciclo = LocalLifecycleOwner.current

    val imageCapture = remember { crearImageCapture() }
    val tieneCamara = remember {
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    }
    val control = rememberRecoleccionMapaControl()
    var siguiendo by remember { mutableStateOf(true) }
    var eligiendoIntervalo by remember { mutableStateOf(false) }
    var fotoTomadaVisible by remember { mutableStateOf(false) }
    val destello = remember { Animatable(0f) }

    val eventosMapa = remember(vm) {
        RecoleccionMapaEventos(onPuntoReanclaje = vm::alMoverReanclaje, onSeguimiento = { siguiendo = it })
    }

    // Atrás (sistema y flecha): cierra el re-anclaje, o pide confirmar la finalización (6b).
    val atras: () -> Unit = {
        when {
            ui.error != null -> onVolver()
            ui.reanclaje != null -> vm.alCancelarReanclaje()
            else -> vm.alPedirFinalizar()
        }
    }
    BackHandler(onBack = atras)

    LaunchedEffect(Unit) { vm.alAbrir() }

    LaunchedEffect(vm) {
        vm.eventos.collect { evento ->
            when (evento) {
                is RecoleccionEvento.Capturar -> {
                    val carpeta = vm.carpetaFotos()
                    if (carpeta == null) vm.onFotoFallida()
                    else imageCapture.tomarFoto(ctx, carpeta, "tmp", vm::onFotoTomada, vm::onFotoFallida)
                }
                is RecoleccionEvento.Finalizado -> onFinalizado(evento.resumen)
                is RecoleccionEvento.Descartado -> onDescartado()
            }
        }
    }

    // ON_STOP: pausa sola (el PDR no maneja ON_STOP por sí mismo, 11.2).
    DisposableEffect(ciclo, vm) {
        val observador = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_STOP) vm.alIrASegundoPlano() }
        ciclo.lifecycle.addObserver(observador)
        onDispose { ciclo.lifecycle.removeObserver(observador) }
    }

    // Pantalla encendida; al salir, soltar la cámara (desenlaza todo el proceso: 11.2).
    DisposableEffect(Unit) {
        vista.keepScreenOn = true
        onDispose {
            vista.keepScreenOn = false
            liberarCamara(ctx)
        }
    }

    // Destello al capturar: fogonazo blanco breve sobre el mapa y etiqueta «Foto tomada» ~1 s.
    LaunchedEffect(ui.destelloCaptura) {
        if (ui.destelloCaptura > 0) {
            fotoTomadaVisible = true
            destello.snapTo(.35f)
            destello.animateTo(0f, tween(250))
            delay(750)
            fotoTomadaVisible = false
        }
    }

    Box(modifier.fillMaxSize().background(CampusColors.Fondo)) {
        when {
            ui.error != null -> PantallaError(ui.error.toString(), onVolver)
            ui.fase == FaseRecoleccion.INICIANDO -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                CircularProgressIndicator(color = CampusColors.Acento)
            }
            else -> Contenido(
                ui = ui, vm = vm, control = control, eventosMapa = eventosMapa,
                imageCapture = imageCapture, tieneCamara = tieneCamara, siguiendo = siguiendo,
                destello = destello.value, fotoTomadaVisible = fotoTomadaVisible,
                onAtras = atras, onAjustes = onAjustes, onIntervalo = { eligiendoIntervalo = true },
            )
        }
    }

    if (eligiendoIntervalo) {
        DialogoIntervalo(
            actual = ui.modo,
            onElegir = { vm.alCambiarModo(it); eligiendoIntervalo = false },
            onCerrar = { eligiendoIntervalo = false },
        )
    }

    ui.formularioAlerta?.let { alerta ->
        AlertaFormSheet(
            alerta = alerta, esNueva = true, error = ui.errorAlerta,
            onCambio = vm::alActualizarAlerta, onGuardar = vm::alGuardarAlerta,
            onCancelar = vm::alCancelarAlerta, onEliminar = vm::alCancelarAlerta,
        )
    }

    if (ui.confirmandoFinalizar) {
        AlertDialog(
            onDismissRequest = vm::alCancelarFinalizar,
            containerColor = CampusColors.SuperficieAlta,
            title = { Text("¿Finalizar video?", color = CampusColors.TextoPrincipal) },
            text = {
                Text(
                    if (ui.fotosTomadas == 0) "No hay fotos: el video se borrará."
                    else "Se guardarán ${ui.fotosTomadas} fotos (${formatearDistancia(ui.distanciaMetros.toDouble())}, ${formatearDuracion(ui.duracionSegundos.toLong())}).",
                    color = CampusColors.TextoSuave,
                )
            },
            confirmButton = { TextButton(onClick = vm::alConfirmarFinalizar) { Text("Finalizar", color = Color(0xFFFF4D7D)) } },
            dismissButton = { TextButton(onClick = vm::alCancelarFinalizar) { Text("Seguir grabando", color = CampusColors.Acento) } },
        )
    }
}

@Composable
private fun Contenido(
    ui: RecoleccionUiState, vm: RecoleccionViewModel, control: RecoleccionMapaControl,
    eventosMapa: RecoleccionMapaEventos, imageCapture: androidx.camera.core.ImageCapture,
    tieneCamara: Boolean, siguiendo: Boolean, destello: Float, fotoTomadaVisible: Boolean,
    onAtras: () -> Unit, onAjustes: () -> Unit, onIntervalo: () -> Unit,
) {
    val enPausa = ui.fase == FaseRecoleccion.PAUSADA
    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()
            .verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Barra superior
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            BotonIcono(icono = Icons.AutoMirrored.Filled.ArrowBack, descripcion = "Volver", onClick = onAtras, tint = CampusColors.Acento)
            Column(Modifier.weight(1f).padding(horizontal = 4.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(ui.nombreVideo, color = CampusColors.TextoPrincipal, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                    ChipEstadoVideo(enPausa)
                }
                Text("Recolección de imágenes", color = CampusColors.TextoSecundario, fontSize = 14.sp)
            }
            BotonIcono(icono = Icons.Filled.Settings, descripcion = "Ajustes", onClick = onAjustes, tint = CampusColors.Acento)
        }

        // Aviso temporal del ViewModel (batería, almacenamiento, re-anclaje aplicado…)
        ui.aviso?.let { texto ->
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(ColorAviso.copy(alpha = .14f))
                    .border(1.dp, ColorAviso.copy(alpha = .5f), RoundedCornerShape(14.dp))
                    .clickable(onClickLabel = "Descartar aviso", onClick = vm::descartarAviso).padding(12.dp)
                    .semantics { liveRegion = LiveRegionMode.Polite },
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                androidx.compose.material3.Icon(Icons.Filled.Warning, null, tint = ColorAviso)
                Text(texto, color = CampusColors.TextoPrincipal, fontSize = 14.sp)
            }
        }
        if (!tieneCamara) {
            Text("Sin permiso de cámara: no se pueden tomar fotos.", color = Color(0xFFFF4D7D), fontSize = 14.sp)
        }

        // Mapa en vivo + vista previa de cámara
        TarjetaMapa(ui, control, eventosMapa, imageCapture, tieneCamara, siguiendo, destello)

        if (ui.reanclaje != null) {
            PanelReanclaje(onConfirmar = vm::alConfirmarReanclaje, onCancelar = vm::alCancelarReanclaje)
        }

        // Contadores
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TarjetaContador(Icons.Filled.CameraAlt, "Fotos tomadas", "${ui.fotosTomadas}", Modifier.weight(1f), sufijo = " / $MAX_FOTOS_VIDEO")
            TarjetaContador(Icons.Filled.LocationOn, "Distancia recorrida", formatearDistancia(ui.distanciaMetros.toDouble()), Modifier.weight(1f))
            TarjetaContador(Icons.Filled.DirectionsWalk, "Pasos", "${ui.pasos}", Modifier.weight(1f))
            TarjetaContador(Icons.Filled.Videocam, "Duración", formatearDuracion(ui.duracionSegundos.toLong()), Modifier.weight(1f))
        }

        TarjetaCalidad(ui.deriva, Icons.Filled.MyLocation)
        TarjetaCaptura(ui.modo, fotoTomadaVisible, Icons.Filled.CameraAlt, enPausa)

        // Acciones principales
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BotonAccion(
                icono = if (enPausa) Icons.Filled.PlayArrow else Icons.Filled.Pause,
                texto = if (enPausa) "Reanudar" else "Pausar",
                onClick = vm::alAlternarPausa, primario = true, modifier = Modifier.weight(1f),
            )
            BotonAccion(Icons.Filled.MyLocation, "Reubicarme manualmente", vm::alReubicarse, Modifier.weight(1f), habilitado = ui.reanclaje == null)
            // Fuera de alcance (depende de 7.6 y 7.7): se dibuja y no hace nada.
            BotonAccion(Icons.Filled.LocationOn, "Marcar punto de interés", {}, Modifier.weight(1f), habilitado = false, nota = "Próximamente")
        }
        FilaAccion(Icons.Filled.Warning, "Agregar alerta aquí", onClick = vm::alAgregarAlerta)
        FilaAccion(Icons.Filled.CameraAlt, "Intervalo de captura automática", "Cada ${ui.modo.etiqueta}", onClick = onIntervalo)

        BotonFinalizar(onClick = vm::alPedirFinalizar, habilitado = ui.fase != FaseRecoleccion.FINALIZANDO)
        FilaAlertasCercanas(ui.alertasActivas)
        PanelAvisos(ui.avisos)
    }
}

@Composable
private fun TarjetaMapa(
    ui: RecoleccionUiState, control: RecoleccionMapaControl, eventosMapa: RecoleccionMapaEventos,
    imageCapture: androidx.camera.core.ImageCapture, tieneCamara: Boolean, siguiendo: Boolean, destello: Float,
) {
    val forma = RoundedCornerShape(20.dp)
    Box(Modifier.fillMaxWidth().height(320.dp).clip(forma).border(1.dp, CampusColors.Borde, forma)) {
        RecoleccionMapaContent(
            control = control, lat = ui.lat, lng = ui.lng, rumbo = ui.rumbo.toFloat(),
            fotosJson = ui.fotosJson, trayectoriaJson = ui.trayectoriaJson, alertasJson = ui.alertasJson,
            reanclaje = ui.reanclaje?.let { it.lat to it.lng },
            eventos = eventosMapa, modifier = Modifier.fillMaxSize(),
        )
        // Destello de captura (no intercepta toques: es un Box sin clickable)
        if (destello > 0f) Box(Modifier.fillMaxSize().background(Color.White.copy(alpha = destello)))

        // «En vivo» / «Centrar»
        Row(
            Modifier.align(Alignment.TopStart).padding(8.dp).clip(RoundedCornerShape(14.dp))
                .background(CampusColors.Superficie.copy(alpha = .9f))
                .clickable(role = Role.Button, onClick = control::centrar).padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            androidx.compose.material3.Icon(Icons.Filled.MyLocation, null, tint = CampusColors.Acento, modifier = Modifier.size(20.dp))
            Text(if (siguiendo) "En vivo" else "Centrar", color = CampusColors.TextoPrincipal, fontSize = 14.sp)
        }

        // Vista previa de cámara (esquina). VistaCamara enlaza una sola vez: el ImageCapture es único.
        Box(
            Modifier.align(Alignment.TopEnd).padding(8.dp).size(width = 112.dp, height = 84.dp)
                .clip(RoundedCornerShape(12.dp)).border(1.5.dp, CampusColors.Acento, RoundedCornerShape(12.dp))
                .semantics { contentDescription = "Vista previa de la cámara" },
        ) { VistaCamara(imageCapture = imageCapture, activo = tieneCamara, modifier = Modifier.fillMaxSize()) }

        // Zoom
        Column(
            Modifier.align(Alignment.CenterEnd).padding(8.dp).clip(RoundedCornerShape(14.dp)).background(CampusColors.Superficie.copy(alpha = .9f)),
        ) {
            BotonMapa(Icons.Filled.Add, "Acercar", control::zoomMas)
            BotonMapa(Icons.Filled.Remove, "Alejar", control::zoomMenos)
        }

        // Leyenda
        Column(
            Modifier.align(Alignment.BottomStart).padding(8.dp).clip(RoundedCornerShape(12.dp))
                .background(CampusColors.Superficie.copy(alpha = .9f)).padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            ItemLeyenda(Color(0xFF7C5CFF), "Tu posición")
            ItemLeyenda(Color(0xFFA78BFA), "Ruta recorrida", linea = true)
            ItemLeyenda(Color(0xFFC4B5FD), "Fotos tomadas")
            ItemLeyenda(ColorAviso, "Alertas")
        }
    }
}

@Composable
private fun BotonMapa(icono: androidx.compose.ui.graphics.vector.ImageVector, descripcion: String, onClick: () -> Unit) {
    Box(
        Modifier.size(48.dp).clickable(role = Role.Button, onClick = onClick).semantics { contentDescription = descripcion },
        contentAlignment = Alignment.Center,
    ) { androidx.compose.material3.Icon(icono, null, tint = CampusColors.TextoPrincipal) }
}

@Composable
private fun ItemLeyenda(color: Color, texto: String, linea: Boolean = false) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(
            if (linea) Modifier.width(14.dp).height(3.dp).background(color, RoundedCornerShape(2.dp))
            else Modifier.size(10.dp).background(color, CircleShape),
        )
        Text(texto, color = CampusColors.TextoPrincipal, fontSize = 12.sp)
    }
}

@Composable
private fun DialogoIntervalo(actual: ModoCaptura, onElegir: (ModoCaptura) -> Unit, onCerrar: () -> Unit) {
    AlertDialog(
        onDismissRequest = onCerrar,
        containerColor = CampusColors.SuperficieAlta,
        title = { Text("Intervalo de captura", color = CampusColors.TextoPrincipal) },
        text = {
            Column {
                ModoCaptura.OPCIONES.forEach { opcion ->
                    Row(
                        Modifier.fillMaxWidth().clickable(role = Role.RadioButton) { onElegir(opcion) }.padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = opcion == actual, onClick = null)
                        Text("Cada ${opcion.etiqueta}", color = CampusColors.TextoPrincipal, modifier = Modifier.padding(start = 12.dp))
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onCerrar) { Text("Cerrar", color = CampusColors.Acento) } },
    )
}

@Composable
private fun PantallaError(detalle: String, onVolver: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(24.dp), Arrangement.Center, Alignment.CenterHorizontally) {
        Text("No se pudo iniciar la recolección", color = CampusColors.TextoPrincipal, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        Text(
            "Vuelve a fijar la ubicación de partida e inténtalo de nuevo. ($detalle)",
            color = CampusColors.TextoSuave, fontSize = 14.sp, modifier = Modifier.padding(vertical = 12.dp),
        )
        Button(onClick = onVolver, modifier = Modifier.height(52.dp)) { Text("Volver") }
    }
}