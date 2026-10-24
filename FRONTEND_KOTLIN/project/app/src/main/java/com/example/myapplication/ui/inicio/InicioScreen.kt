package com.example.myapplication.ui.inicio

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.outlined.AdminPanelSettings
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

// --- Paleta ---------------------------------------------------------------
private val Fondo = Color(0xFF030712)
private val Morado = Color(0xFF7C3AED)
private val MoradoClaro = Color(0xFFC4B5FD)
private val MoradoOscuro = Color(0xFF2E1F8A)
private val TextoSecundario = Color(0xFF9CA3AF)
private val Verde = Color(0xFF22E58B)
private val Rojo = Color(0xFFEF4444)
private val FondoAviso = Color(0xFF3B1D1D)

// --- Permisos -------------------------------------------------------------

/** Permisos en runtime que necesita la app (cámara, voz y PDR). */
private fun permisosNecesarios(): Array<String> = buildList {
    add(Manifest.permission.CAMERA)
    add(Manifest.permission.RECORD_AUDIO)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        add(Manifest.permission.ACTIVITY_RECOGNITION)
    }
}.toTypedArray()

private fun permisosFaltantes(ctx: Context): List<String> =
    permisosNecesarios().filter {
        ctx.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
    }

private fun tienePermisos(ctx: Context) = permisosFaltantes(ctx).isEmpty()

private fun nombreLegible(permiso: String): String = when (permiso) {
    Manifest.permission.CAMERA -> "Cámara"
    Manifest.permission.RECORD_AUDIO -> "Micrófono"
    Manifest.permission.ACTIVITY_RECOGNITION -> "Sensores de actividad"
    else -> permiso.substringAfterLast('.')
}

private fun abrirAjustesApp(ctx: Context) {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
        data = Uri.fromParts("package", ctx.packageName, null)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    ctx.startActivity(intent)
}

/** Punto de entrada: conecta ViewModel, permisos y navegación. */
@Composable
fun InicioScreen(
    onUbicarme: () -> Unit,
    onIrALugar: () -> Unit,
    onAccesoAdministrador: () -> Unit,
    viewModel: InicioViewModel = viewModel(),
) {
    val ctx = LocalContext.current
    val estado by viewModel.estado.collectAsStateWithLifecycle()

    // Permisos que faltan por conceder. Se refresca al volver de Ajustes y tras cada solicitud.
    var faltantes by remember { mutableStateOf(permisosFaltantes(ctx)) }

    val lanzadorPermisos = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) {
        faltantes = permisosFaltantes(ctx)
        // Arranca siempre: sin micrófono no hay voz, pero el orbe y las acciones
        // de accesibilidad siguen funcionando. El escaneo 360° solo necesitará cámara.
        viewModel.alAbrir()
    }

    // Primera vez: explicación hablada y luego solicitud de permisos.
    LaunchedEffect(Unit) {
        if (tienePermisos(ctx)) {
            viewModel.alAbrir()
        } else {
            viewModel.explicarPermisos { lanzadorPermisos.launch(permisosNecesarios()) }
        }
    }

    // Eventos de navegación.
    LaunchedEffect(Unit) {
        viewModel.eventos.collect {
            when (it) {
                InicioEvento.Ubicarme -> onUbicarme()
                InicioEvento.IrALugar -> onIrALugar()
            }
        }
    }

    // Ciclo de vida: refrescar permisos al volver de Ajustes y detener voz al salir.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val obs = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_RESUME -> faltantes = permisosFaltantes(ctx)
                Lifecycle.Event.ON_STOP -> viewModel.alPausar()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
    }

    InicioContent(
        escuchando = estado.escuchando,
        backendEnLinea = estado.backendEnLinea,
        permisosFaltantes = faltantes,
        onOrbe = viewModel::alPresionarOrbe,
        onUbicarme = viewModel::ubicarme,
        onIrALugar = viewModel::irALugar,
        onAccesoAdministrador = onAccesoAdministrador,
        onReintentarPermisos = { lanzadorPermisos.launch(permisosNecesarios()) },
        onIrAAjustes = { abrirAjustesApp(ctx) },
    )
}

@Composable
fun InicioContent(
    escuchando: Boolean,
    backendEnLinea: Boolean,
    permisosFaltantes: List<String>,
    onOrbe: () -> Unit,
    onUbicarme: () -> Unit,
    onIrALugar: () -> Unit,
    onAccesoAdministrador: () -> Unit,
    onReintentarPermisos: () -> Unit,
    onIrAAjustes: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Fondo)
            .statusBarsPadding()
            .navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // Banner de permisos (solo si falta alguno).
        if (permisosFaltantes.isNotEmpty()) {
            BannerPermisos(
                faltantes = permisosFaltantes,
                onReintentar = onReintentarPermisos,
                onIrAAjustes = onIrAAjustes,
            )
        }

        Spacer(Modifier.height(if (permisosFaltantes.isEmpty()) 72.dp else 20.dp))

        IconoSenal(modifier = Modifier.size(88.dp))

        Spacer(Modifier.height(28.dp))

        Text(
            text = if (escuchando) "Te escucho…"
            else "Presiona para ubicarte\no para llegar a un lugar.",
            color = Color.White,
            fontSize = 28.sp,
            lineHeight = 36.sp,
            fontWeight = FontWeight.Medium,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 24.dp),
        )

        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentAlignment = Alignment.Center,
        ) {
            Orbe(
                escuchando = escuchando,
                onClick = onOrbe,
                onUbicarme = onUbicarme,
                onIrALugar = onIrALugar,
            )
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                Icons.AutoMirrored.Filled.VolumeUp,
                contentDescription = null,
                tint = Morado,
                modifier = Modifier.size(24.dp),
            )
            Text("Activa el lector de pantalla", color = TextoSecundario, fontSize = 16.sp)
        }

        Spacer(Modifier.height(48.dp))

        BarraInferior(backendEnLinea, onAccesoAdministrador)
    }
}

/** Aviso superior con los permisos que faltan y botones para resolverlo. */
@Composable
private fun BannerPermisos(
    faltantes: List<String>,
    onReintentar: () -> Unit,
    onIrAAjustes: () -> Unit,
) {
    val nombres = faltantes.joinToString(", ") { nombreLegible(it) }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .background(FondoAviso, RoundedCornerShape(16.dp))
            .border(1.dp, Rojo, RoundedCornerShape(16.dp))
            .padding(16.dp)
            .semantics {
                contentDescription =
                    "Faltan permisos: $nombres. Toca Permitir para concederlos " +
                            "o Ajustes para abrirlos manualmente."
            },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "Faltan permisos: $nombres",
            color = Color.White,
            fontSize = 16.sp,
            lineHeight = 22.sp,
            textAlign = TextAlign.Center,
            fontWeight = FontWeight.Medium,
        )
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AccionPermiso(texto = "Permitir", onClick = onReintentar)
            AccionPermiso(texto = "Ajustes", onClick = onIrAAjustes)
        }
    }
}

@Composable
private fun AccionPermiso(texto: String, onClick: () -> Unit) {
    Text(
        text = texto,
        color = MoradoClaro,
        fontSize = 16.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp)
            .semantics { contentDescription = texto },
    )
}

@Composable
private fun Orbe(
    escuchando: Boolean,
    onClick: () -> Unit,
    onUbicarme: () -> Unit,
    onIrALugar: () -> Unit,
) {
    val transicion = rememberInfiniteTransition(label = "pulso")
    val pulso by transicion.animateFloat(
        initialValue = 1f,
        targetValue = 1.06f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "escala",
    )
    val escala = if (escuchando) pulso else 1f

    Box(
        modifier = Modifier
            .size(252.dp)
            .scale(escala)
            .shadow(
                elevation = 48.dp,
                shape = CircleShape,
                ambientColor = Morado,
                spotColor = Morado,
            )
            .background(
                Brush.radialGradient(
                    colors = listOf(MoradoOscuro, Color(0xFF5B2FD6), Color(0xFF7C45EE)),
                ),
                CircleShape,
            )
            .border(3.dp, MoradoClaro, CircleShape)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics {
                contentDescription =
                    "Botón principal. Toca dos veces para iniciar el escaneo de 360 grados " +
                            "y saber dónde estás."
                customActions = listOf(
                    CustomAccessibilityAction("Ir a un lugar") { onIrALugar(); true },
                )
            },
    )
}

/** Icono de señal: punto central con dos arcos a cada lado. */
@Composable
private fun IconoSenal(modifier: Modifier = Modifier) {
    Canvas(modifier = modifier.semantics { contentDescription = "" }) {
        val c = Offset(size.width / 2, size.height / 2)
        val trazo = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round)
        drawCircle(Color.White, radius = 9.dp.toPx(), center = c)
        listOf(20.dp.toPx(), 36.dp.toPx()).forEach { r ->
            val tam = Size(r * 2, r * 2)
            val tl = Offset(c.x - r, c.y - r)
            drawArc(Color.White, startAngle = -50f, sweepAngle = 100f, useCenter = false,
                topLeft = tl, size = tam, style = trazo)
            drawArc(Color.White, startAngle = 130f, sweepAngle = 100f, useCenter = false,
                topLeft = tl, size = tam, style = trazo)
        }
    }
}

@Composable
private fun BarraInferior(backendEnLinea: Boolean, onAccesoAdministrador: () -> Unit) {
    Column(Modifier.padding(horizontal = 24.dp)) {
        HorizontalDivider(color = Color(0xFF111827))
        Spacer(Modifier.height(20.dp))
        Row(
            modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                modifier = Modifier
                    .weight(1f)
                    .semantics {
                        contentDescription =
                            if (backendEnLinea) "Conectado. Backend en línea."
                            else "Sin conexión. Backend no disponible."
                    },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .size(14.dp)
                        .background(if (backendEnLinea) Verde else Rojo, CircleShape)
                )
                Spacer(Modifier.width(14.dp))
                Column {
                    Text(
                        if (backendEnLinea) "Conectado" else "Sin conexión",
                        color = Color.White, fontSize = 16.sp,
                    )
                    Text(
                        if (backendEnLinea) "Backend en línea" else "Backend no disponible",
                        color = TextoSecundario, fontSize = 14.sp,
                    )
                }
            }

            Row(
                modifier = Modifier
                    .clickable(role = Role.Button, onClick = onAccesoAdministrador)
                    .padding(vertical = 8.dp)
                    .semantics { contentDescription = "Acceso administrador" },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Outlined.AdminPanelSettings, null, tint = Morado,
                    modifier = Modifier.size(32.dp))
                Spacer(Modifier.width(10.dp))
                Text("Acceso administrador", color = MoradoClaro, fontSize = 16.sp)
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Morado)
            }
        }
    }
}