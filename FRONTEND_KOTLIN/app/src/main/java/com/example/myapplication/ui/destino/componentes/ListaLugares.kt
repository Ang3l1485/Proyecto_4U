package com.example.myapplication.ui.destino.componentes

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.SwapVert
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.ui.destino.OrdenLugares
import com.example.myapplication.ui.theme.CampusColors

// ============================================================================
// Chips de categorías
// ============================================================================

@Composable
fun FilaCategorias(
    seleccionada: CategoriaLugar?,
    onElegir: (CategoriaLugar?) -> Unit,
) {
    var menuAbierto by remember { mutableStateOf(false) }
    // Si la categoría activa no tiene chip propio, el chip "Más" muestra su nombre.
    val extra = seleccionada?.takeIf { it !in CategoriaLugar.DESTACADAS }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CategoriaLugar.DESTACADAS.forEach { categoria ->
            ChipCategoria(
                texto = categoria.etiquetaPlural,
                icono = categoria.icono(),
                seleccionado = seleccionada == categoria,
                onClick = { onElegir(if (seleccionada == categoria) null else categoria) },
            )
        }

        Box {
            ChipCategoria(
                texto = extra?.etiquetaPlural ?: "Más",
                icono = extra?.icono(),
                seleccionado = extra != null,
                conFlecha = true,
                descripcion = "Más categorías",
                onClick = { menuAbierto = true },
            )
            DropdownMenu(
                expanded = menuAbierto,
                onDismissRequest = { menuAbierto = false },
                modifier = Modifier.background(CampusColors.SuperficieAlta),
            ) {
                CategoriaLugar.OTRAS.forEach { categoria ->
                    DropdownMenuItem(
                        text = {
                            Text(categoria.etiquetaPlural, color = CampusColors.TextoPrincipal, fontSize = 18.sp)
                        },
                        leadingIcon = {
                            Icon(categoria.icono(), contentDescription = null, tint = CampusColors.Acento)
                        },
                        onClick = {
                            onElegir(categoria)
                            menuAbierto = false
                        },
                    )
                }
                if (extra != null) {
                    DropdownMenuItem(
                        text = { Text("Quitar filtro", color = CampusColors.TextoSecundario, fontSize = 18.sp) },
                        onClick = {
                            onElegir(null)
                            menuAbierto = false
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ChipCategoria(
    texto: String,
    icono: ImageVector?,
    seleccionado: Boolean,
    onClick: () -> Unit,
    conFlecha: Boolean = false,
    descripcion: String? = null,
) {
    val forma = RoundedCornerShape(50)
    Row(
        modifier = Modifier
            .heightIn(min = 48.dp)
            .clip(forma)
            .background(if (seleccionado) CampusColors.Primario.copy(alpha = 0.18f) else Color.Transparent)
            .border(
                width = if (seleccionado) 2.dp else 1.dp,
                color = if (seleccionado) CampusColors.Acento else CampusColors.Borde,
                shape = forma,
            )
            .clickable(role = Role.Button, onClick = onClick)
            .semantics {
                selected = seleccionado
                if (descripcion != null) contentDescription = descripcion
            }
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (icono != null) {
            Icon(icono, contentDescription = null, tint = CampusColors.Acento, modifier = Modifier.size(22.dp))
        }
        Text(texto, color = CampusColors.TextoPrincipal, fontSize = 16.sp)
        if (conFlecha) {
            Icon(
                Icons.Filled.KeyboardArrowDown,
                contentDescription = null,
                tint = CampusColors.TextoSecundario,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

// ============================================================================
// Buscador
// ============================================================================

@Composable
fun CampoBusqueda(texto: String, onCambio: (String) -> Unit) {
    val foco = LocalFocusManager.current
    OutlinedTextField(
        value = texto,
        onValueChange = onCambio,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 60.dp),
        placeholder = { Text("Buscar un lugar…", color = CampusColors.TextoSuave, fontSize = 18.sp) },
        leadingIcon = {
            Icon(Icons.Outlined.Search, contentDescription = null, tint = CampusColors.TextoSuave)
        },
        trailingIcon = {
            if (texto.isNotEmpty()) {
                IconButton(onClick = { onCambio("") }) {
                    Icon(Icons.Filled.Close, contentDescription = "Borrar búsqueda", tint = CampusColors.TextoSuave)
                }
            }
        },
        singleLine = true,
        shape = RoundedCornerShape(18.dp),
        textStyle = LocalTextStyle.current.copy(fontSize = 18.sp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = CampusColors.TextoPrincipal,
            unfocusedTextColor = CampusColors.TextoPrincipal,
            focusedBorderColor = CampusColors.Acento,
            unfocusedBorderColor = CampusColors.Borde,
            focusedContainerColor = CampusColors.Superficie,
            unfocusedContainerColor = CampusColors.Superficie,
            cursorColor = CampusColors.Acento,
        ),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        keyboardActions = KeyboardActions(onSearch = { foco.clearFocus() }),
    )
}

// ============================================================================
// Lista
// ============================================================================

@Composable
fun EncabezadoLista(orden: OrdenLugares, onCambiarOrden: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (orden == OrdenLugares.CERCANIA) "Lugares cercanos" else "Lugares",
            color = CampusColors.TextoPrincipal,
            fontSize = 20.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier
                .weight(1f)
                .semantics { heading() },
        )
        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(12.dp))
                .clickable(role = Role.Button, onClick = onCambiarOrden)
                .heightIn(min = 48.dp)
                .padding(horizontal = 8.dp)
                .semantics { contentDescription = "${orden.etiqueta}. Toca para cambiar el orden." },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(orden.etiqueta, color = CampusColors.TextoSuave, fontSize = 16.sp)
            Icon(
                Icons.Filled.SwapVert,
                contentDescription = null,
                tint = CampusColors.Acento,
                modifier = Modifier.size(22.dp),
            )
        }
    }
}

@Composable
fun FilaLugar(lugar: LugarDestino, onClick: () -> Unit) {
    val distancia = lugar.distanciaMetros?.let { "$it m" }
    val descripcion = buildString {
        append(lugar.nombre).append(", ").append(lugar.categoria.etiqueta)
        if (distancia != null) append(", a ").append(lugar.distanciaMetros).append(" metros")
        append(". Toca para elegir este destino.")
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .tarjeta(18.dp)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = descripcion }
            .padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // Miniatura: foto de referencia o, si no hay, el ícono de la categoría.
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(CampusColors.SuperficieAlta),
            contentAlignment = Alignment.Center,
        ) {
            if (lugar.imagenUrl != null) {
                AsyncImage(
                    model = lugar.imagenUrl,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Icon(
                    lugar.categoria.icono(),
                    contentDescription = null,
                    tint = CampusColors.Acento,
                    modifier = Modifier.size(30.dp),
                )
            }
        }

        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = lugar.nombre,
                color = CampusColors.TextoPrincipal,
                fontSize = 18.sp,
                lineHeight = 22.sp,
                fontWeight = FontWeight.Medium,
            )
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(
                    lugar.categoria.icono(),
                    contentDescription = null,
                    tint = CampusColors.Acento,
                    modifier = Modifier.size(18.dp),
                )
                Text(lugar.categoria.etiqueta, color = CampusColors.TextoSecundario, fontSize = 15.sp)
            }
        }

        if (distancia != null) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                Icon(
                    Icons.Filled.LocationOn,
                    contentDescription = null,
                    tint = CampusColors.TextoSuave,
                    modifier = Modifier.size(18.dp),
                )
                Text(distancia, color = CampusColors.TextoSecundario, fontSize = 16.sp)
            }
        }
        Icon(
            Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = CampusColors.TextoSecundario,
        )
    }
}

/** Mensaje (opcional) con una acción de texto debajo: "Limpiar filtros", "Reintentar". */
@Composable
fun EstadoVacio(mensaje: String?, accion: String, onAccion: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (mensaje != null) {
            Text(
                text = mensaje,
                color = CampusColors.TextoSuave,
                fontSize = 18.sp,
                textAlign = TextAlign.Center,
            )
        }
        Text(
            text = accion,
            color = CampusColors.Acento,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier
                .clip(RoundedCornerShape(12.dp))
                .clickable(role = Role.Button, onClick = onAccion)
                .heightIn(min = 48.dp)
                .padding(horizontal = 20.dp, vertical = 12.dp),
        )
    }
}

// ============================================================================
// Botón inferior
// ============================================================================

@Composable
fun BotonVolver(onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 12.dp)
            .heightIn(min = 64.dp),
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(2.dp, CampusColors.Primario),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = CampusColors.Acento),
    ) {
        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(24.dp))
        Spacer(Modifier.width(10.dp))
        Text("Volver", fontSize = 20.sp, fontWeight = FontWeight.Medium)
    }
}
