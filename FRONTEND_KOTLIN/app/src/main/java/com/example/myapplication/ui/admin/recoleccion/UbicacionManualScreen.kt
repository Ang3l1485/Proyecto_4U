package com.example.myapplication.ui.admin.recoleccion

import android.webkit.JavascriptInterface
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.outlined.Cancel
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Explore
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.LocationOn
import androidx.compose.material.icons.outlined.MyLocation
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Straighten
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.InicioRecoleccion
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.map.MapaWeb
import com.example.myapplication.map.MapaWebView
import com.example.myapplication.map.PuenteWeb
import com.example.myapplication.map.literalJs
import com.example.myapplication.map.rememberMapaWeb
import com.example.myapplication.data.repository.CalibracionPasoRepository
import com.example.myapplication.sensors.EscucharOrientacion
import com.example.myapplication.sensors.PdrEngine
import com.example.myapplication.sensors.tieneSensorRotacion
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin
import java.util.Locale

private val C = CampusColors

/** El mock usa rosa para Cancelar; `CampusColors.Peligro` es morado (11.4), así que va aparte. */
private val ColorCancelar = Color(0xFFFF4D7D)

private const val GRADOS_POR_PASO = 15f

// ═════════════════════════════════════════════════════════════════════════════════════
//  Conexión
// ═════════════════════════════════════════════════════════════════════════════════════

/**
 * Vista 7.3 — Ubicación manual inicial.
 *
 * @param onConfirmar recibe el punto, el rumbo y el nombre. Aún **no existe** `crearVideo` ni la
 *   vista 7.4: quien navega decide qué hacer (ver 11.6).
 */
@Composable
fun UbicacionManualScreen(
    onVolver: () -> Unit,
    onConfirmar: (InicioRecoleccion) -> Unit,
    onAjustes: () -> Unit = {},
    onCalibrar: () -> Unit = {},
    viewModel: UbicacionManualViewModel = viewModel(
        factory = UbicacionManualViewModel.Factory(LocalContext.current.applicationContext),
    ),
) {
    val contexto = LocalContext.current
    val estado by viewModel.ui.collectAsStateWithLifecycle()
    val volverActual by rememberUpdatedState(onVolver)
    val ajustesActual by rememberUpdatedState(onAjustes)
    val confirmarActual by rememberUpdatedState(onConfirmar)
    val brujulaOk = remember { tieneSensorRotacion(contexto) }
    // Longitud calibrada (null = valor genérico). Se relee al volver de la calibración porque NavHost
    // recompone la ruta; D9: el PdrTracker la lee una sola vez al crearse (7.4).
    val longitudCalibradaM = remember { CalibracionPasoRepository(contexto).guardada() }
    val calibrarActual by rememberUpdatedState(onCalibrar)

    LaunchedEffect(Unit) { viewModel.alAbrir(brujulaOk) }

    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                is UbicacionManualEvento.Confirmado -> confirmarActual(evento.inicio)
            }
        }
    }

    // La brújula solo escucha mientras el botón está activo y la pantalla visible.
    EscucharOrientacion(activo = estado.usandoBrujula) { acimut, _ -> viewModel.alLeerBrujula(acimut) }

    val dueño = LocalLifecycleOwner.current
    DisposableEffect(dueño) {
        val observador = LifecycleEventObserver { _, evento ->
            when (evento) {
                Lifecycle.Event.ON_STOP -> viewModel.alPausar()
                Lifecycle.Event.ON_RESUME -> viewModel.alReanudar()
                else -> Unit
            }
        }
        dueño.lifecycle.addObserver(observador)
        onDispose { dueño.lifecycle.removeObserver(observador) }
    }

    val acciones = remember(viewModel) {
        UbicacionManualAcciones(
            onVolver = { volverActual() },
            onAjustes = { ajustesActual() },
            onPuntoCambiado = viewModel::alMoverPunto,
            onRumbo = viewModel::alElegirRumbo,
            onAlternarBrujula = viewModel::alAlternarBrujula,
            onEditarCoordenada = viewModel::alEditarCoordenada,
            onTextoEdicion = viewModel::alCambiarTextoEdicion,
            onAceptarEdicion = viewModel::alAceptarEdicion,
            onCancelarEdicion = viewModel::alCancelarEdicion,
            onUsarUltima = viewModel::alUsarUltimaPosicion,
            onNombre = viewModel::alCambiarNombre,
            onCancelar = { volverActual() },
            onConfirmar = viewModel::alConfirmar,
            onCalibrar = { calibrarActual() },
        )
    }

    UbicacionManualContent(estado = estado, acciones = acciones, longitudCalibradaM = longitudCalibradaM)
}

// ═════════════════════════════════════════════════════════════════════════════════════
//  Contenido (sin lógica)
// ═════════════════════════════════════════════════════════════════════════════════════

@Composable
fun UbicacionManualContent(
    estado: UbicacionManualUiState,
    acciones: UbicacionManualAcciones,
    modifier: Modifier = Modifier,
    longitudCalibradaM: Double? = null,
) {
    val scroll = rememberScrollState()
    // Mientras el dedo está sobre el mapa, la columna no se desplaza (si no, arrastrar el
    // marcador movería la pantalla). El aviso llega desde el JS con `gesto(activo)`.
    var mapaEnGesto by remember { mutableStateOf(false) }

    Column(
        modifier
            .fillMaxSize()
            .background(C.Fondo)
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding(),
    ) {
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(scroll, enabled = !mapaEnGesto)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Encabezado(acciones.onVolver, acciones.onAjustes)
            BannerAyuda()
            MapaConControles(estado, acciones, onGesto = { mapaEnGesto = it })
            Row(
                Modifier.height(IntrinsicSize.Min),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                TarjetaOrientacion(estado, acciones, Modifier.weight(1.15f).fillMaxHeight())
                TarjetaCoordenadas(estado, acciones, Modifier.weight(1f).fillMaxHeight())
            }
            FilaUltimaPosicion(estado, acciones.onUsarUltima)
            FilaCalibracion(longitudCalibradaM, acciones.onCalibrar)
            TarjetaNombreVideo(estado, acciones.onNombre)
            Spacer(Modifier.height(4.dp))
        }
        BarraAcciones(estado.puedeConfirmar, acciones.onCancelar, acciones.onConfirmar)
    }

    estado.edicion?.let { edicion ->
        DialogoCoordenada(edicion, acciones.onTextoEdicion, acciones.onAceptarEdicion, acciones.onCancelarEdicion)
    }
}

// ── Encabezado y ayuda ──────────────────────────────────────────────────────────────

@Composable
private fun Encabezado(onVolver: () -> Unit, onAjustes: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        BotonIcono(Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Volver", onVolver, C.Acento)
        Box(
            Modifier
                .size(48.dp)
                .background(C.SuperficieAlta, CircleShape)
                .border(2.dp, C.Primario, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.LocationOn, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f).semantics(mergeDescendants = true) { heading() }) {
            Text(
                "Fijar ubicación de partida",
                color = C.TextoPrincipal,
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text("Antes de recolectar", color = C.Acento, fontSize = 14.sp)
        }
        BotonIcono(Icons.Outlined.Settings, "Ajustes", onAjustes, C.Acento)
    }
}

@Composable
private fun BannerAyuda() {
    Row(
        Modifier.fillMaxWidth().tarjeta(16.dp).padding(horizontal = 14.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Info, contentDescription = null, tint = C.Acento, modifier = Modifier.size(28.dp))
        Spacer(Modifier.width(12.dp))
        Text(
            "Colócate en un punto reconocible y marca tu posición exacta.",
            color = C.TextoSecundario,
            fontSize = 15.sp,
            lineHeight = 20.sp,
        )
    }
}

// ── Mapa ────────────────────────────────────────────────────────────────────────────

/** Eventos del mapa web hacia la pantalla. Lo implementa el contenido; lo invoca [UbicacionPuente]. */
internal interface UbicacionMapaEventos {
    fun puntoCambiado(lat: Double, lng: Double)
    fun gesto(activo: Boolean)
}

/**
 * Puente web → app de `ubicacion_manual.html`. Los métodos llegan en un hilo del `WebView`:
 * `enHiloPrincipal` los pasa al principal. **No** puede ser `private` (se invoca por reflexión).
 */
internal class UbicacionPuente(
    mapa: MapaWeb,
    private val eventos: () -> UbicacionMapaEventos,
) : PuenteWeb(mapa) {
    @JavascriptInterface
    fun puntoCambiado(lat: Double, lng: Double) {
        enHiloPrincipal { eventos().puntoCambiado(lat, lng) }
    }

    @JavascriptInterface
    fun gesto(activo: Boolean) {
        enHiloPrincipal { eventos().gesto(activo) }
    }
}

@Composable
private fun MapaConControles(
    estado: UbicacionManualUiState,
    acciones: UbicacionManualAcciones,
    onGesto: (Boolean) -> Unit,
) {
    val mapa = rememberMapaWeb()
    val accionesActuales by rememberUpdatedState(acciones)
    val gestoActual by rememberUpdatedState(onGesto)
    val eventos = remember {
        object : UbicacionMapaEventos {
            override fun puntoCambiado(lat: Double, lng: Double) = accionesActuales.onPuntoCambiado(lat, lng)
            override fun gesto(activo: Boolean) = gestoActual(activo)
        }
    }
    val puente = remember(mapa) { UbicacionPuente(mapa) { eventos } }
    val forma = RoundedCornerShape(20.dp)

    // Kotlin → web. El estado se reenvía cada vez que cambia, y solo cuando la página avisó `listo()`.
    LaunchedEffect(mapa.listo) {
        if (mapa.listo) {
            mapa.js("setCentro(${CampusMapa.CENTRO.lat}, ${CampusMapa.CENTRO.lng}, ${CampusMapa.ZOOM_INICIAL})")
        }
    }
    LaunchedEffect(mapa.listo, estado.lugares) {
        if (mapa.listo) mapa.js("cargarLugares(${literalJs(lugaresJson(estado.lugares))})")
    }
    LaunchedEffect(mapa.listo, estado.rumbo) {
        if (mapa.listo) mapa.js("setRumbo(${estado.rumbo})")
    }
    LaunchedEffect(mapa.listo, estado.punto) {
        val p = estado.punto
        if (mapa.listo && p != null) mapa.js("setPunto(${p.lat}, ${p.lng})")
    }
    // Va después de `setPunto`: los efectos corren en el orden en que se declaran.
    LaunchedEffect(mapa.listo, estado.centrarSolicitud) {
        if (mapa.listo && estado.centrarSolicitud > 0) mapa.js("centrar()")
    }

    Box(
        Modifier
            .fillMaxWidth()
            .height(300.dp)
            .clip(forma)
            .border(1.dp, C.Borde, forma)
            .background(Color(0xFF0A0E1A))
            .semantics {
                contentDescription =
                    "Mapa del campus. Toca para colocar tu posición o arrastra el marcador. " +
                        "También puedes escribir las coordenadas."
            },
    ) {
        if (LocalInspectionMode.current) {
            Text(
                "Mapa (vista previa)",
                color = C.TextoSuave,
                modifier = Modifier.align(Alignment.Center),
            )
        } else {
            MapaWebView(
                mapa = mapa,
                html = "ubicacion_manual.html",
                puente = puente,
                nombrePuente = "UbicacionBridge",
                tag = "UbicacionMapa",
                modifier = Modifier.fillMaxSize(),
                pasarInsets = false, // la página no define setInsets; la pantalla ya pone los márgenes
                manejarAtras = false, // «atrás» lo resuelve el NavHost
            )
        }

        BotonCentrar(Modifier.align(Alignment.TopStart).padding(12.dp)) { mapa.js("centrar()") }
        ControlZoom(
            Modifier.align(Alignment.CenterEnd).padding(end = 12.dp),
            onMas = { mapa.js("zoomMas()") },
            onMenos = { mapa.js("zoomMenos()") },
        )
    }
}

private fun lugaresJson(lugares: List<LugarDestino>): String =
    JSONArray().also { arr ->
        lugares.forEach {
            arr.put(
                JSONObject()
                    .put("id", it.id)
                    .put("nombre", it.nombre)
                    .put("categoria", it.categoria.name)
                    .put("lat", it.lat)
                    .put("lng", it.lng),
            )
        }
    }.toString()

@Composable
private fun BotonCentrar(modifier: Modifier, onClick: () -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(
        modifier
            .heightIn(min = 48.dp)
            .clip(forma)
            .background(C.Superficie.copy(alpha = 0.92f))
            .border(1.dp, C.Borde, forma)
            .clickable(role = Role.Button, onClickLabel = "Centrar el mapa", onClick = onClick)
            .padding(horizontal = 14.dp)
            .semantics(mergeDescendants = true) { contentDescription = "Centrar el mapa en el marcador" },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.MyLocation, contentDescription = null, tint = C.Acento, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(8.dp))
        Text("Centrar", color = C.TextoPrincipal, fontSize = 16.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun ControlZoom(modifier: Modifier, onMas: () -> Unit, onMenos: () -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Column(
        modifier
            .clip(forma)
            .background(C.Superficie.copy(alpha = 0.92f))
            .border(1.dp, C.Borde, forma),
    ) {
        BotonZoom(Icons.Filled.Add, "Acercar el mapa", onMas)
        Box(Modifier.width(48.dp).height(1.dp).background(C.Borde))
        BotonZoom(Icons.Filled.Remove, "Alejar el mapa", onMenos)
    }
}

@Composable
private fun BotonZoom(icono: androidx.compose.ui.graphics.vector.ImageVector, descripcion: String, onClick: () -> Unit) {
    Box(
        Modifier
            .size(48.dp)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = descripcion },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icono, contentDescription = null, tint = C.TextoPrincipal, modifier = Modifier.size(26.dp))
    }
}

// ── Orientación ─────────────────────────────────────────────────────────────────────

@Composable
private fun EncabezadoTarjeta(
    icono: androidx.compose.ui.graphics.vector.ImageVector,
    titulo: String,
    subtitulo: String,
    modifier: Modifier = Modifier,
) {
    Row(modifier.semantics(mergeDescendants = true) { heading() }, verticalAlignment = Alignment.Top) {
        Box(
            Modifier.size(40.dp).background(C.SuperficieAlta, CircleShape).border(1.5.dp, C.Primario, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icono, contentDescription = null, tint = C.Acento, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.width(10.dp))
        Column {
            Text(titulo, color = C.TextoPrincipal, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Text(subtitulo, color = C.Acento, fontSize = 12.5.sp, lineHeight = 16.sp)
        }
    }
}

@Composable
private fun TarjetaOrientacion(
    estado: UbicacionManualUiState,
    acciones: UbicacionManualAcciones,
    modifier: Modifier = Modifier,
) {
    // Dial y botón lado a lado solo si caben; con pantalla angosta o letra grande se apilan.
    // (No se usa BoxWithConstraints: no admite medidas intrínsecas dentro del Row.)
    val horizontal = LocalConfiguration.current.screenWidthDp >= 380 && LocalDensity.current.fontScale <= 1.15f

    Column(modifier.tarjeta().padding(12.dp)) {
        EncabezadoTarjeta(Icons.Outlined.Explore, "Orientación", "Indica hacia dónde miras.")
        Spacer(Modifier.height(10.dp))
        if (horizontal) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                DialConLeyenda(estado.rumbo, acciones.onRumbo)
                Spacer(Modifier.width(8.dp))
                BotonBrujula(estado, acciones.onAlternarBrujula, Modifier.weight(1f))
            }
        } else {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                DialConLeyenda(estado.rumbo, acciones.onRumbo)
                Spacer(Modifier.height(8.dp))
                BotonBrujula(estado, acciones.onAlternarBrujula, Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
private fun DialConLeyenda(rumbo: Float, onRumbo: (Float) -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        DialOrientacion(rumbo, onRumbo)
        // Oculta a TalkBack: la descripción del dial ya dice los grados y el punto cardinal.
        Text(
            "${Rumbo.cardinal(rumbo)} · ${rumbo.roundToInt() % 360}°",
            color = C.TextoSuave,
            fontSize = 12.sp,
            modifier = Modifier.padding(top = 4.dp).clearAndSetSemantics { },
        )
    }
}

/**
 * Rueda de rumbo: se arrastra o se toca para fijar hacia dónde mira la persona.
 * 0° = arriba (norte), sentido horario. Para TalkBack: acciones de ±15° y «Apuntar al norte».
 */
@Composable
private fun DialOrientacion(rumbo: Float, onRumbo: (Float) -> Unit, modifier: Modifier = Modifier) {
    val onRumboActual by rememberUpdatedState(onRumbo)
    val grados = rumbo.roundToInt() % 360
    val descripcion = "Orientación: $grados grados, ${Rumbo.nombreCardinal(rumbo)}. Arrastra para girar."

    Box(
        modifier
            .size(88.dp)
            .pointerInput(Unit) {
                detectTapGestures { onRumboActual(anguloDesdeCentro(it, size)) }
            }
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { onRumboActual(anguloDesdeCentro(it, size)) },
                    onDrag = { cambio, _ ->
                        cambio.consume()
                        onRumboActual(anguloDesdeCentro(cambio.position, size))
                    },
                )
            }
            .semantics {
                contentDescription = descripcion
                stateDescription = "$grados grados"
                customActions = listOf(
                    CustomAccessibilityAction("Girar 15 grados a la derecha") {
                        onRumboActual(Rumbo.normalizar(rumbo + GRADOS_POR_PASO)); true
                    },
                    CustomAccessibilityAction("Girar 15 grados a la izquierda") {
                        onRumboActual(Rumbo.normalizar(rumbo - GRADOS_POR_PASO)); true
                    },
                    CustomAccessibilityAction("Apuntar al norte") {
                        onRumboActual(0f); true
                    },
                )
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val r = size.minDimension / 2f
            val centro = Offset(size.width / 2f, size.height / 2f)
            drawCircle(C.SuperficieAlta, radius = r)
            drawCircle(C.Primario.copy(alpha = 0.75f), radius = r - 1.dp.toPx(), style = Stroke(2.dp.toPx()))
            // Marcas cada 30°, salvo en los puntos cardinales (ahí van las letras).
            for (i in 0 until 12) {
                if (i % 3 == 0) continue
                val rad = Math.toRadians(i * 30.0)
                val dir = Offset(sin(rad).toFloat(), -cos(rad).toFloat())
                drawLine(
                    color = C.Acento.copy(alpha = 0.7f),
                    start = centro + dir * (r - 9.dp.toPx()),
                    end = centro + dir * (r - 4.dp.toPx()),
                    strokeWidth = 1.5.dp.toPx(),
                )
            }
        }
        Text("N", Modifier.align(Alignment.TopCenter).padding(top = 5.dp), color = C.Acento, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Text("E", Modifier.align(Alignment.CenterEnd).padding(end = 7.dp), color = C.TextoSecundario, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Text("S", Modifier.align(Alignment.BottomCenter).padding(bottom = 5.dp), color = C.TextoSecundario, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Text("O", Modifier.align(Alignment.CenterStart).padding(start = 7.dp), color = C.TextoSecundario, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Box(
            Modifier.size(34.dp).background(C.Primario, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Filled.Navigation,
                contentDescription = null,
                tint = C.TextoPrincipal,
                modifier = Modifier.size(22.dp).rotate(rumbo),
            )
        }
    }
}

/** Ángulo (0…360, 0 = arriba, horario) del punto tocado respecto al centro del dial. */
private fun anguloDesdeCentro(punto: Offset, tam: IntSize): Float {
    val dx = punto.x - tam.width / 2f
    val dy = punto.y - tam.height / 2f
    return Rumbo.normalizar(Math.toDegrees(atan2(dx.toDouble(), -dy.toDouble())).toFloat())
}

@Composable
private fun BotonBrujula(estado: UbicacionManualUiState, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val forma = RoundedCornerShape(14.dp)
    val activo = estado.usandoBrujula
    val habilitado = estado.brujulaDisponible
    val texto = if (activo) "Fijar rumbo" else "Usar brújula del teléfono"
    Column(
        modifier
            .heightIn(min = 56.dp)
            .clip(forma)
            .background(if (activo) C.Primario else C.Primario.copy(alpha = 0.12f))
            .border(1.5.dp, C.Primario.copy(alpha = if (habilitado) 1f else 0.4f), forma)
            .clickable(enabled = habilitado, role = Role.Button, onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 8.dp)
            .semantics(mergeDescendants = true) {
                contentDescription = texto
                if (!habilitado) stateDescription = "Este teléfono no tiene brújula; gira el dial con el dedo"
                else if (activo) stateDescription = "La brújula está actualizando el rumbo"
            },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            Icons.Outlined.PhoneAndroid,
            contentDescription = null,
            tint = C.TextoPrincipal.copy(alpha = if (habilitado) 1f else 0.4f),
            modifier = Modifier.size(22.dp),
        )
        Text(
            texto,
            color = C.TextoPrincipal.copy(alpha = if (habilitado) 1f else 0.4f),
            fontSize = 13.sp,
            lineHeight = 16.sp,
            textAlign = TextAlign.Center,
        )
    }
}

// ── Coordenadas ─────────────────────────────────────────────────────────────────────

@Composable
private fun TarjetaCoordenadas(
    estado: UbicacionManualUiState,
    acciones: UbicacionManualAcciones,
    modifier: Modifier = Modifier,
) {
    Column(modifier.tarjeta().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        EncabezadoTarjeta(
            Icons.Outlined.LocationOn,
            "Coordenadas",
            if (estado.punto == null) "Toca el mapa para fijarlas." else "Puedes editar si es necesario.",
        )
        CampoCoordenadaFila("Latitud (X)", "Latitud", estado.latitudTexto) {
            acciones.onEditarCoordenada(CampoCoordenada.LATITUD)
        }
        CampoCoordenadaFila("Longitud (Y)", "Longitud", estado.longitudTexto) {
            acciones.onEditarCoordenada(CampoCoordenada.LONGITUD)
        }
    }
}

@Composable
private fun CampoCoordenadaFila(etiqueta: String, nombre: String, valor: String, onEditar: () -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clip(forma)
            .background(C.SuperficieAlta)
            .border(1.dp, C.Primario.copy(alpha = 0.6f), forma)
            .clickable(role = Role.Button, onClickLabel = "Editar ${nombre.lowercase()}", onClick = onEditar)
            .padding(start = 12.dp, end = 8.dp, top = 6.dp, bottom = 6.dp)
            .semantics(mergeDescendants = true) { contentDescription = "$nombre: $valor" },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(etiqueta, color = C.TextoSecundario, fontSize = 12.sp)
            Text(valor, color = C.TextoPrincipal, fontSize = 17.sp, fontWeight = FontWeight.Medium, maxLines = 1)
        }
        Icon(Icons.Outlined.Edit, contentDescription = null, tint = C.Acento, modifier = Modifier.size(20.dp))
    }
}

@Composable
private fun DialogoCoordenada(
    edicion: EdicionCoordenada,
    onTexto: (String) -> Unit,
    onAceptar: () -> Unit,
    onCancelar: () -> Unit,
) {
    val esLatitud = edicion.campo == CampoCoordenada.LATITUD
    val limite = if (esLatitud) 90 else 180
    val foco = remember { FocusRequester() }
    LaunchedEffect(Unit) { foco.requestFocus() }

    AlertDialog(
        onDismissRequest = onCancelar,
        containerColor = C.SuperficieAlta,
        titleContentColor = C.TextoPrincipal,
        textContentColor = C.TextoSecundario,
        title = { Text(if (esLatitud) "Editar latitud" else "Editar longitud") },
        text = {
            OutlinedTextField(
                value = edicion.texto,
                onValueChange = onTexto,
                singleLine = true,
                isError = edicion.error,
                label = { Text(if (esLatitud) "Latitud" else "Longitud") },
                supportingText = {
                    Text(
                        if (edicion.error) "Escribe un número entre -$limite y $limite."
                        else "Usa punto o coma para los decimales.",
                    )
                },
                // Texto y no Decimal: el teclado numérico de algunos teléfonos no trae el signo «−»,
                // y en Colombia la longitud siempre es negativa.
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onAceptar() }),
                colors = colores(),
                modifier = Modifier.fillMaxWidth().focusRequester(foco),
            )
        },
        confirmButton = {
            TextButton(onClick = onAceptar, modifier = Modifier.heightIn(min = 48.dp)) {
                Text("Aplicar", color = C.Acento, fontSize = 16.sp)
            }
        },
        dismissButton = {
            TextButton(onClick = onCancelar, modifier = Modifier.heightIn(min = 48.dp)) {
                Text("Cancelar", color = C.TextoSecundario, fontSize = 16.sp)
            }
        },
    )
}

@Composable
private fun colores() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = C.TextoPrincipal,
    unfocusedTextColor = C.TextoPrincipal,
    focusedBorderColor = C.Acento,
    unfocusedBorderColor = C.Primario.copy(alpha = 0.7f),
    focusedLabelColor = C.Acento,
    unfocusedLabelColor = C.TextoSecundario,
    cursorColor = C.Acento,
    focusedSupportingTextColor = C.TextoSecundario,
    unfocusedSupportingTextColor = C.TextoSecundario,
)

// ── Última posición y nombre ────────────────────────────────────────────────────────

@Composable
private fun FilaUltimaPosicion(estado: UbicacionManualUiState, onClick: () -> Unit) {
    val forma = RoundedCornerShape(18.dp)
    val ultima = estado.ultimaPosicion
    val habilitada = ultima != null
    val subtitulo = when {
        estado.cargandoUltima -> "Buscando el video anterior…"
        ultima == null -> "Aún no hay un video anterior."
        estado.ultimaAplicada -> "Posición tomada de ${ultima.videoNombre}."
        else -> "Continúa desde el final del video anterior."
    }
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .clip(forma)
            .background(C.Primario.copy(alpha = 0.10f))
            .border(1.5.dp, C.Primario.copy(alpha = if (habilitada) 1f else 0.4f), forma)
            .clickable(enabled = habilitada, role = Role.Button, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp)
            .semantics(mergeDescendants = true) {
                contentDescription = "Usar mi última posición. $subtitulo"
                liveRegion = LiveRegionMode.Polite
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val alfa = if (habilitada) 1f else 0.5f
        Box(
            Modifier.size(48.dp).border(1.5.dp, C.Primario.copy(alpha = alfa), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.History, contentDescription = null, tint = C.Acento.copy(alpha = alfa), modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text("Usar mi última posición", color = C.Acento.copy(alpha = alfa), fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Text(subtitulo, color = C.TextoSecundario.copy(alpha = alfa), fontSize = 13.5.sp, lineHeight = 17.sp)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = C.Acento.copy(alpha = alfa))
    }
}

@Composable
private fun TarjetaNombreVideo(estado: UbicacionManualUiState, onNombre: (String) -> Unit) {
    val foco = LocalFocusManager.current
    Row(
        Modifier.fillMaxWidth().tarjeta().padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(48.dp).background(C.SuperficieAlta, CircleShape).border(1.5.dp, C.Primario, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.Videocam, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text("Nombre del video", color = C.TextoPrincipal, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                Spacer(Modifier.width(6.dp))
                Text("(opcional)", color = C.TextoSuave, fontSize = 12.sp)
            }
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = estado.nombreVideo,
                onValueChange = onNombre,
                singleLine = true,
                placeholder = { Text(estado.nombreSugerido, color = C.TextoSuave) },
                shape = RoundedCornerShape(14.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { foco.clearFocus() }),
                colors = colores(),
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
                    .semantics { contentDescription = "Nombre del video, opcional" },
            )
        }
    }
}

// ── Calibración de la longitud de paso (7.3b) ───────────────────────────────────────

@Composable
private fun FilaCalibracion(longitudCalibradaM: Double?, onClick: () -> Unit) {
    val forma = RoundedCornerShape(18.dp)
    val longitud = longitudCalibradaM ?: PdrEngine.LONGITUD_PASO_DEFECTO_M
    val valor = String.format(Locale("es", "CO"), "%.2f m", longitud)
    val subtitulo =
        if (longitudCalibradaM != null) "Longitud de paso en uso: $valor (calibrada)."
        else "Usando $valor (valor genérico). Calibra para mayor precisión."
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .clip(forma)
            .background(C.Primario.copy(alpha = 0.10f))
            .border(1.5.dp, C.Primario, forma)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp)
            .semantics(mergeDescendants = true) { contentDescription = "Calibrar mi paso. $subtitulo" },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(48.dp).border(1.5.dp, C.Primario, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.Straighten, contentDescription = null, tint = C.Acento, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text("Calibrar mi paso", color = C.Acento, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Text(subtitulo, color = C.TextoSecundario, fontSize = 13.5.sp, lineHeight = 17.sp)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = C.Acento)
    }
}

// ── Barra inferior ──────────────────────────────────────────────────────────────────

@Composable
private fun BarraAcciones(puedeConfirmar: Boolean, onCancelar: () -> Unit, onConfirmar: () -> Unit) {
    val forma = RoundedCornerShape(18.dp)
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            Modifier
                .weight(1f)
                .height(64.dp)
                .clip(forma)
                .border(BorderStroke(2.dp, ColorCancelar), forma)
                .clickable(role = Role.Button, onClick = onCancelar),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Outlined.Cancel, contentDescription = null, tint = ColorCancelar, modifier = Modifier.size(26.dp))
            Spacer(Modifier.width(8.dp))
            Text("Cancelar", color = ColorCancelar, fontSize = 17.sp, fontWeight = FontWeight.Medium)
        }
        Row(
            Modifier
                .weight(1.5f)
                .height(64.dp)
                .clip(forma)
                .background(C.Primario.copy(alpha = if (puedeConfirmar) 1f else 0.35f))
                .clickable(enabled = puedeConfirmar, role = Role.Button, onClick = onConfirmar)
                .padding(horizontal = 12.dp)
                .semantics {
                    if (!puedeConfirmar) stateDescription = "Falta marcar tu posición en el mapa"
                },
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Filled.Check, contentDescription = null, tint = C.TextoPrincipal, modifier = Modifier.size(26.dp))
            Spacer(Modifier.width(8.dp))
            Text(
                "Confirmar y comenzar",
                color = C.TextoPrincipal,
                fontSize = 16.sp,
                lineHeight = 19.sp,
                fontWeight = FontWeight.Medium,
                textAlign = TextAlign.Center,
                maxLines = 2,
                modifier = Modifier.weight(1f, fill = false),
            )
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = C.TextoPrincipal)
        }
    }
}

// ═════════════════════════════════════════════════════════════════════════════════════
//  Vistas previas (el mapa no se previsualiza: muestra un recuadro)
// ═════════════════════════════════════════════════════════════════════════════════════

private val PUNTO_PREVIEW = PuntoMapa(6.2006, -75.5783)

@Preview(showBackground = true, backgroundColor = 0xFF030615, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewConPunto() {
    UbicacionManualContent(
        estado = UbicacionManualUiState(
            punto = PUNTO_PREVIEW,
            rumbo = 45f,
            brujulaDisponible = true,
            cargandoUltima = false,
            ultimaPosicion = UltimaPosicion(PUNTO_PREVIEW, 90f, "video_2"),
            nombreVideo = "video_3",
            nombreSugerido = "video_3",
        ),
        acciones = UbicacionManualAcciones(),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF030615, widthDp = 360, heightDp = 900)
@Composable
private fun PreviewSinPunto() {
    UbicacionManualContent(
        estado = UbicacionManualUiState(
            cargandoUltima = false,
            nombreVideo = "video_1",
            nombreSugerido = "video_1",
        ),
        acciones = UbicacionManualAcciones(),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF030615, widthDp = 390, heightDp = 900)
@Composable
private fun PreviewEditandoLatitud() {
    UbicacionManualContent(
        estado = UbicacionManualUiState(
            punto = PUNTO_PREVIEW,
            cargandoUltima = false,
            nombreVideo = "video_3",
            nombreSugerido = "video_3",
            edicion = EdicionCoordenada(CampoCoordenada.LATITUD, "6,2006x", error = true),
        ),
        acciones = UbicacionManualAcciones(),
    )
}