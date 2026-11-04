package com.example.myapplication.ui.admin.lugares

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.ui.admin.lugares.componentes.LugarMapaContent
import com.example.myapplication.ui.admin.lugares.componentes.LugarMapaEventos
import com.example.myapplication.ui.admin.lugares.componentes.lugaresJson
import com.example.myapplication.ui.destino.componentes.BotonIcono
import com.example.myapplication.ui.destino.componentes.EstadoVacio
import com.example.myapplication.ui.destino.componentes.icono
import com.example.myapplication.ui.theme.CampusColors

/**
 * Vista 7.7 · Formulario de lugar (FE-3.4). [lugarId] `null` = nuevo. **No navega**: [onListo] (Atrás, «Cancelar», tras
 * guardar o eliminar) lo conecta `AppNav` con `popBackStack()`. El pie fijo muestra «Punto: lat, lng» y los botones,
 * siempre visibles (también para `uiautomator`).
 */
@Composable
fun LugarFormScreen(
    lugarId: String?,
    onListo: () -> Unit,
    modifier: Modifier = Modifier,
    onVerFotos: (id: String) -> Unit = {},
    vm: LugarFormViewModel = viewModel(key = "lugar-form-${lugarId ?: "nuevo"}", factory = LugarFormViewModel.Factory(lugarId)),
) {
    val estado by vm.estado.collectAsStateWithLifecycle()
    val ctx = LocalContext.current

    LaunchedEffect(vm) {
        vm.eventos.collect { evento ->
            val texto = when (evento) {
                is LugarFormEvento.Guardado -> "«${evento.nombre}» guardado."
                is LugarFormEvento.Eliminado -> "«${evento.nombre}» eliminado."
            }
            Toast.makeText(ctx, texto, Toast.LENGTH_SHORT).show()
            onListo()
        }
    }
    BackHandler(onBack = onListo)

    LugarFormContent(
        estado = estado,
        acciones = LugarFormAcciones(
            onVolver = onListo,
            onNombre = vm::alNombre,
            onAlias = vm::alAlias,
            onDescripcion = vm::alDescripcion,
            onCategoria = vm::alCategoria,
            onPunto = vm::alPunto,
            onReferencias = vm::alReferencias,
            onGuardar = vm::guardar,
            onReintentar = vm::cargar,
            onPedirBorrar = vm::pedirBorrar,
            onConfirmarBorrar = vm::confirmarBorrar,
            onCancelarBorrar = vm::cancelarBorrar,
            onVerFotos = { lugarId?.let(onVerFotos) },
        ),
        modifier = modifier,
    )
}

@Composable
fun LugarFormContent(
    estado: LugarFormUiState,
    acciones: LugarFormAcciones,
    modifier: Modifier = Modifier,
    conMapa: Boolean = true,
) {
    val c = estado.campos
    val e = estado.errores
    Column(
        modifier.fillMaxSize().background(CampusColors.Fondo).statusBarsPadding().navigationBarsPadding().imePadding(),
    ) {
        Row(Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            BotonIcono(Icons.AutoMirrored.Filled.ArrowBack, "Volver", acciones.onVolver)
            Text(
                if (estado.esNuevo) "Nuevo lugar" else "Editar lugar",
                color = CampusColors.TextoPrincipal, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
        }

        when {
            estado.cargando -> Box(Modifier.weight(1f).fillMaxWidth(), Alignment.Center) {
                CircularProgressIndicator(color = CampusColors.Acento)
            }
            estado.errorCarga != null -> Box(Modifier.weight(1f).fillMaxWidth().padding(16.dp)) {
                EstadoVacio(estado.errorCarga, "Reintentar", acciones.onReintentar)
            }
            else -> Column(
                Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                e.general?.let { MensajeError(it) }
                Campo("Nombre", c.nombre, acciones.onNombre, e.nombre, "Único: no distingue mayúsculas ni tildes.")
                Campo(
                    "Alias (separados por comas)", c.aliasTexto, acciones.onAlias, e.alias,
                    "Otros nombres que la persona puede decir (máx. ${FormularioLugar.ALIAS_MAX_ELEMENTOS}).",
                )
                Campo(
                    "Descripción", c.descripcion, acciones.onDescripcion, e.descripcion,
                    "Texto que se le lee a la persona (${c.descripcion.trim().length}/${FormularioLugar.TEXTO_MAX}).",
                    unaLinea = false,
                )

                Titulo("Categoría")
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    CategoriaLugar.values().forEach { cat ->
                        FilterChip(
                            selected = c.categoria == cat,
                            onClick = { acciones.onCategoria(cat) },
                            label = { Text(cat.etiqueta, fontSize = 15.sp) },
                            leadingIcon = { Icon(cat.icono(), contentDescription = null, modifier = Modifier.size(18.dp)) },
                            colors = FilterChipDefaults.filterChipColors(
                                labelColor = CampusColors.TextoPrincipal, iconColor = CampusColors.Acento,
                                selectedContainerColor = CampusColors.Primario.copy(alpha = .35f),
                                selectedLabelColor = CampusColors.TextoPrincipal, selectedLeadingIconColor = CampusColors.TextoPrincipal,
                            ),
                            modifier = Modifier.heightIn(min = 48.dp),
                        )
                    }
                }
                e.categoria?.let { MensajeError(it) }

                Titulo("Punto de llegada")
                Text("Toca el mapa donde se llega al lugar (su entrada) o arrastra el alfiler.", color = CampusColors.TextoSuave, fontSize = 14.sp)
                val forma = RoundedCornerShape(20.dp)
                Box(Modifier.fillMaxWidth().height(300.dp).clip(forma).border(1.dp, CampusColors.Borde, forma)) {
                    if (conMapa) {
                        LugarMapaContent(
                            lugaresJson = lugaresJson(estado.otros),
                            punto = c.punto,
                            editable = true,
                            eventos = LugarMapaEventos(onPunto = acciones.onPunto),
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
                e.punto?.let { MensajeError(it) }

                Campo(
                    "Referencias cercanas", c.referencias, acciones.onReferencias, e.referencias,
                    "Cómo describir los alrededores (${c.referencias.trim().length}/${FormularioLugar.TEXTO_MAX}).",
                    unaLinea = false,
                )

                Titulo("Fotos asociadas")
                Text(
                    "${textoFotos(estado.totalFotos)} con este lugar. Las fotos se asignan a un lugar desde la galería " +
                        "(selecciona fotos y «Reasignar»).",
                    color = CampusColors.TextoSuave, fontSize = 14.sp,
                )
                // FE-4.1: abre la Galería filtrada por este lugar (solo al editar: uno nuevo aún no tiene id).
                if (!estado.esNuevo) {
                    OutlinedButton(
                        onClick = acciones.onVerFotos,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = CampusColors.Acento),
                    ) { Text("Ver en la galería", fontSize = 16.sp) }
                }

                if (!estado.esNuevo) {
                    OutlinedButton(
                        onClick = acciones.onPedirBorrar, enabled = !estado.guardando,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = ColorBorrar),
                    ) { Text("Eliminar lugar", fontSize = 16.sp) }
                }
                Spacer(Modifier.height(8.dp))
            }
        }

        // Pie fijo: el punto elegido y los botones.
        Column(
            Modifier.fillMaxWidth().background(CampusColors.Superficie).padding(horizontal = 16.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(estado.textoPunto, color = if (c.punto == null) CampusColors.TextoSuave else CampusColors.TextoPrincipal, fontSize = 15.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = acciones.onVolver, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) {
                    Text("Cancelar", color = CampusColors.Acento, fontSize = 16.sp)
                }
                Button(
                    onClick = acciones.onGuardar,
                    enabled = !estado.guardando && !estado.cargando && estado.errorCarga == null,
                    modifier = Modifier.weight(1f).heightIn(min = 56.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = CampusColors.Primario, contentColor = Color.White),
                ) {
                    if (estado.guardando) {
                        CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.size(8.dp))
                    }
                    Text("Guardar", fontSize = 16.sp)
                }
            }
        }
    }

    if (estado.confirmandoBorrar) {
        AlertDialog(
            onDismissRequest = acciones.onCancelarBorrar,
            containerColor = CampusColors.SuperficieAlta,
            title = { Text("¿Eliminar «${c.nombre.trim()}»?", color = CampusColors.TextoPrincipal) },
            text = {
                Text(
                    "Deja de aparecer en Selección de destino. " +
                        (if (estado.totalFotos > 0) "Sus ${estado.totalFotos} fotos quedarán sin lugar. " else "") + "No se puede deshacer.",
                    color = CampusColors.TextoSuave,
                )
            },
            confirmButton = { TextButton(onClick = acciones.onConfirmarBorrar) { Text("Eliminar", color = ColorBorrar) } },
            dismissButton = { TextButton(onClick = acciones.onCancelarBorrar) { Text("Cancelar", color = CampusColors.Acento) } },
        )
    }
}

@Composable
private fun Titulo(texto: String) {
    Text(texto, color = CampusColors.TextoPrincipal, fontSize = 16.sp, fontWeight = FontWeight.Medium, modifier = Modifier.semantics { heading() })
}

@Composable
internal fun MensajeError(texto: String) {
    Text(
        texto, color = ColorBorrar, fontSize = 14.sp,
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(ColorBorrar.copy(alpha = .12f))
            .padding(10.dp).semantics { liveRegion = LiveRegionMode.Polite },
    )
}

/** Campo de texto del formulario: el error (si hay) reemplaza la ayuda y TalkBack lo anuncia. */
@Composable
private fun Campo(
    etiqueta: String,
    valor: String,
    onCambio: (String) -> Unit,
    error: String?,
    ayuda: String,
    unaLinea: Boolean = true,
) {
    OutlinedTextField(
        value = valor,
        onValueChange = onCambio,
        label = { Text(etiqueta) },
        supportingText = {
            Text(
                error ?: ayuda,
                modifier = if (error != null) Modifier.semantics { liveRegion = LiveRegionMode.Polite } else Modifier,
            )
        },
        isError = error != null,
        singleLine = unaLinea,
        minLines = if (unaLinea) 1 else 2,
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = CampusColors.TextoPrincipal, unfocusedTextColor = CampusColors.TextoPrincipal,
            focusedBorderColor = CampusColors.Acento, unfocusedBorderColor = CampusColors.Borde,
            focusedLabelColor = CampusColors.Acento, unfocusedLabelColor = CampusColors.TextoSuave,
            focusedSupportingTextColor = CampusColors.TextoSuave, unfocusedSupportingTextColor = CampusColors.TextoSuave,
            cursorColor = CampusColors.Acento,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF030615, heightDp = 900)
@Composable
private fun PreviewLugarFormNuevo() {
    LugarFormContent(
        estado = LugarFormUiState(
            campos = CamposLugar(nombre = "Bloque 19", categoria = CategoriaLugar.BLOQUE, punto = 6.200512 to -75.578311),
            errores = ErroresLugar(nombre = ErroresLugarMapeo.NOMBRE_DUPLICADO),
        ),
        acciones = LugarFormAcciones(),
        conMapa = false,
    )
}
