package com.example.myapplication.ui.admin.recoleccion.componentes

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.myapplication.domain.usecase.EstimacionDeriva
import com.example.myapplication.domain.usecase.ModoCaptura
import com.example.myapplication.domain.usecase.NivelCalidad
import com.example.myapplication.ui.admin.recoleccion.AvisoRecoleccion
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import java.util.Locale
import kotlin.math.roundToInt

/**
 * Piezas de la pantalla 7.4 (`RecoleccionScreen`). Reutilizan `Modifier.tarjeta` y `CampusColors`.
 * ⚠ `ColorFinalizar` replica el rosa `#FF4D7D` de 7.3 (`CampusColors.Peligro` es morado); cuando
 * ese color suba a `CampusColors` (regla 4 de 11), reemplazar ambos.
 */
internal val ColorFinalizar = Color(0xFFFF4D7D)
internal val ColorAviso = Color(0xFFF59E0B)

// ── Formatos (puros) ────────────────────────────────────────────────────────────────────────────

internal fun formatearDistancia(metros: Double): String =
    if (metros < 1000) "${metros.roundToInt()} m"
    else String.format(Locale.getDefault(), "%.2f km", metros / 1000)

internal fun formatearDuracion(segundos: Long): String {
    val s = segundos.coerceAtLeast(0)
    val h = s / 3600
    val m = (s % 3600) / 60
    val ss = s % 60
    return if (h > 0) String.format(Locale.US, "%d:%02d:%02d", h, m, ss)
    else String.format(Locale.US, "%02d:%02d", m, ss)
}

// ── Encabezado ──────────────────────────────────────────────────────────────────────────────────

@Composable
internal fun ChipEstadoVideo(enPausa: Boolean) {
    val color = if (enPausa) ColorAviso else CampusColors.Exito
    Text(
        text = if (enPausa) "En pausa" else "En curso",
        color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium,
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(color.copy(alpha = .14f))
            .padding(horizontal = 10.dp, vertical = 3.dp),
    )
}

// ── Contadores ──────────────────────────────────────────────────────────────────────────────────

@Composable
internal fun TarjetaContador(icono: ImageVector, etiqueta: String, valor: String, modifier: Modifier = Modifier, sufijo: String? = null) {
    Column(
        modifier = modifier.tarjeta(16.dp).padding(12.dp)
            .semantics(mergeDescendants = true) { contentDescription = "$etiqueta: $valor${sufijo.orEmpty()}" },
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(icono, contentDescription = null, tint = CampusColors.Acento, modifier = Modifier.size(24.dp))
        Text(etiqueta, color = CampusColors.TextoSuave, fontSize = 12.sp, maxLines = 2)
        Row(verticalAlignment = Alignment.Bottom) {
            Text(valor, color = CampusColors.TextoPrincipal, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
            if (sufijo != null) Text(sufijo, color = CampusColors.TextoSuave, fontSize = 13.sp, modifier = Modifier.padding(start = 2.dp, bottom = 2.dp))
        }
    }
}

// ── Calidad del seguimiento ─────────────────────────────────────────────────────────────────────

@Composable
internal fun TarjetaCalidad(deriva: EstimacionDeriva, icono: ImageVector, modifier: Modifier = Modifier) {
    val (texto, color) = when (deriva.nivel) {
        NivelCalidad.ALTA -> "Alta" to CampusColors.Exito
        NivelCalidad.MEDIA -> "Media" to ColorAviso
        NivelCalidad.BAJA -> "Baja" to ColorFinalizar
    }
    val precision = formatearDistancia(deriva.precisionM.toDouble())
    val derivaTxt = formatearDistancia(deriva.derivaM.toDouble())
    Row(
        modifier = modifier.fillMaxWidth().tarjeta(20.dp).padding(14.dp)
            .semantics(mergeDescendants = true) {
                contentDescription = "Calidad del seguimiento $texto, precisión estimada $precision, deriva acumulada $derivaTxt"
            },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icono, null, tint = CampusColors.Acento, modifier = Modifier.size(32.dp))
        Column(Modifier.weight(1f)) {
            Text("Calidad del seguimiento", color = CampusColors.TextoPrincipal, fontSize = 15.sp, fontWeight = FontWeight.Medium)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    texto, color = color, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(color.copy(alpha = .16f)).padding(horizontal = 10.dp, vertical = 2.dp),
                )
                Text("± $precision", color = CampusColors.TextoSuave, fontSize = 12.sp)
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("Deriva acumulada", color = CampusColors.TextoSuave, fontSize = 12.sp)
            Text(derivaTxt, color = CampusColors.TextoPrincipal, fontSize = 17.sp, fontWeight = FontWeight.Medium)
        }
    }
}

// ── Captura automática ──────────────────────────────────────────────────────────────────────────

@Composable
internal fun TarjetaCaptura(modo: ModoCaptura, fotoTomada: Boolean, icono: ImageVector, enPausa: Boolean, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().tarjeta(20.dp).padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icono, null, tint = CampusColors.Acento, modifier = Modifier.size(32.dp))
        Column(Modifier.weight(1f)) {
            Text("Captura automática", color = CampusColors.TextoPrincipal, fontSize = 15.sp, fontWeight = FontWeight.Medium)
            Text(
                if (enPausa) "En pausa" else "Tomando fotos cada ${modo.etiqueta}",
                color = CampusColors.TextoSuave, fontSize = 13.sp,
            )
        }
        if (fotoTomada) {
            // La pantalla lo marca 1 s tras cada foto; liveRegion para que TalkBack lo anuncie.
            Row(
                Modifier.clip(RoundedCornerShape(50)).background(CampusColors.Primario.copy(alpha = .25f))
                    .padding(horizontal = 12.dp, vertical = 6.dp)
                    .semantics { liveRegion = LiveRegionMode.Polite },
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(Icons.Filled.AutoAwesome, null, tint = CampusColors.Acento, modifier = Modifier.size(16.dp))
                Text("Foto tomada", color = CampusColors.TextoSecundario, fontSize = 13.sp)
            }
        }
    }
}

// ── Botones ─────────────────────────────────────────────────────────────────────────────────────

@Composable
internal fun BotonAccion(
    icono: ImageVector, texto: String, onClick: () -> Unit, modifier: Modifier = Modifier,
    primario: Boolean = false, habilitado: Boolean = true, nota: String? = null,
) {
    val forma = RoundedCornerShape(16.dp)
    Column(
        modifier = modifier.heightIn(min = 76.dp).clip(forma)
            .background(if (primario) CampusColors.Primario else CampusColors.Superficie)
            .then(if (primario) Modifier else Modifier.tarjeta(16.dp))
            .alpha(if (habilitado) 1f else .5f)
            .clickable(enabled = habilitado, role = Role.Button, onClick = onClick)
            .semantics { if (nota != null) stateDescription = nota }
            .padding(10.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(icono, null, tint = if (primario) Color.White else CampusColors.Acento, modifier = Modifier.size(26.dp))
        Spacer(Modifier.size(4.dp))
        Text(texto, color = CampusColors.TextoPrincipal, fontSize = 13.sp, textAlign = TextAlign.Center, lineHeight = 16.sp)
    }
}

@Composable
internal fun FilaAccion(icono: ImageVector, titulo: String, subtitulo: String? = null, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).tarjeta(16.dp)
            .clickable(role = Role.Button, onClick = onClick).heightIn(min = 56.dp).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icono, null, tint = CampusColors.Acento, modifier = Modifier.size(26.dp))
        Column(Modifier.weight(1f)) {
            Text(titulo, color = CampusColors.TextoPrincipal, fontSize = 15.sp)
            if (subtitulo != null) Text(subtitulo, color = CampusColors.TextoSuave, fontSize = 13.sp)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = CampusColors.TextoSuave)
    }
}

@Composable
internal fun BotonFinalizar(onClick: () -> Unit, habilitado: Boolean, modifier: Modifier = Modifier) {
    Button(
        onClick = onClick, enabled = habilitado,
        modifier = modifier.fillMaxWidth().heightIn(min = 56.dp),
        shape = RoundedCornerShape(16.dp),
        colors = ButtonDefaults.buttonColors(containerColor = ColorFinalizar, contentColor = Color.White),
    ) {
        Icon(Icons.Filled.Stop, null, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(10.dp))
        Text("Finalizar video", fontSize = 16.sp, fontWeight = FontWeight.Medium)
    }
}

// ── Re-anclaje ──────────────────────────────────────────────────────────────────────────────────

@Composable
internal fun PanelReanclaje(onConfirmar: () -> Unit, onCancelar: () -> Unit, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().tarjeta(20.dp).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Reubicarte en el mapa", color = CampusColors.TextoPrincipal, fontSize = 15.sp, fontWeight = FontWeight.Medium)
        Text(
            "Arrastra el alfiler rosa (o toca el mapa) hasta tu posición real. Las fotos y la ruta desde la última corrección se desplazarán igual. Las capturas se detienen mientras tanto.",
            color = CampusColors.TextoSuave, fontSize = 13.sp,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                onClick = onCancelar, modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                border = BorderStroke(1.dp, ColorFinalizar),
            ) { Text("Cancelar", color = ColorFinalizar) }
            Button(
                onClick = onConfirmar, modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                colors = ButtonDefaults.buttonColors(containerColor = CampusColors.Primario, contentColor = Color.White),
            ) { Text("Confirmar posición") }
        }
    }
}

// ── Alertas ─────────────────────────────────────────────────────────────────────────────────────

@Composable
internal fun FilaAlertasCercanas(activas: Int, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().tarjeta(16.dp).padding(horizontal = 14.dp, vertical = 12.dp)
            .semantics(mergeDescendants = true) {},
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Filled.Warning, null, tint = ColorFinalizar)
        Text("Alertas cercanas", color = ColorFinalizar, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Icon(Icons.Filled.Notifications, null, tint = CampusColors.TextoSuave, modifier = Modifier.size(20.dp))
        Text("Alertas activas: $activas", color = CampusColors.TextoPrincipal, fontSize = 14.sp)
    }
}

/** Los cuatro avisos de 7.4; se iluminan solo los activos (`ui.avisos`). */
@Composable
internal fun PanelAvisos(activos: Set<AvisoRecoleccion>, modifier: Modifier = Modifier) {
    val todos = listOf(
        AvisoRecoleccion.FOTO_BORROSA to "Foto borrosa",
        AvisoRecoleccion.POCA_LUZ to "Poca luz",
        AvisoRecoleccion.BATERIA_BAJA to "Batería baja",
        AvisoRecoleccion.ALMACENAMIENTO_BAJO to "Almacenamiento bajo",
    )
    Column(modifier.fillMaxWidth().tarjeta(16.dp).padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Alertas", color = CampusColors.TextoPrincipal, fontSize = 15.sp, fontWeight = FontWeight.Medium)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            todos.forEach { (aviso, texto) ->
                val activo = aviso in activos
                val color = if (activo) ColorAviso else CampusColors.TextoSuave
                Row(
                    Modifier.clip(RoundedCornerShape(50)).background(CampusColors.SuperficieAlta)
                        .then(if (activo) Modifier.background(ColorAviso.copy(alpha = .12f)) else Modifier)
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                        .semantics(mergeDescendants = true) { stateDescription = if (activo) "Activa" else "Sin problema" },
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(Icons.Filled.Warning, null, tint = color, modifier = Modifier.size(16.dp))
                    Text(texto, color = if (activo) CampusColors.TextoPrincipal else CampusColors.TextoSuave, fontSize = 13.sp)
                }
            }
        }
    }
}