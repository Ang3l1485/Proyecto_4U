package com.example.myapplication.ui.destino.componentes

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.outlined.LocationOn
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.ui.theme.CampusColors

// ============================================================================
// Encabezado
// ============================================================================

@Composable
fun BarraSuperior(onAtras: () -> Unit, onAjustes: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp)
            .heightIn(min = 64.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BotonIcono(Icons.AutoMirrored.Filled.ArrowBack, "Volver", onAtras)
        Text(
            text = "Destino",
            color = CampusColors.TextoPrincipal,
            fontSize = 22.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier
                .weight(1f)
                .padding(start = 4.dp),
        )
        BotonIcono(Icons.Outlined.Settings, "Ajustes", onAjustes)
    }
}

@Composable
fun EncabezadoPregunta() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Box(
            modifier = Modifier
                .size(72.dp)
                .clip(CircleShape)
                .background(CampusColors.SuperficieAlta)
                .border(1.dp, CampusColors.Borde, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Filled.LocationOn,
                contentDescription = null,
                tint = CampusColors.Acento,
                modifier = Modifier.size(40.dp),
            )
        }
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = "¿A dónde quieres ir?",
                color = CampusColors.TextoPrincipal,
                fontSize = 28.sp,
                lineHeight = 34.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                text = "Puedes decir el nombre del lugar o elegirlo de la lista.",
                color = CampusColors.TextoSecundario,
                fontSize = 18.sp,
                lineHeight = 24.sp,
            )
        }
    }
}

// ============================================================================
// Micrófono
// ============================================================================

/** Micrófono grande con halo (pulsa mientras escucha) y el texto de estado debajo. */
@Composable
fun ZonaMicrofono(escuchando: Boolean, onClick: () -> Unit) {
    val transicion = rememberInfiniteTransition(label = "pulso")
    val pulso by transicion.animateFloat(
        initialValue = 1f,
        targetValue = 1.08f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "escala",
    )
    val escala = if (escuchando) pulso else 1f

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(modifier = Modifier.size(200.dp), contentAlignment = Alignment.Center) {
            // Halos decorativos.
            Box(
                Modifier
                    .size(196.dp)
                    .scale(escala)
                    .border(1.dp, CampusColors.Borde.copy(alpha = 0.6f), CircleShape)
            )
            Box(
                Modifier
                    .size(168.dp)
                    .scale(escala)
                    .border(2.dp, CampusColors.Acento.copy(alpha = 0.35f), CircleShape)
            )
            // Botón.
            Box(
                modifier = Modifier
                    .size(144.dp)
                    .shadow(
                        elevation = 32.dp,
                        shape = CircleShape,
                        ambientColor = CampusColors.Primario,
                        spotColor = CampusColors.Primario,
                    )
                    .background(
                        Brush.radialGradient(
                            listOf(Color(0xFF7B5CFF), CampusColors.Primario, Color(0xFF3B24C9))
                        ),
                        CircleShape,
                    )
                    .border(2.dp, CampusColors.Acento, CircleShape)
                    .clip(CircleShape)
                    .clickable(role = Role.Button, onClick = onClick)
                    .semantics {
                        contentDescription =
                            if (escuchando) "Micrófono. Escuchando. Toca dos veces para detener."
                            else "Micrófono. Toca dos veces para decir el nombre del lugar."
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Filled.Mic,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(64.dp),
                )
            }
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        ) {
            if (escuchando) {
                Icon(
                    Icons.Filled.GraphicEq,
                    contentDescription = null,
                    tint = CampusColors.Acento,
                    modifier = Modifier.size(28.dp),
                )
            }
            Text(
                text = if (escuchando) "Escuchando…" else "Toca para hablar",
                color = if (escuchando) CampusColors.TextoSecundario else CampusColors.TextoSuave,
                fontSize = 20.sp,
            )
        }
    }
}

// ============================================================================
// Tarjetas de resultado de la voz
// ============================================================================

/** "Texto reconocido: “biblioteca”" con ✕ para descartarlo. */
@Composable
fun TarjetaTextoReconocido(texto: String, onDescartar: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .tarjeta()
            .padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(
            Icons.Filled.GraphicEq,
            contentDescription = null,
            tint = CampusColors.Acento,
            modifier = Modifier.size(32.dp),
        )
        Column(
            modifier = Modifier
                .weight(1f)
                .semantics(mergeDescendants = true) {},
        ) {
            Text("Texto reconocido:", color = CampusColors.TextoSuave, fontSize = 14.sp)
            Text(
                text = "“$texto”",
                color = CampusColors.TextoPrincipal,
                fontSize = 22.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        BotonIcono(Icons.Filled.Close, "Descartar texto reconocido", onDescartar, tint = CampusColors.TextoSecundario)
    }
}

/** "¿Quieres ir a X? Di sí o no." con botones Sí / No grandes. */
@Composable
fun TarjetaConfirmacion(lugar: LugarDestino, onSi: () -> Unit, onNo: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .tarjeta()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // TalkBack anuncia la pregunta al aparecer.
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.semantics(mergeDescendants = true) {
                liveRegion = LiveRegionMode.Polite
            },
        ) {
            Box(
                modifier = Modifier
                    .size(52.dp)
                    .clip(CircleShape)
                    .background(CampusColors.SuperficieAlta)
                    .border(1.dp, CampusColors.Borde, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Outlined.LocationOn,
                    contentDescription = null,
                    tint = CampusColors.Acento,
                    modifier = Modifier.size(28.dp),
                )
            }
            Column {
                Text(
                    text = "¿Quieres ir a ${lugar.nombre}?",
                    color = CampusColors.TextoPrincipal,
                    fontSize = 22.sp,
                    lineHeight = 28.sp,
                    fontWeight = FontWeight.Medium,
                )
                Text("Di sí o no.", color = CampusColors.TextoSecundario, fontSize = 18.sp)
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Button(
                onClick = onSi,
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 64.dp)
                    .semantics { contentDescription = "Sí, ir a ${lugar.nombre}" },
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = CampusColors.Primario,
                    contentColor = Color.White,
                ),
            ) {
                Text("Sí", fontSize = 22.sp, fontWeight = FontWeight.Medium)
            }
            OutlinedButton(
                onClick = onNo,
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 64.dp)
                    .semantics { contentDescription = "No, elegir otro lugar" },
                shape = RoundedCornerShape(16.dp),
                border = BorderStroke(1.5.dp, CampusColors.Primario),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = CampusColors.Acento),
            ) {
                Text("No", fontSize = 22.sp, fontWeight = FontWeight.Medium)
            }
        }
    }
}

/** Varias coincidencias: se listan para que la persona elija una. */
@Composable
fun TarjetaOpciones(opciones: List<LugarDestino>, onElegir: (LugarDestino) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .tarjeta()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            text = "Encontré varios lugares. ¿Cuál quieres?",
            color = CampusColors.TextoPrincipal,
            fontSize = 20.sp,
            lineHeight = 26.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        )
        opciones.forEach { lugar ->
            OutlinedButton(
                onClick = { onElegir(lugar) },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp),
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, CampusColors.Borde),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = CampusColors.TextoPrincipal),
            ) {
                Icon(
                    lugar.categoria.icono(),
                    contentDescription = null,
                    tint = CampusColors.Acento,
                    modifier = Modifier.size(22.dp),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    text = lugar.nombre,
                    fontSize = 18.sp,
                    textAlign = TextAlign.Start,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}
