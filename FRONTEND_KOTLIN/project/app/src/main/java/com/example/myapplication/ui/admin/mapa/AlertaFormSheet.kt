package com.example.myapplication.ui.admin.mapa

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.ui.inicio.VoiceController
import java.util.TimeZone

private enum class Extremo { DESDE, HASTA }

/**
 * Vista 7.9 — Formulario de alerta (hoja inferior). Cada cambio se refleja en vivo en el mapa (lo hace quien recibe
 * [onCambio]). FE-3.3: dictado por voz (añade lo dicho al mensaje), «Escuchar cómo sonará» (la voz de la app),
 * vigencia opcional (desde / hasta, días enteros en la zona del teléfono) y, si [onAjustarEnMapa] no es `null`,
 * «Ajustar en el mapa». La voz vive mientras la hoja está abierta (un `VoiceController` propio). No valida: los errores
 * llegan en [error] (bajo el mensaje) y [errorVigencia].
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertaFormSheet(
    alerta: Alerta,
    esNueva: Boolean,
    error: String?,
    onCambio: (Alerta) -> Unit,
    onGuardar: () -> Unit,
    onCancelar: () -> Unit,
    onEliminar: () -> Unit,
    errorVigencia: String? = null,
    onAjustarEnMapa: (() -> Unit)? = null,
) {
    val ctx = LocalContext.current
    val voz = remember { VoiceController(ctx.applicationContext) }
    DisposableEffect(voz) { onDispose { voz.release() } }
    val alertaActual by rememberUpdatedState(alerta)
    val onCambioActual by rememberUpdatedState(onCambio)

    var confirmarEliminar by remember { mutableStateOf(false) }
    var escuchando by remember { mutableStateOf(false) }
    var avisoVoz by remember { mutableStateOf<String?>(null) }
    var eligiendo by remember { mutableStateOf<Extremo?>(null) }
    val zona = remember { TimeZone.getDefault() }

    ModalBottomSheet(onDismissRequest = { voz.stopAll(); onCancelar() }) {
        Column(
            Modifier.navigationBarsPadding().heightIn(max = 640.dp).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(if (esNueva) "Nueva alerta" else "Editar alerta", style = MaterialTheme.typography.titleLarge)

            OutlinedTextField(
                value = alerta.mensaje,
                onValueChange = { if (it.length <= MAX_MENSAJE) onCambio(alerta.copy(mensaje = it)) },
                label = { Text("Mensaje") },
                supportingText = { Text(error ?: "Escribe exactamente lo que se le dirá al usuario (${alerta.mensaje.length}/$MAX_MENSAJE)") },
                isError = error != null,
                minLines = 2,
                trailingIcon = {
                    IconButton(onClick = {
                        if (escuchando) {
                            voz.stopListening()
                            escuchando = false
                            avisoVoz = null
                        } else {
                            voz.stopAll()
                            escuchando = true
                            avisoVoz = "Escuchando… di el mensaje."
                            voz.listen(
                                onResult = { dicho ->
                                    escuchando = false
                                    avisoVoz = null
                                    val a = alertaActual
                                    onCambioActual(a.copy(mensaje = FormularioAlerta.agregarDictado(a.mensaje, dicho)))
                                },
                                onFail = { escuchando = false; avisoVoz = "No te entendí. Toca el micrófono e inténtalo de nuevo." },
                                soloMejor = true,
                            )
                        }
                    }) {
                        Icon(Icons.Filled.Mic, contentDescription = if (escuchando) "Dejar de escuchar" else "Dictar el mensaje")
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            )
            avisoVoz?.let { Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
            OutlinedButton(
                onClick = { voz.stopListening(); escuchando = false; voz.speak(alerta.mensaje.trim()) },
                enabled = alerta.mensaje.isNotBlank(),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) {
                Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null)
                Text("  Escuchar cómo sonará")
            }

            Text("Tipo", style = MaterialTheme.typography.labelLarge)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FormularioAlerta.TIPOS.forEach { (clave, nombre) ->
                    FilterChip(selected = alerta.tipo == clave, onClick = { onCambio(alerta.copy(tipo = clave)) }, label = { Text(nombre) })
                }
            }

            Text("Prioridad", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FormularioAlerta.PRIORIDADES.forEach { (clave, nombre) ->
                    FilterChip(selected = alerta.prioridad == clave, onClick = { onCambio(alerta.copy(prioridad = clave)) }, label = { Text(nombre) })
                }
            }

            Text("Radio de activación: ${alerta.radio} m", style = MaterialTheme.typography.labelLarge)
            Slider(
                value = alerta.radio.toFloat(),
                onValueChange = { onCambio(alerta.copy(radio = (Math.round(it / 5f) * 5).coerceIn(5, 100))) },
                valueRange = 5f..100f,
                steps = 18,   // saltos de 5 m
                modifier = Modifier.semantics { stateDescription = "${alerta.radio} metros" },
            )

            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(if (alerta.activa) "Activa" else "Inactiva")
                Switch(checked = alerta.activa, onCheckedChange = { onCambio(alerta.copy(activa = it)) })
            }

            Text(
                "Vigencia (opcional): " + FormularioAlerta.textoVigencia(alerta.vigenciaDesdeMs, alerta.vigenciaHastaMs, zona),
                style = MaterialTheme.typography.labelLarge,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = { eligiendo = Extremo.DESDE }, modifier = Modifier.weight(1f).heightIn(min = 48.dp)) {
                    Text("Desde: " + (alerta.vigenciaDesdeMs?.let { FormularioAlerta.textoFecha(it, zona) } ?: "—"))
                }
                OutlinedButton(onClick = { eligiendo = Extremo.HASTA }, modifier = Modifier.weight(1f).heightIn(min = 48.dp)) {
                    Text("Hasta: " + (alerta.vigenciaHastaMs?.let { FormularioAlerta.textoFecha(it, zona) } ?: "—"))
                }
            }
            if (alerta.vigenciaDesdeMs != null || alerta.vigenciaHastaMs != null) {
                TextButton(onClick = { onCambio(alerta.copy(vigenciaDesdeMs = null, vigenciaHastaMs = null)) }) { Text("Quitar la vigencia") }
            }
            errorVigencia?.let {
                Text(
                    it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }

            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Posición: " + FormularioAlerta.textoPosicion(alerta.lat, alerta.lng), style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                if (onAjustarEnMapa != null) {
                    TextButton(onClick = { voz.stopAll(); onAjustarEnMapa() }, modifier = Modifier.heightIn(min = 48.dp)) {
                        Icon(Icons.Filled.MyLocation, contentDescription = null)
                        Text(" Ajustar en el mapa")
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
                OutlinedButton(onClick = { voz.stopAll(); onCancelar() }, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Cancelar") }
                if (!esNueva) {
                    OutlinedButton(onClick = { confirmarEliminar = true }, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Eliminar") }
                }
                Button(onClick = { voz.stopAll(); onGuardar() }, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Guardar") }
            }
        }
    }

    eligiendo?.let { extremo ->
        val inicial = (if (extremo == Extremo.DESDE) alerta.vigenciaDesdeMs else alerta.vigenciaHastaMs)
            ?.let { FormularioAlerta.fechaUtcDelDia(it, zona) }
        val estado = rememberDatePickerState(initialSelectedDateMillis = inicial)
        DatePickerDialog(
            onDismissRequest = { eligiendo = null },
            confirmButton = {
                TextButton(onClick = {
                    estado.selectedDateMillis?.let { fecha ->
                        onCambio(
                            if (extremo == Extremo.DESDE) alerta.copy(vigenciaDesdeMs = FormularioAlerta.inicioDelDia(fecha, zona))
                            else alerta.copy(vigenciaHastaMs = FormularioAlerta.finDelDia(fecha, zona)),
                        )
                    }
                    eligiendo = null
                }) { Text("Aceptar") }
            },
            dismissButton = { TextButton(onClick = { eligiendo = null }) { Text("Cancelar") } },
        ) {
            DatePicker(
                state = estado,
                title = { Text(if (extremo == Extremo.DESDE) "Vigente desde" else "Vigente hasta", Modifier.padding(16.dp)) },
            )
        }
    }

    if (confirmarEliminar) {
        AlertDialog(
            onDismissRequest = { confirmarEliminar = false },
            title = { Text("¿Eliminar esta alerta?") },
            text = { Text("Dejará de avisarse a los usuarios.") },
            confirmButton = { TextButton(onClick = { confirmarEliminar = false; voz.stopAll(); onEliminar() }) { Text("Eliminar") } },
            dismissButton = { TextButton(onClick = { confirmarEliminar = false }) { Text("Cancelar") } },
        )
    }
}