package com.example.myapplication.ui.destino.componentes

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.MenuBook
import androidx.compose.material.icons.outlined.AccountBalance
import androidx.compose.material.icons.outlined.Apartment
import androidx.compose.material.icons.outlined.LocalCafe
import androidx.compose.material.icons.outlined.MeetingRoom
import androidx.compose.material.icons.outlined.SportsSoccer
import androidx.compose.material.icons.outlined.TheaterComedy
import androidx.compose.material.icons.outlined.Wc
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.ui.theme.CampusColors

/** Fondo de tarjeta con borde fino, como las tarjetas del diseño. */
internal fun Modifier.tarjeta(radio: Dp = 20.dp): Modifier {
    val forma = RoundedCornerShape(radio)
    return this
        .clip(forma)
        .background(CampusColors.Superficie)
        .border(1.dp, CampusColors.Borde, forma)
}

/** Ícono de cada categoría (el dominio no conoce Compose, por eso vive aquí). */
internal fun CategoriaLugar.icono(): ImageVector = when (this) {
    CategoriaLugar.BIBLIOTECA -> Icons.AutoMirrored.Outlined.MenuBook
    CategoriaLugar.CAFETERIA -> Icons.Outlined.LocalCafe
    CategoriaLugar.BANO -> Icons.Outlined.Wc
    CategoriaLugar.BLOQUE -> Icons.Outlined.Apartment
    CategoriaLugar.AUDITORIO -> Icons.Outlined.TheaterComedy
    CategoriaLugar.DEPORTES -> Icons.Outlined.SportsSoccer
    CategoriaLugar.ADMINISTRACION -> Icons.Outlined.AccountBalance
    CategoriaLugar.ENTRADA -> Icons.Outlined.MeetingRoom
}

/** Botón circular de solo ícono con área táctil de 56 dp. */
@Composable
internal fun BotonIcono(
    icono: ImageVector,
    descripcion: String,
    onClick: () -> Unit,
    tint: Color = CampusColors.Acento,
) {
    Box(
        modifier = Modifier
            .size(56.dp)
            .clip(CircleShape)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = descripcion },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icono, contentDescription = null, tint = tint, modifier = Modifier.size(28.dp))
    }
}
