package com.example.myapplication.ui.admin.lugares

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.LugarAdmin
import com.example.myapplication.ui.admin.lugares.componentes.LugarMapaContent
import com.example.myapplication.ui.admin.lugares.componentes.LugarMapaEventos
import com.example.myapplication.ui.admin.lugares.componentes.lugaresJson
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.CampoBusqueda
import com.example.myapplication.ui.destino.componentes.EstadoVacio
import com.example.myapplication.ui.destino.componentes.FilaCategorias
import com.example.myapplication.ui.destino.componentes.icono
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import com.example.myapplication.data.repository.LUGARES_DE_PRUEBA

/** Rojo de las acciones destructivas (como `ColorFinalizar` de 7.4: `CampusColors.Peligro` es morado, §5.4). */
internal val ColorBorrar = Color(0xFFFF4D7D)

/**
 * Vista 7.6 · Lista de lugares (FE-3.4). **No navega**: [onNuevo] abre 7.7 vacía y [onEditar] la abre con el lugar
 * (las conecta `AppNav`). Reutiliza el buscador y los chips de categoría de 6.4 (`ui/destino/componentes/`, sin
 * cambiarlos).
 */
@Composable
fun LugaresScreen(
    onVolver: () -> Unit,
    onNuevo: () -> Unit,
    onEditar: (id: String) -> Unit,
    modifier: Modifier = Modifier,
    onVerFotos: (id: String) -> Unit = {},
    vm: LugaresViewModel = viewModel(factory = LugaresViewModel.Factory()),
) {
    val estado by vm.estado.collectAsStateWithLifecycle()
    LugaresContent(
        estado = estado,
        acciones = LugaresAcciones(
            onVolver = onVolver,
            onNuevo = onNuevo,
            onEditar = onEditar,
            onVerFotos = onVerFotos,
            onReintentar = { vm.cargar() },
            onBusqueda = vm::alBuscar,
            onCategoria = vm::alCategoria,
            onLimpiarFiltros = vm::limpiarFiltros,
            onModo = vm::alModo,
            onPedirBorrar = vm::pedirBorrar,
            onConfirmarBorrar = vm::confirmarBorrar,
            onCancelarBorrar = vm::cancelarBorrar,
            onDescartarAviso = vm::descartarAviso,
        ),
        modifier = modifier,
    )
}

@Composable
fun LugaresContent(estado: LugaresUiState, acciones: LugaresAcciones, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().background(CampusColors.Fondo)) {
        Column(
            Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(Modifier.fillMaxWidth().heightIn(min = 64.dp), verticalAlignment = Alignment.CenterVertically) {
                BotonIcono(Icons.AutoMirrored.Filled.ArrowBack, "Volver", acciones.onVolver)
                Column(Modifier.weight(1f).padding(horizontal = 4.dp)) {
                    Text(
                        "Lugares", color = CampusColors.TextoPrincipal, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.semantics { heading() },
                    )
                    if (!estado.cargando && estado.error == null) {
                        Text("${estado.todos.size} lugares registrados", color = CampusColors.TextoSecundario, fontSize = 14.sp)
                    }
                }
            }
            estado.aviso?.let { Aviso(it, acciones.onDescartarAviso) }
            SelectorModo(estado.modo, acciones.onModo)
            CampoBusqueda(estado.busqueda, acciones.onBusqueda)
            FilaCategorias(estado.categoria, acciones.onCategoria)

            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    estado.cargando -> CircularProgressIndicator(color = CampusColors.Acento, modifier = Modifier.align(Alignment.Center))
                    estado.error != null -> EstadoVacio(estado.error, "Reintentar", acciones.onReintentar)
                    estado.todos.isEmpty() -> EstadoVacio("Aún no hay lugares.", "Nuevo lugar", acciones.onNuevo)
                    estado.visibles.isEmpty() -> EstadoVacio("No hay lugares con estos filtros", "Limpiar filtros", acciones.onLimpiarFiltros)
                    estado.modo == ModoLugares.MAPA -> {
                        val forma = RoundedCornerShape(20.dp)
                        LugarMapaContent(
                            lugaresJson = lugaresJson(estado.visibles.map { it.lugar }),
                            punto = null,
                            editable = false,
                            eventos = LugarMapaEventos(onLugarTocado = acciones.onEditar),
                            modifier = Modifier.fillMaxSize().padding(bottom = 88.dp).clip(forma).border(1.dp, CampusColors.Borde, forma),
                        )
                    }
                    else -> LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                        contentPadding = PaddingValues(bottom = 96.dp),
                    ) {
                        items(estado.visibles, key = { it.id }) { l ->
                            FilaLugarAdmin(
                                l,
                                onEditar = { acciones.onEditar(l.id) },
                                onBorrar = { acciones.onPedirBorrar(l) },
                                onVerFotos = { acciones.onVerFotos(l.id) },
                            )
                        }
                    }
                }
            }
        }

        ExtendedFloatingActionButton(
            onClick = acciones.onNuevo,
            containerColor = CampusColors.Primario,
            contentColor = Color.White,
            icon = { Icon(Icons.Filled.Add, contentDescription = null) },
            text = { Text("Nuevo lugar", fontSize = 16.sp) },
            modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(16.dp),
        )
    }

    estado.confirmandoBorrar?.let { l ->
        AlertDialog(
            onDismissRequest = acciones.onCancelarBorrar,
            containerColor = CampusColors.SuperficieAlta,
            title = { Text("¿Eliminar «${l.nombre}»?", color = CampusColors.TextoPrincipal) },
            text = {
                Text(
                    "Deja de aparecer en Selección de destino. " +
                        (if (l.totalFotos > 0) "Sus ${l.totalFotos} fotos quedarán sin lugar. " else "") + "No se puede deshacer.",
                    color = CampusColors.TextoSuave,
                )
            },
            confirmButton = { TextButton(onClick = acciones.onConfirmarBorrar) { Text("Eliminar", color = ColorBorrar) } },
            dismissButton = { TextButton(onClick = acciones.onCancelarBorrar) { Text("Cancelar", color = CampusColors.Acento) } },
        )
    }
}

/** Fila de 7.6: nombre, categoría, nº de fotos y coordenada; tocarla edita; ⋮ abre Editar / Eliminar / Ver fotos. */
@Composable
private fun FilaLugarAdmin(l: LugarAdmin, onEditar: () -> Unit, onBorrar: () -> Unit, onVerFotos: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    val categoria = l.lugar.categoria
    Row(
        Modifier.fillMaxWidth().tarjeta(18.dp)
            .clickable(role = Role.Button, onClickLabel = "Editar", onClick = onEditar)
            .semantics { contentDescription = descripcionFila(l) }
            .heightIn(min = 72.dp).padding(start = 14.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(categoria.icono(), contentDescription = null, tint = CampusColors.Acento, modifier = Modifier.size(30.dp))
        Column(Modifier.weight(1f)) {
            Text(l.nombre, color = CampusColors.TextoPrincipal, fontSize = 18.sp)
            Text("${categoria.etiqueta} · ${textoFotos(l.totalFotos)}", color = CampusColors.TextoSecundario, fontSize = 14.sp)
            Text(FormularioLugar.textoCoordenada(l.lugar.lat, l.lugar.lng), color = CampusColors.TextoSuave, fontSize = 13.sp)
        }
        Box {
            BotonIcono(Icons.Filled.MoreVert, "Opciones de ${l.nombre}", { menu = true }, tint = CampusColors.TextoSuave)
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, modifier = Modifier.background(CampusColors.SuperficieAlta)) {
                DropdownMenuItem(text = { Text("Editar", color = CampusColors.TextoPrincipal) }, onClick = { menu = false; onEditar() })
                DropdownMenuItem(text = { Text("Eliminar", color = ColorBorrar) }, onClick = { menu = false; onBorrar() })
                // FE-4.1: abre la Galería filtrada por este lugar (`GET /v1/admin/images?lugar_id=`).
                DropdownMenuItem(
                    text = { Text("Ver fotos", color = CampusColors.TextoPrincipal) },
                    onClick = { menu = false; onVerFotos() },
                )
            }
        }
    }
}

/** `content-desc` de una fila de 7.6: «{nombre}, {categoría}, {N} fotos. Toca para editar.» (lo lee `validate34.py`). */
internal fun descripcionFila(l: LugarAdmin): String =
    "${l.nombre}, ${l.lugar.categoria.etiqueta}, ${textoFotos(l.totalFotos)}. Toca para editar."

internal fun textoFotos(n: Int): String = if (n == 1) "1 foto" else "$n fotos"

@Composable
private fun SelectorModo(modo: ModoLugares, onModo: (ModoLugares) -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(Modifier.fillMaxWidth().clip(forma).border(1.dp, CampusColors.Borde, forma)) {
        listOf(ModoLugares.LISTA to "Lista", ModoLugares.MAPA to "Mapa").forEach { (m, texto) ->
            val activo = m == modo
            Box(
                Modifier.weight(1f).heightIn(min = 48.dp)
                    .background(if (activo) CampusColors.Primario.copy(alpha = .3f) else Color.Transparent)
                    .clickable(role = Role.Tab) { onModo(m) }
                    .semantics { selected = activo; contentDescription = "Vista de ${texto.lowercase()}" },
                contentAlignment = Alignment.Center,
            ) {
                Text(texto, color = if (activo) CampusColors.TextoPrincipal else CampusColors.TextoSuave, fontSize = 16.sp)
            }
        }
    }
}

@Composable
private fun Aviso(texto: String, onDescartar: () -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(
        Modifier.fillMaxWidth().clip(forma).background(CampusColors.SuperficieAlta).border(1.dp, CampusColors.Borde, forma)
            .clickable(onClickLabel = "Descartar aviso", onClick = onDescartar).padding(12.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Filled.Warning, contentDescription = null, tint = CampusColors.Acento)
        Text(texto, color = CampusColors.TextoPrincipal, fontSize = 14.sp)
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF030615, heightDp = 800)
@Composable
private fun PreviewLugares() {
    LugaresContent(
        estado = LugaresUiState(cargando = false, todos = LUGARES_DE_PRUEBA.map { LugarAdmin(it.copy(distanciaMetros = null)) }),
        acciones = LugaresAcciones(),
    )
}
