package com.example.myapplication.ui.ubicacion.componentes

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.myapplication.ui.ubicacion.EscaneoColores.Fondo
import com.example.myapplication.ui.ubicacion.EscaneoColores.Morado
import com.example.myapplication.ui.ubicacion.EscaneoColores.MoradoClaro
import com.example.myapplication.ui.ubicacion.EscaneoColores.Panel
import com.example.myapplication.ui.ubicacion.EscaneoColores.Pista
import com.example.myapplication.ui.ubicacion.EscaneoColores.TextoSecundario
import com.example.myapplication.ui.ubicacion.EscaneoConfig.GRADOS_POR_FOTO
import com.example.myapplication.ui.ubicacion.EscaneoConfig.TOTAL_FOTOS
import com.example.myapplication.ui.ubicacion.EscaneoUiState
import com.example.myapplication.ui.ubicacion.Fase
import kotlin.math.cos
import kotlin.math.sin

/**
 * Anillo de 0° a 360° (sentido horario desde arriba) con una marca por foto.
 *
 * Capas, de abajo hacia arriba:
 *  1. Pista gris del círculo completo.
 *  2. Arco morado = grados girados hasta ahora.
 *  3. Marcas: llenas con check si la foto ya se tomó; vacías si falta.
 *  4. Etiquetas 0° / 90° / 180° / 270°.
 *  5. Centro: "Foto X de 5" o "Analizando…".
 */
@Composable
internal fun AnilloProgreso(estado: EscaneoUiState) {
    // La foto "actual" es la siguiente por tomar (sin pasarse del total).
    val fotoActual = (estado.fotos + 1).coerceAtMost(TOTAL_FOTOS)

    Box(
        modifier = Modifier
            .size(width = 270.dp, height = 240.dp)
            // Para TalkBack se anuncia el progreso en lugar de los elementos de dibujo.
            .semantics { contentDescription = "Foto $fotoActual de $TOTAL_FOTOS" },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(190.dp)) {
            val trazo = 10.dp.toPx()
            val r = size.minDimension / 2f - 16.dp.toPx()
            val c = center

            // 1) Pista
            drawCircle(Pista, radius = r, center = c, style = Stroke(trazo))

            // 2) Progreso del giro
            if (estado.progreso > 0f) {
                drawArc(
                    color = Morado,
                    startAngle = -90f, // las 12 en punto
                    sweepAngle = estado.progreso,
                    useCenter = false,
                    topLeft = Offset(c.x - r, c.y - r),
                    size = Size(r * 2, r * 2),
                    style = Stroke(trazo, cap = StrokeCap.Round),
                )
            }

            // 3) Una marca por foto, cada GRADOS_POR_FOTO (72°)
            repeat(TOTAL_FOTOS) { i ->
                val a = Math.toRadians(-90.0 + i * GRADOS_POR_FOTO)
                val p = Offset(c.x + r * cos(a).toFloat(), c.y + r * sin(a).toFloat())
                if (i < estado.fotos) marcaCompletada(p) else marcaPendiente(p)
            }
        }

        // 4) Etiquetas de grados
        listOf(
            "0°" to Alignment.TopCenter,
            "90°" to Alignment.CenterEnd,
            "180°" to Alignment.BottomCenter,
            "270°" to Alignment.CenterStart,
        ).forEach { (txt, pos) ->
            Text(txt, color = TextoSecundario, fontSize = 14.sp, modifier = Modifier.align(pos))
        }

        // 5) Centro
        Column(
            modifier = Modifier.size(118.dp).clip(CircleShape).background(Panel),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            if (estado.fase == Fase.ANALIZANDO) {
                CircularProgressIndicator(color = Morado, modifier = Modifier.size(34.dp), strokeWidth = 3.dp)
                Spacer(Modifier.height(8.dp))
                Text("Analizando…", color = Color.White, fontSize = 14.sp, textAlign = TextAlign.Center)
            } else {
                Icon(Icons.Default.CameraAlt, null, tint = MoradoClaro, modifier = Modifier.size(34.dp))
                Spacer(Modifier.height(6.dp))
                Text("Foto $fotoActual de $TOTAL_FOTOS", color = Color.White, fontSize = 15.sp)
            }
        }
    }
}

/** Marca de foto ya tomada: círculo morado con un check blanco dibujado a mano. */
private fun DrawScope.marcaCompletada(p: Offset) {
    drawCircle(Morado, radius = 12.dp.toPx(), center = p)
    drawCircle(MoradoClaro, radius = 12.dp.toPx(), center = p, style = Stroke(2.dp.toPx()))
    val d = 1.dp.toPx()
    val w = 2.dp.toPx()
    // Dos segmentos forman el check: el corto (bajando) y el largo (subiendo).
    drawLine(Color.White, Offset(p.x - 4 * d, p.y), Offset(p.x - 1.5f * d, p.y + 3 * d), w, StrokeCap.Round)
    drawLine(Color.White, Offset(p.x - 1.5f * d, p.y + 3 * d), Offset(p.x + 4.5f * d, p.y - 3 * d), w, StrokeCap.Round)
}

/** Marca de foto pendiente: círculo vacío con borde gris. */
private fun DrawScope.marcaPendiente(p: Offset) {
    drawCircle(Fondo, radius = 10.dp.toPx(), center = p)
    drawCircle(Pista, radius = 10.dp.toPx(), center = p, style = Stroke(2.dp.toPx()))
}