package com.example.myapplication.ui.admin.calibracion

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.usecase.CalibracionPaso
import com.example.myapplication.domain.usecase.MotivoInvalido
import com.example.myapplication.domain.usecase.ResultadoCalibracion
import com.example.myapplication.sensors.PdrEngine
import com.example.myapplication.ui.admin.calibracion.componentes.CalibracionMapaContent
import com.example.myapplication.ui.admin.calibracion.componentes.CalibracionMapaEventos
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import java.util.Locale

// CampusColors.Peligro es morado (11.4): estos dos son propios, como en 7.4.
private val ColorFin = Color(0xFFFF4D7D)
private val ColorAviso = Color(0xFFF59E0B)

/** Lambdas de la pantalla (`{}` por defecto para previews). */
data class CalibracionAcciones(
    val onVolver: () -> Unit = {},
    val onToque: (Double, Double) -> Unit = { _, _ -> },
    val onPuntoMovido: (ExtremoTramo, Double, Double) -> Unit = { _, _, _ -> },
    val onLimpiar: () -> Unit = {},
    val onIniciar: () -> Unit = {},
    val onFinalizar: () -> Unit = {},
    val onCancelarMedicion: () -> Unit = {},
    val onRepetir: () -> Unit = {},
    val onGuardar: () -> Unit = {},
    val onRestablecer: () -> Unit = {},
    val onDescartarAviso: () -> Unit = {},
)

/**
 * Vista 7.3b — Calibración de la longitud de paso. **No navega**: la ruta decide qué hace `onVolver`.
 * La ruta debe pedir `ACTIVITY_RECOGNITION` antes de mostrarla (`Permisos.ACTIVIDAD`, 11.8).
 */
@Composable
fun CalibracionScreen(
    onVolver: () -> Unit,
    modifier: Modifier = Modifier,
    vm: CalibracionViewModel = viewModel(),
) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    val caminando = ui.fase == FaseCalibracion.CAMINANDO

    // Los sensores no siguen el ciclo de vida: ON_STOP detiene el tracker y cancela la medición.
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observador = LifecycleEventObserver { _, evento ->
            if (evento == Lifecycle.Event.ON_STOP) vm.alIrASegundoPlano()
        }
        owner.lifecycle.addObserver(observador)
        onDispose { owner.lifecycle.removeObserver(observador) }
    }

    val vista = LocalView.current
    DisposableEffect(caminando) {
        vista.keepScreenOn = caminando
        onDispose { vista.keepScreenOn = false }
    }

    BackHandler { if (caminando) vm.alCancelarMedicion() else onVolver() }

    CalibracionContent(
        ui = ui,
        acciones = CalibracionAcciones(
            onVolver = onVolver,
            onToque = vm::alTocarMapa,
            onPuntoMovido = vm::alMoverPunto,
            onLimpiar = vm::alLimpiarPuntos,
            onIniciar = vm::alIniciar,
            onFinalizar = vm::alFinalizar,
            onCancelarMedicion = vm::alCancelarMedicion,
            onRepetir = vm::alRepetir,
            onGuardar = vm::alGuardar,
            onRestablecer = vm::alRestablecer,
            onDescartarAviso = vm::descartarAviso,
        ),
        modifier = modifier,
    )
}

@Composable
internal fun CalibracionContent(
    ui: CalibracionUiState,
    acciones: CalibracionAcciones,
    modifier: Modifier = Modifier,
) {
    // Sin scroll: el mapa ocupa el espacio que sobra (un WebView dentro de un scroll vertical
    // se pelea con el arrastre del mapa; 7.3 lo resuelve con `gesto()`, aquí se evita).
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CampusColors.Fondo)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        BarraCalibracion(ui, acciones)

        ui.aviso?.let { TarjetaAviso(textoAviso(it), ColorAviso, acciones.onDescartarAviso) }
        if (ui.pasosPorAcelerometro) {
            TarjetaAviso(
                "Los pasos se cuentan con el acelerómetro (sin permiso de actividad física o sin " +
                    "sensor). Calibra con el mismo método con el que vas a recolectar.",
                ColorAviso,
            )
        }

        TarjetaInstruccion(ui)

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .heightIn(min = 180.dp)
                .clip(RoundedCornerShape(20.dp))
                .border(1.dp, CampusColors.Borde, RoundedCornerShape(20.dp)),
        ) {
            CalibracionMapaContent(
                puntoA = ui.puntoA,
                puntoB = ui.puntoB,
                bloqueado = ui.mapaBloqueado,
                eventos = CalibracionMapaEventos(
                    onToque = acciones.onToque,
                    onPuntoMovido = acciones.onPuntoMovido,
                ),
                modifier = Modifier.fillMaxSize(),
            )
        }

        when (ui.fase) {
            FaseCalibracion.PUNTOS -> {
                FilaDatos(ui)
                BotonSecundario("Limpiar puntos", acciones.onLimpiar, enabled = ui.hayPuntos)
            }
            FaseCalibracion.LISTO -> {
                FilaDatos(ui)
                BotonGrande("Inicio", acciones.onIniciar, CampusColors.Primario)
                TextButton(onClick = acciones.onLimpiar, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                    Text("Limpiar puntos", color = CampusColors.Acento, fontSize = 16.sp)
                }
            }
            FaseCalibracion.CAMINANDO -> {
                FilaDatos(ui)
                BotonGrande("Fin", acciones.onFinalizar, ColorFin)
                TextButton(onClick = acciones.onCancelarMedicion, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                    Text("Cancelar medición", color = CampusColors.Acento, fontSize = 16.sp)
                }
            }
            FaseCalibracion.RESULTADO -> PanelResultado(ui, acciones)
            FaseCalibracion.GUARDADA -> {
                TarjetaTexto(
                    titulo = "Guardada: ${m2(ui.longitudActualM)}",
                    detalle = "La recolección calculará los metros como pasos × esta longitud. " +
                        "Camina igual que en la calibración.",
                    colorTitulo = CampusColors.Exito,
                )
                BotonGrande("Listo", acciones.onVolver, CampusColors.Primario)
            }
        }
    }
}

// ── Piezas ────────────────────────────────────────

@Composable
private fun BarraCalibracion(ui: CalibracionUiState, acciones: CalibracionAcciones) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        BotonIcono(
            icono = Icons.AutoMirrored.Filled.ArrowBack,
            descripcion = "Volver",
            onClick = acciones.onVolver,
        )
        Column(Modifier.weight(1f)) {
            Text(
                "Calibrar longitud de paso",
                color = CampusColors.TextoPrincipal,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "En uso: ${m2(ui.longitudActualM)} (${if (ui.calibrada) "calibrada" else "genérica"})",
                color = CampusColors.TextoSuave,
                fontSize = 14.sp,
            )
        }
        if (ui.calibrada && ui.fase != FaseCalibracion.CAMINANDO) {
            TextButton(onClick = acciones.onRestablecer) {
                Text("Restablecer", color = CampusColors.Acento, fontSize = 15.sp)
            }
        }
    }
}

@Composable
private fun TarjetaInstruccion(ui: CalibracionUiState) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .tarjeta()
            .padding(14.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(textoInstruccion(ui), color = CampusColors.TextoPrincipal, fontSize = 16.sp)
        if (ui.fase == FaseCalibracion.PUNTOS || ui.fase == FaseCalibracion.LISTO) {
            Text(
                "Mejor un tramo de ${CalibracionPaso.DISTANCIA_RECOMENDADA_M.toInt()} m o más " +
                    "(mínimo ${CalibracionPaso.MIN_DISTANCIA_M.toInt()} m).",
                color = CampusColors.TextoSuave,
                fontSize = 13.sp,
            )
        }
    }
}

@Composable
private fun FilaDatos(ui: CalibracionUiState) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Dato("Tramo", ui.distanciaM?.let(::m1) ?: "—", Modifier.weight(1f))
        Dato("Pasos", if (ui.fase == FaseCalibracion.CAMINANDO) ui.pasos.toString() else "—", Modifier.weight(1f))
        Dato("Tiempo", if (ui.fase == FaseCalibracion.CAMINANDO) mmss(ui.segundos) else "—", Modifier.weight(1f))
    }
}

@Composable
private fun Dato(etiqueta: String, valor: String, modifier: Modifier) {
    Column(
        modifier = modifier
            .tarjeta()
            .padding(vertical = 10.dp, horizontal = 8.dp)
            .semantics(mergeDescendants = true) {},
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(valor, color = CampusColors.TextoPrincipal, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text(etiqueta, color = CampusColors.TextoSuave, fontSize = 13.sp)
    }
}

@Composable
private fun PanelResultado(ui: CalibracionUiState, acciones: CalibracionAcciones) {
    when (val r = ui.resultado) {
        is ResultadoCalibracion.Valido -> {
            TarjetaTexto(
                titulo = "Longitud de paso: ${m2(r.longitudPasoM)}",
                detalle = "${r.pasos} pasos en ${m1(r.distanciaM)}.\n" +
                    "Solo informativo: cadencia ${Math.round(r.cadenciaPpm)} pasos/min, " +
                    "velocidad ${String.format(ES, "%.1f", r.velocidadMps)} m/s.\n" +
                    "Al recolectar, camina igual que en esta medición.",
                colorTitulo = CampusColors.Exito,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                BotonSecundario("Repetir", acciones.onRepetir, Modifier.weight(1f))
                BotonGrande("Guardar", acciones.onGuardar, CampusColors.Primario, Modifier.weight(1f))
            }
        }
        is ResultadoCalibracion.Invalido -> {
            TarjetaTexto(
                titulo = "No se pudo usar esta medición",
                detalle = textoMotivo(r),
                colorTitulo = ColorAviso,
            )
            BotonGrande("Repetir", acciones.onRepetir, CampusColors.Primario)
        }
        null -> BotonGrande("Repetir", acciones.onRepetir, CampusColors.Primario)
    }
}

@Composable
private fun TarjetaTexto(titulo: String, detalle: String, colorTitulo: Color) {
    Column(
        modifier = Modifier.fillMaxWidth().tarjeta().padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(titulo, color = colorTitulo, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text(detalle, color = CampusColors.TextoSecundario, fontSize = 14.sp)
    }
}

@Composable
private fun TarjetaAviso(texto: String, color: Color, onDescartar: (() -> Unit)? = null) {
    val forma = RoundedCornerShape(16.dp)
    Text(
        text = texto,
        color = CampusColors.TextoPrincipal,
        fontSize = 14.sp,
        modifier = Modifier
            .fillMaxWidth()
            .clip(forma)
            .border(1.dp, color, forma)
            .then(if (onDescartar != null) Modifier.clickable(onClick = onDescartar) else Modifier)
            .padding(12.dp),
    )
}

@Composable
private fun BotonGrande(
    texto: String,
    onClick: () -> Unit,
    color: Color,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.fillMaxWidth().heightIn(min = 60.dp),
        shape = RoundedCornerShape(18.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = color,
            contentColor = Color.White,
            disabledContainerColor = CampusColors.SuperficieAlta,
            disabledContentColor = CampusColors.TextoSuave,
        ),
    ) { Text(texto, fontSize = 18.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center) }
}

@Composable
private fun BotonSecundario(
    texto: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.fillMaxWidth().heightIn(min = 60.dp),
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, CampusColors.Borde),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = CampusColors.TextoPrincipal,
            disabledContentColor = CampusColors.TextoSuave,
        ),
    ) { Text(texto, fontSize = 17.sp, fontWeight = FontWeight.SemiBold) }
}

// ── Textos y formato ──────────────────────────────

private val ES: Locale = Locale.forLanguageTag("es-CO")
private fun m1(v: Double) = String.format(ES, "%.1f m", v)
private fun m2(v: Double) = String.format(ES, "%.2f m", v)
private fun mmss(s: Int) = String.format(Locale.US, "%d:%02d", s / 60, s % 60)

private fun textoInstruccion(ui: CalibracionUiState): String = when (ui.fase) {
    FaseCalibracion.PUNTOS ->
        if (ui.puntoA == null) "Toca el mapa donde empieza el tramo (A)."
        else "Ahora toca donde termina el tramo (B)."
    FaseCalibracion.LISTO ->
        "Párate en A, toca Inicio y camina hasta B como lo harás al recolectar. Puedes arrastrar A y B para ajustarlos."
    FaseCalibracion.CAMINANDO -> "Camina hasta B a tu ritmo normal y toca Fin al llegar."
    FaseCalibracion.RESULTADO ->
        if (ui.resultado is ResultadoCalibracion.Valido) "Medición lista. Revisa el resultado y guárdalo."
        else "Esta medición no sirve."
    FaseCalibracion.GUARDADA -> "Longitud de paso guardada."
}

private fun textoMotivo(r: ResultadoCalibracion.Invalido): String {
    val rango = "${String.format(ES, "%.2f", CalibracionPaso.MIN_PASO_M)} a " +
        "${String.format(ES, "%.2f", CalibracionPaso.MAX_PASO_M)} m"
    val sale = r.longitudPasoM?.let { "Salió un paso de ${m2(it)} (lo normal: $rango). " } ?: ""
    return when (r.motivo) {
        MotivoInvalido.TRAMO_CORTO ->
            "El tramo es muy corto. Marca uno de al menos ${CalibracionPaso.MIN_DISTANCIA_M.toInt()} m."
        MotivoInvalido.POCOS_PASOS ->
            "Se contaron muy pocos pasos (mínimo ${CalibracionPaso.MIN_PASOS}). Camina un tramo más " +
                "largo y revisa el permiso de actividad física."
        MotivoInvalido.PASO_MUY_CORTO ->
            sale + "El contador sumó pasos de más: repite sin agitar el teléfono."
        MotivoInvalido.PASO_MUY_LARGO ->
            sale + "Faltaron pasos o A y B están mal marcados: revísalos y repite."
    }
}

private fun textoAviso(a: AvisoCalibracion): String = when (a) {
    AvisoCalibracion.CANCELADA_SEGUNDO_PLANO ->
        "La medición se canceló porque saliste de la app. Vuelve a tocar Inicio."
    AvisoCalibracion.VALOR_RESTABLECIDO ->
        "Se restableció la longitud genérica (${m2(PdrEngine.LONGITUD_PASO_DEFECTO_M)})."
}

// ── Previews ──────────────────────────────────────

private val PREVIEW_A = PuntoTramo(6.2006, -75.5783)
private val PREVIEW_B = PuntoTramo(6.2009, -75.5783)

@Preview(showBackground = true, heightDp = 780)
@Composable
private fun PreviewListo() {
    CalibracionContent(
        ui = CalibracionUiState(
            fase = FaseCalibracion.LISTO, puntoA = PREVIEW_A, puntoB = PREVIEW_B,
            distanciaM = 33.4, longitudActualM = 0.72, calibrada = false,
        ),
        acciones = CalibracionAcciones(),
    )
}

@Preview(showBackground = true, heightDp = 780)
@Composable
private fun PreviewResultado() {
    CalibracionContent(
        ui = CalibracionUiState(
            fase = FaseCalibracion.RESULTADO, puntoA = PREVIEW_A, puntoB = PREVIEW_B,
            distanciaM = 33.4, pasos = 49, segundos = 31, longitudActualM = 0.72, calibrada = false,
            resultado = CalibracionPaso.calcular(33.4, 49, 31.0),
        ),
        acciones = CalibracionAcciones(),
    )
}