package com.example.myapplication.ui.admin.mapa

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Chair
import androidx.compose.material.icons.filled.Construction
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stairs
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.ui.platform.LocalContext
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.ui.admin.lugares.ColorBorrar
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.EstadoVacio
import com.example.myapplication.ui.destino.componentes.tarjeta
import com.example.myapplication.ui.theme.CampusColors
import java.util.TimeZone

/**
 * Vista 7.10 · Lista de alertas (FE-3.3). **No navega**: [onVerEnMapa] y [onNuevaEnMapa] vuelven al editor 7.8 (que está
 * debajo en la pila) con un pedido (`PedidosEditorMapa`); [onVolver] también es «Ver mapa». Editar abre la hoja 7.9
 * aquí mismo (sin «Ajustar en el mapa»: la posición se cambia en el editor con «Mover»).
 */
@Composable
fun AlertasScreen(
    onVolver: () -> Unit,
    onVerEnMapa: (id: String) -> Unit,
    onNuevaEnMapa: () -> Unit,
    modifier: Modifier = Modifier,
    vm: AlertasViewModel = viewModel(factory = AlertasViewModel.Factory(LocalContext.current.applicationContext)),
) {
    val estado by vm.estado.collectAsStateWithLifecycle()
    AlertasContent(
        estado = estado,
        acciones = AlertasAcciones(
            onVolver = onVolver,
            onVerMapa = onVolver,
            onNueva = onNuevaEnMapa,
            onReintentar = vm::cargar,
            onBusqueda = vm::alBuscar,
            onTipo = vm::alTipo,
            onPrioridad = vm::alPrioridad,
            onEstado = vm::alEstado,
            onLimpiarFiltros = vm::limpiarFiltros,
            onEditar = vm::editar,
            onAlternarActiva = vm::alternarActiva,
            onVerEnMapa = onVerEnMapa,
            onPedirBorrar = vm::pedirBorrar,
            onConfirmarBorrar = vm::confirmarBorrar,
            onCancelarBorrar = vm::cancelarBorrar,
            onSincronizar = vm::sincronizar,
            onDescartarAviso = vm::descartarAviso,
        ),
        modifier = modifier,
    )
    estado.formulario?.let { a ->
        AlertaFormSheet(
            alerta = a,
            esNueva = false,
            error = estado.errores.mensaje ?: estado.errores.general,
            errorVigencia = estado.errores.vigencia,
            onCambio = vm::actualizarFormulario,
            onGuardar = vm::guardarFormulario,
            onCancelar = vm::cancelarFormulario,
            onEliminar = { vm.pedirBorrar(a); vm.confirmarBorrar() },   // la hoja ya pidió confirmación
        )
    }
}

@Composable
fun AlertasContent(estado: AlertasUiState, acciones: AlertasAcciones, modifier: Modifier = Modifier) {
    val zona = remember { TimeZone.getDefault() }
    Box(modifier.fillMaxSize().background(CampusColors.Fondo)) {
        Column(
            Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(Modifier.fillMaxWidth().heightIn(min = 64.dp), verticalAlignment = Alignment.CenterVertically) {
                BotonIcono(Icons.AutoMirrored.Filled.ArrowBack, "Volver", acciones.onVolver)
                Column(Modifier.weight(1f).padding(horizontal = 4.dp)) {
                    Text(
                        "Alertas", color = CampusColors.TextoPrincipal, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.semantics { heading() },
                    )
                    if (!estado.cargando || estado.todas.isNotEmpty()) {
                        Text(textoTotal(estado.todas.size), color = CampusColors.TextoSecundario, fontSize = 14.sp)
                    }
                }
                BotonIcono(Icons.Filled.Map, "Ver mapa", acciones.onVerMapa)
            }
            estado.aviso?.let { Aviso(it, acciones.onDescartarAviso) }
            if (estado.pendientes.isNotEmpty()) {
                Pendientes(estado.pendientes.size, estado.sincronizando, acciones.onSincronizar)
            }
            OutlinedTextField(
                value = estado.busqueda,
                onValueChange = acciones.onBusqueda,
                singleLine = true,
                placeholder = { Text("Buscar por mensaje…") },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
            )
            Filtros(estado, acciones)

            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    estado.cargando && estado.todas.isEmpty() ->
                        CircularProgressIndicator(color = CampusColors.Acento, modifier = Modifier.align(Alignment.Center))
                    estado.error != null -> EstadoVacio(estado.error, "Reintentar", acciones.onReintentar)
                    estado.todas.isEmpty() -> EstadoVacio("Aún no hay alertas.", "Nueva alerta", acciones.onNueva)
                    estado.visibles.isEmpty() -> EstadoVacio("No hay alertas con estos filtros", "Limpiar filtros", acciones.onLimpiarFiltros)
                    else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(bottom = 96.dp)) {
                        items(estado.visibles, key = { it.id }) { a ->
                            FilaAlerta(
                                a, pendiente = a.id in estado.pendientes, rechazada = a.id in estado.rechazadas, zona = zona,
                                acciones = acciones,
                            )
                        }
                    }
                }
            }
        }

        ExtendedFloatingActionButton(
            onClick = acciones.onNueva,
            containerColor = CampusColors.Primario,
            contentColor = Color.White,
            icon = { Icon(Icons.Filled.Add, contentDescription = null) },
            text = { Text("Nueva alerta", fontSize = 16.sp) },
            modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(16.dp),
        )
    }

    estado.confirmandoBorrar?.let { a ->
        AlertDialog(
            onDismissRequest = acciones.onCancelarBorrar,
            containerColor = CampusColors.SuperficieAlta,
            title = { Text("¿Eliminar esta alerta?", color = CampusColors.TextoPrincipal) },
            text = { Text("«${a.mensaje}» dejará de avisarse a los usuarios al sincronizar.", color = CampusColors.TextoSuave) },
            confirmButton = { TextButton(onClick = acciones.onConfirmarBorrar) { Text("Eliminar", color = ColorBorrar) } },
            dismissButton = { TextButton(onClick = acciones.onCancelarBorrar) { Text("Cancelar", color = CampusColors.Acento) } },
        )
    }
}

/** Fila de 7.10: ícono del tipo, mensaje (2 líneas), «prioridad · radio · estado» y la fecha de modificación. */
@Composable
private fun FilaAlerta(a: Alerta, pendiente: Boolean, rechazada: Boolean, zona: TimeZone, acciones: AlertasAcciones) {
    var menu by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().tarjeta(18.dp)
            .clickable(role = Role.Button, onClickLabel = "Editar") { acciones.onEditar(a.id) }
            .semantics { contentDescription = descripcionFilaAlerta(a, pendiente) }
            .heightIn(min = 72.dp).padding(start = 14.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(
            iconoTipo(a.tipo), contentDescription = null,
            tint = if (a.activa) (if (a.prioridad == "alta") ColorBorrar else ColorAlerta) else CampusColors.TextoSuave,
            modifier = Modifier.size(30.dp),
        )
        Column(Modifier.weight(1f)) {
            Text(a.mensaje, color = CampusColors.TextoPrincipal, fontSize = 17.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(
                "${FormularioAlerta.nombrePrioridad(a.prioridad)} · ${a.radio} m · ${if (a.activa) "Activa" else "Inactiva"}",
                color = CampusColors.TextoSecundario, fontSize = 14.sp,
            )
            Text(
                when {
                    rechazada -> "Rechazada por el servidor: revísala"
                    pendiente -> "Sin sincronizar"
                    a.actualizadoEnMs != null -> "Modificada el ${FormularioAlerta.textoFecha(a.actualizadoEnMs, zona)}"
                    else -> ""
                },
                color = if (rechazada) ColorBorrar else CampusColors.TextoSuave, fontSize = 13.sp,
            )
        }
        Box {
            BotonIcono(Icons.Filled.MoreVert, "Opciones de la alerta", { menu = true }, tint = CampusColors.TextoSuave)
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, modifier = Modifier.background(CampusColors.SuperficieAlta)) {
                DropdownMenuItem(text = { Text("Editar", color = CampusColors.TextoPrincipal) }, onClick = { menu = false; acciones.onEditar(a.id) })
                DropdownMenuItem(
                    text = { Text(if (a.activa) "Desactivar" else "Activar", color = CampusColors.TextoPrincipal) },
                    onClick = { menu = false; acciones.onAlternarActiva(a.id) },
                )
                DropdownMenuItem(text = { Text("Ver en el mapa", color = CampusColors.TextoPrincipal) }, onClick = { menu = false; acciones.onVerEnMapa(a.id) })
                DropdownMenuItem(text = { Text("Eliminar", color = ColorBorrar) }, onClick = { menu = false; acciones.onPedirBorrar(a) })
            }
        }
    }
}

@Composable
private fun Filtros(estado: AlertasUiState, acciones: AlertasAcciones) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FormularioAlerta.TIPOS.forEach { (clave, nombre) ->
            val activo = estado.tipo == clave
            FilterChip(selected = activo, onClick = { acciones.onTipo(if (activo) null else clave) }, label = { Text(nombre) })
        }
    }
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FormularioAlerta.PRIORIDADES.forEach { (clave, nombre) ->
            val activo = estado.prioridad == clave
            FilterChip(selected = activo, onClick = { acciones.onPrioridad(if (activo) null else clave) }, label = { Text("Prioridad ${nombre.lowercase()}") })
        }
        listOf(FiltroEstado.ACTIVAS, FiltroEstado.INACTIVAS).forEach { f ->
            val activo = estado.estado == f
            FilterChip(selected = activo, onClick = { acciones.onEstado(if (activo) FiltroEstado.TODAS else f) }, label = { Text(f.etiqueta) })
        }
    }
}

@Composable
private fun Pendientes(n: Int, sincronizando: Boolean, onSincronizar: () -> Unit) {
    val forma = RoundedCornerShape(14.dp)
    Row(
        Modifier.fillMaxWidth().clip(forma).background(CampusColors.SuperficieAlta).border(1.dp, ColorAlerta, forma)
            .padding(horizontal = 12.dp, vertical = 4.dp).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            if (n == 1) "1 alerta con cambios sin sincronizar" else "$n alertas con cambios sin sincronizar",
            color = CampusColors.TextoPrincipal, fontSize = 14.sp, modifier = Modifier.weight(1f),
        )
        if (sincronizando) CircularProgressIndicator(color = CampusColors.Acento, modifier = Modifier.size(24.dp))
        else TextButton(onClick = onSincronizar, modifier = Modifier.heightIn(min = 48.dp)) { Text("Sincronizar", color = CampusColors.Acento) }
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

/** Ámbar de las alertas de prioridad normal (el `#f59e0b` del mapa web). */
internal val ColorAlerta = Color(0xFFF59E0B)

/**
 * `content-desc` de una fila de 7.10: «‹mensaje›, ‹tipo›, prioridad ‹normal|alta›, ‹activa|inactiva›[, sin
 * sincronizar]. Toca para editar.» (lo lee `validate33.py`: empieza por el mensaje seguido de «, »).
 */
internal fun descripcionFilaAlerta(a: Alerta, pendiente: Boolean): String =
    "${a.mensaje}, ${FormularioAlerta.nombreTipo(a.tipo)}, prioridad ${FormularioAlerta.nombrePrioridad(a.prioridad).lowercase()}, " +
        (if (a.activa) "activa" else "inactiva") + (if (pendiente) ", sin sincronizar" else "") + ". Toca para editar."

internal fun textoTotal(n: Int): String = if (n == 1) "1 alerta" else "$n alertas"

private fun iconoTipo(tipo: String): ImageVector = when (tipo) {
    "agua" -> Icons.Filled.WaterDrop
    "mobiliario" -> Icons.Filled.Chair
    "escalones" -> Icons.Filled.Stairs
    "obra" -> Icons.Filled.Construction
    "vehiculos" -> Icons.Filled.DirectionsCar
    else -> Icons.Filled.Warning
}

@Preview(showBackground = true, backgroundColor = 0xFF030615, heightDp = 800)
@Composable
private fun PreviewAlertas() {
    AlertasContent(
        estado = AlertasUiState(
            cargando = false,
            todas = listOf(
                Alerta("a1", 6.2004, -75.5785, "Ten cuidado, hay bancas cerca, no te vayas a estrellar", "mobiliario"),
                Alerta("a2", 6.2010, -75.5777, "Rampa de acceso bloqueada por obras.", "obra", "alta", 50, actualizadoEnMs = 1_792_767_845_000L),
                Alerta("a3", 6.1997, -75.5779, "Escalones al frente.", "escalones", activa = false),
            ),
            pendientes = setOf("a1"),
        ),
        acciones = AlertasAcciones(),
    )
}
