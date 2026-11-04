package com.example.myapplication.ui.navegacion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.camera.crearImageCapture
import com.example.myapplication.camera.liberarCamara
import com.example.myapplication.camera.tomarFoto
import com.example.myapplication.sensors.PdrTracker
import com.example.myapplication.ui.theme.CampusColors
import com.example.myapplication.ui.ubicacion.componentes.VistaCamara

/*
 * Vista 6.5 — Navegación guiada (FE-5.3). Usable sin mirar la pantalla: todo se dice por voz (la guía) y solo hay dos
 * botones grandes, «Repetir instrucción» y «Terminar». La pantalla es dueña del PDR (con el ciclo de vida de esta
 * entrada de la pila, como el mapa: ADR-FE-22), de la cámara (una vista previa pequeña; la foto es automática) y de la
 * navegación. La lógica está en NavegacionViewModel y domain/guia/.
 */

@Composable
fun NavegacionScreen(
    camaraOk: Boolean,
    onTerminar: () -> Unit,
    onLlegada: () -> Unit,
    viewModel: NavegacionViewModel = viewModel(),
) {
    val ctx = LocalContext.current
    val estado by viewModel.estado.collectAsStateWithLifecycle()
    val lifecycleOwner = LocalLifecycleOwner.current
    val ciclo = lifecycleOwner.lifecycle

    // PDR desde la posición de «Ubicarme» (o la de prueba); no se crea en el modo de simulación.
    val tracker = remember { if (viewModel.simulando) null else PdrTracker(ctx, cicloDeVida = ciclo) }
    DisposableEffect(tracker) { onDispose { tracker?.liberar() } }
    LaunchedEffect(tracker) {
        val t = tracker ?: return@LaunchedEffect
        val inicio = viewModel.posicionInicial ?: return@LaunchedEffect
        t.fijarPosicion(inicio.first, inicio.second)
        t.iniciar()
        t.estado.collect { viewModel.onPdr(it) }
    }

    val imageCapture = remember { crearImageCapture() }
    LaunchedEffect(Unit) {
        viewModel.alAbrir()
        viewModel.eventos.collect { e ->
            when (e) {
                NavegacionEvento.TomarFoto ->
                    if (camaraOk) {
                        imageCapture.tomarFoto(
                            ctx, viewModel.carpetaFotos(), prefijo = "guia",
                            onGuardada = viewModel::onFotoTomada, onFallo = viewModel::onFotoFallida,
                        )
                    } else {
                        viewModel.onFotoFallida()
                    }
                is NavegacionEvento.CorregirPosicion -> tracker?.fijarPosicion(e.lat, e.lng)
                NavegacionEvento.Llegada -> onLlegada()
            }
        }
    }

    // Pantalla encendida mientras se guía; cámara liberada al salir.
    val view = LocalView.current
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        onDispose {
            view.keepScreenOn = false
            liberarCamara(ctx)
        }
    }

    DisposableEffect(lifecycleOwner) {
        val obs = LifecycleEventObserver { _, ev ->
            when (ev) {
                Lifecycle.Event.ON_STOP -> viewModel.alPausar()
                Lifecycle.Event.ON_START -> viewModel.alReanudar()
                else -> Unit
            }
        }
        ciclo.addObserver(obs)
        onDispose { ciclo.removeObserver(obs) }
    }

    val acciones = remember(viewModel) {
        NavegacionAcciones(
            onRepetir = viewModel::repetir,
            onTerminar = { viewModel.terminar(); onTerminar() },
        )
    }
    NavegacionContent(estado, acciones) {
        VistaCamara(imageCapture = imageCapture, activo = camaraOk, modifier = Modifier.fillMaxWidth().height(110.dp))
    }
}

/** Contenido sin lógica de 6.5: instrucción en grande (*live region*), destino, metros, seguimiento y dos botones. */
@Composable
internal fun NavegacionContent(
    estado: NavegacionUiState,
    acciones: NavegacionAcciones,
    modifier: Modifier = Modifier,
    camara: @Composable () -> Unit = {},
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CampusColors.Fondo)
            .systemBarsPadding()
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = if (estado.destino.isBlank()) "Navegación guiada" else "Hacia ${estado.destino}",
            color = CampusColors.TextoSecundario,
            fontSize = 20.sp,
            modifier = Modifier.semantics { heading() },
        )
        Text(
            text = estado.instruccion,
            color = CampusColors.TextoPrincipal,
            fontSize = 34.sp,
            lineHeight = 42.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.semantics {
                liveRegion = LiveRegionMode.Polite
                contentDescription = "Instrucción: ${estado.instruccion}"
            },
        )
        estado.restante?.let { Text(it, color = CampusColors.TextoSecundario, fontSize = 22.sp) }
        if (estado.simulacion) Text("Modo de simulación (pasos simulados)", color = CampusColors.Peligro, fontSize = 16.sp)
        Spacer(Modifier.weight(1f))
        estado.seguimiento?.let { Text(it, color = CampusColors.TextoSuave, fontSize = 14.sp) }
        camara()
        BotonGrande("Repetir instrucción", principal = true, onClick = acciones.onRepetir)
        BotonGrande("Terminar", principal = false, onClick = acciones.onTerminar)
    }
}

/** Botón de 6.5 y 6.6: ancho completo y al menos 80 dp de alto (se encuentra sin mirar). */
@Composable
internal fun BotonGrande(texto: String, principal: Boolean, onClick: () -> Unit) {
    val m = Modifier.fillMaxWidth().heightIn(min = 80.dp)
    val forma = RoundedCornerShape(20.dp)
    if (principal) {
        Button(
            onClick = onClick,
            modifier = m,
            shape = forma,
            colors = ButtonDefaults.buttonColors(containerColor = CampusColors.Primario, contentColor = CampusColors.TextoPrincipal),
        ) { Text(texto, fontSize = 24.sp, fontWeight = FontWeight.Bold) }
    } else {
        OutlinedButton(
            onClick = onClick,
            modifier = m,
            shape = forma,
            border = BorderStroke(2.dp, CampusColors.Primario),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = CampusColors.Acento),
        ) { Text(texto, fontSize = 24.sp, fontWeight = FontWeight.Bold) }
    }
}

@Preview(showBackground = true, heightDp = 800)
@Composable
private fun PreviewNavegacion() {
    NavegacionContent(
        NavegacionUiState(
            destino = "Bloque 35",
            instruccion = "En 10 metros, gira a la izquierda.",
            restante = "Faltan 18 m por el camino",
            seguimiento = "Fotos: 1 pedidas, 0 aceptadas · última descartada (sin_coincidencias)",
        ),
        NavegacionAcciones(),
    )
}
