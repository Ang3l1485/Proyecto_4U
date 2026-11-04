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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.myapplication.domain.model.Alerta

private val TIPOS = listOf(
    "agua" to "Agua", "mobiliario" to "Mobiliario", "escalones" to "Escalones",
    "obra" to "Obra", "vehiculos" to "Vehículos", "otro" to "Otro",
)

/** Vista 7.9 — Formulario de alerta (hoja inferior). Cada cambio se refleja en vivo en el mapa. */
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
) {
    var confirmarEliminar by remember { mutableStateOf(false) }

    ModalBottomSheet(onDismissRequest = onCancelar) {
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
                modifier = Modifier.fillMaxWidth(),
            )

            Text("Tipo", style = MaterialTheme.typography.labelLarge)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TIPOS.forEach { (clave, nombre) ->
                    FilterChip(selected = alerta.tipo == clave, onClick = { onCambio(alerta.copy(tipo = clave)) }, label = { Text(nombre) })
                }
            }

            Text("Prioridad", style = MaterialTheme.typography.labelLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = alerta.prioridad == "normal", onClick = { onCambio(alerta.copy(prioridad = "normal")) }, label = { Text("Normal") })
                FilterChip(selected = alerta.prioridad == "alta", onClick = { onCambio(alerta.copy(prioridad = "alta")) }, label = { Text("Alta") })
            }

            Text("Radio de activación: ${alerta.radio} m", style = MaterialTheme.typography.labelLarge)
            Slider(
                value = alerta.radio.toFloat(),
                onValueChange = { onCambio(alerta.copy(radio = (Math.round(it / 5f) * 5).coerceIn(5, 100))) },
                valueRange = 5f..100f,
                steps = 18,   // saltos de 5 m
            )

            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(if (alerta.activa) "Activa" else "Inactiva")
                Switch(checked = alerta.activa, onCheckedChange = { onCambio(alerta.copy(activa = it)) })
            }
            Text("Posición: %.5f, %.5f".format(alerta.lat, alerta.lng), style = MaterialTheme.typography.bodySmall)

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
                OutlinedButton(onClick = onCancelar, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Cancelar") }
                if (!esNueva) {
                    OutlinedButton(onClick = { confirmarEliminar = true }, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Eliminar") }
                }
                Button(onClick = onGuardar, modifier = Modifier.weight(1f).heightIn(min = 56.dp)) { Text("Guardar") }
            }
        }
    }

    if (confirmarEliminar) {
        AlertDialog(
            onDismissRequest = { confirmarEliminar = false },
            title = { Text("¿Eliminar esta alerta?") },
            text = { Text("Dejará de avisarse a los usuarios.") },
            confirmButton = { TextButton(onClick = { confirmarEliminar = false; onEliminar() }) { Text("Eliminar") } },
            dismissButton = { TextButton(onClick = { confirmarEliminar = false }) { Text("Cancelar") } },
        )
    }
}