package com.example.myapplication.ui.ubicacion

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.ImageCapture
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.camera.crearCarpetaEscaneo // NUEVO
import com.example.myapplication.camera.crearImageCapture
import com.example.myapplication.camera.liberarCamara
import com.example.myapplication.camera.tomarFoto
import com.example.myapplication.sensors.EscucharOrientacion
import com.example.myapplication.sensors.tieneSensorRotacion
import com.example.myapplication.ui.ubicacion.EscaneoColores.Fondo
import com.example.myapplication.ui.ubicacion.componentes.AnilloProgreso
import com.example.myapplication.ui.ubicacion.componentes.BarraSuperior
import com.example.myapplication.ui.ubicacion.componentes.BotonesAccion
import com.example.myapplication.ui.ubicacion.componentes.IndicadorInclinacion
import com.example.myapplication.ui.ubicacion.componentes.InstruccionGrande
import com.example.myapplication.ui.ubicacion.componentes.RecordatoriosFijos
import com.example.myapplication.ui.ubicacion.componentes.VistaCamara
import java.io.File // NUEVO

/*
 * Vista 6.2 — Ubicarse (escaneo 360°).
 *
 * Este archivo solo "conecta" cosas (permisos, sensores, cámara, ViewModel).
 *   - Lógica del giro y las fotos  -> EscaneoViewModel
 *   - Estado y eventos             -> EscaneoState
 *   - Piezas visuales              -> componentes/
 *   - Sensor de rotación           -> sensors/OrientationProvider
 *   - Captura y calidad de foto    -> camera/
 */

// ============================================================================
// Pantalla con estado (se conecta con Android y con el ViewModel)
// ============================================================================

@Composable
fun EscaneoScreen(
    onCancelar: () -> Unit,
    onCompletado: () -> Unit,
    onAjustes: () -> Unit = {},
    viewModel: EscaneoViewModel = viewModel(),
) {
    val ctx = LocalContext.current
    val estado by viewModel.estado.collectAsStateWithLifecycle()
    val imageCapture = remember { crearImageCapture() }

    // NUEVO: carpeta del escaneo en curso (una por vuelta de 5 fotos),
    // dentro de camera/photos/<yyyy-MM-dd_HH-mm-ss>/
    var carpetaEscaneo by remember { mutableStateOf<File?>(null) }

    // NUEVO: abre una carpeta nueva y arranca el escaneo (se usa al iniciar y al repetir)
    val nuevoEscaneo: () -> Unit = {
        carpetaEscaneo = crearCarpetaEscaneo(ctx)
        viewModel.iniciar()
    }

    // --- Permiso de cámara (normalmente ya concedido desde Inicio) ----------
    var camaraOk by remember {
        mutableStateOf(
            ctx.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    val lanzador = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        camaraOk = it
    }
    LaunchedEffect(Unit) { if (!camaraOk) lanzador.launch(Manifest.permission.CAMERA) }

    // --- Sensor de rotación -------------------------------------------------
    val tieneSensor = remember { tieneSensorRotacion(ctx) }

    // Con cámara disponible: iniciar el escaneo (voz) o avisar que falta el sensor.
    LaunchedEffect(camaraOk) {
        if (camaraOk) {
            // CAMBIO: antes llamaba directamente a viewModel.iniciar()
            if (tieneSensor) nuevoEscaneo() else viewModel.sensorNoDisponible()
        }
    }

    // Acimut y cabeceo -> ViewModel (solo mientras haya cámara y sensor).
    EscucharOrientacion(
        activo = camaraOk && tieneSensor,
        onOrientacion = viewModel::onOrientacion,
    )

    // --- Eventos del ViewModel: tomar foto / terminar -----------------------
    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                // CAMBIO: ahora guarda en la carpeta del escaneo actual
                EscaneoEvento.Capturar -> {
                    val carpeta = carpetaEscaneo
                        ?: crearCarpetaEscaneo(ctx).also { carpetaEscaneo = it }
                    imageCapture.tomarFoto(
                        ctx = ctx,
                        carpeta = carpeta,
                        prefijo = "escaneo",
                        onGuardada = viewModel::onFotoTomada,
                        onFallo = viewModel::onFotoFallida,
                    )
                }
                EscaneoEvento.Completado -> onCompletado()
            }
        }
    }

    // --- Pantalla siempre encendida y cámara liberada al salir --------------
    val view = LocalView.current
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        onDispose {
            view.keepScreenOn = false
            liberarCamara(ctx)
        }
    }

    // Cancelar (botón o atrás del sistema): limpia el ViewModel y avisa al padre.
    val cancelar = { viewModel.cancelar(); onCancelar() }
    BackHandler(onBack = cancelar)

    EscaneoContent(
        estado = estado,
        camaraOk = camaraOk,
        imageCapture = imageCapture,
        onAtras = cancelar,
        onAjustes = onAjustes,
        onCancelar = cancelar,
        onRepetir = nuevoEscaneo, // CAMBIO: antes era viewModel::iniciar
    )
}

// ============================================================================
// Contenido sin lógica (solo dibuja el estado recibido)
// ============================================================================

@Composable
private fun EscaneoContent(
    estado: EscaneoUiState,
    camaraOk: Boolean,
    imageCapture: ImageCapture,
    onAtras: () -> Unit,
    onAjustes: () -> Unit,
    onCancelar: () -> Unit,
    onRepetir: () -> Unit,
) {
    // Texto principal según la situación (el permiso y los errores tienen prioridad).
    val titulo = when {
        !camaraOk -> "Necesito permiso de cámara"
        estado.fase == Fase.ANALIZANDO -> "Analizando…"
        estado.fase == Fase.ERROR -> estado.error?.mensaje.orEmpty()
        else -> estado.instruccion.texto
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Fondo)
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState()) // por si el texto se agranda mucho
            .padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BarraSuperior(onAtras = onAtras, onAjustes = onAjustes)
        Spacer(Modifier.height(8.dp))

        VistaCamara(
            imageCapture = imageCapture,
            activo = camaraOk,
            modifier = Modifier.fillMaxWidth().aspectRatio(1.63f),
        )
        Spacer(Modifier.height(20.dp))

        AnilloProgreso(estado)
        Spacer(Modifier.height(20.dp))

        InstruccionGrande(texto = titulo, esError = estado.fase == Fase.ERROR)
        Spacer(Modifier.height(20.dp))

        RecordatoriosFijos()
        Spacer(Modifier.height(20.dp))

        IndicadorInclinacion(estado.inclinacionOk)
        Spacer(Modifier.height(28.dp))

        BotonesAccion(onCancelar = onCancelar, onRepetir = onRepetir)
        Spacer(Modifier.height(24.dp))
    }
}