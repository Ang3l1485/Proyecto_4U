package com.example.myapplication.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

enum class TipoBanner(val acento: Color, val fondo: Color) {
    Error(acento = Color(0xFFFF4D6A), fondo = Color(0xFF1B0A17)),
    Advertencia(acento = Color(0xFFFFB02E), fondo = Color(0xFF1B1407)),
}

/** Banner de estado accesible: TalkBack lo anuncia al aparecer (live region asertiva). */
@Composable
fun BannerEstado(
    tipo: TipoBanner,
    icono: ImageVector,
    titulo: String,
    mensaje: String,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Assertive },
        shape = RoundedCornerShape(18.dp),
        color = tipo.fondo,
        border = BorderStroke(1.dp, tipo.acento.copy(alpha = 0.85f)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icono, contentDescription = null, tint = tipo.acento, modifier = Modifier.size(32.dp))
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(titulo, color = tipo.acento, fontSize = 18.sp, fontWeight = FontWeight.Medium)
                Text(mensaje, color = Color(0xFFD9DCF2), fontSize = 16.sp, lineHeight = 22.sp)
            }
        }
    }
}