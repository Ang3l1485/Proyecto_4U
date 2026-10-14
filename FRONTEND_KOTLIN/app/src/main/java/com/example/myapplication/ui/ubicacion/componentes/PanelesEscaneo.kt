package com.example.myapplication.ui.ubicacion.componentes

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Timer
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.myapplication.ui.ubicacion.EscaneoColores.Morado
import com.example.myapplication.ui.ubicacion.EscaneoColores.MoradoBoton
import com.example.myapplication.ui.ubicacion.EscaneoColores.MoradoClaro
import com.example.myapplication.ui.ubicacion.EscaneoColores.Panel
import com.example.myapplication.ui.ubicacion.EscaneoColores.Rojo
import com.example.myapplication.ui.ubicacion.EscaneoColores.TextoSecundario
import com.example.myapplication.ui.ubicacion.EscaneoColores.Verde

/* Piezas pequeñas de la pantalla de escaneo. Todas son "tontas": solo dibujan lo que reciben. */

/** Barra superior: botón volver, título y botón de ajustes. */
@Composable
internal fun BarraSuperior(onAtras: () -> Unit, onAjustes: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onAtras) {
            Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Volver", tint = Morado,
                modifier = Modifier.size(32.dp),
            )
        }
        Column(Modifier.weight(1f).padding(start = 8.dp)) {
            Text("Ubicarme", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Medium)
            Text("Captura de entorno", color = MoradoClaro, fontSize = 16.sp)
        }
        IconButton(onClick = onAjustes) {
            Icon(Icons.Default.Settings, "Ajustes", tint = Morado, modifier = Modifier.size(30.dp))
        }
    }
}

/** Instrucción grande (o mensaje de error, con ícono de advertencia en rojo). */
@Composable
internal fun InstruccionGrande(texto: String, esError: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            if (esError) Icons.Default.Warning else Icons.Default.Refresh,
            contentDescription = null, // el texto de al lado ya dice lo mismo
            tint = if (esError) Rojo else Morado,
            modifier = Modifier.size(52.dp),
        )
        Spacer(Modifier.width(18.dp))
        Text(
            text = texto,
            color = Color.White,
            fontSize = 28.sp,
            lineHeight = 34.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

/** Recordatorios fijos: "Más despacio" y "Mantén el celular vertical". */
@Composable
internal fun RecordatoriosFijos() {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Timer, null, tint = TextoSecundario, modifier = Modifier.size(34.dp))
            Spacer(Modifier.width(10.dp))
            Text("Más despacio", color = TextoSecundario, fontSize = 15.sp)
        }
        // Divisor vertical
        Spacer(Modifier.width(1.dp).height(32.dp).background(Color(0xFF1F2937)))
        Row(
            Modifier.weight(1f).padding(start = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.PhoneAndroid, null, tint = TextoSecundario, modifier = Modifier.size(34.dp))
            Spacer(Modifier.width(10.dp))
            Text("Mantén el celular vertical", color = TextoSecundario, fontSize = 15.sp)
        }
    }
}

/** Tarjeta que indica si el teléfono está vertical (verde) o hay que enderezarlo (rojo). */
@Composable
internal fun IndicadorInclinacion(inclinacionOk: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Panel)
            .border(1.dp, Color(0xFF1F2937), RoundedCornerShape(16.dp))
            .padding(horizontal = 20.dp, vertical = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.PhoneAndroid, null, tint = Morado, modifier = Modifier.size(30.dp))
        Spacer(Modifier.width(16.dp))
        Text(
            text = if (inclinacionOk) "Tu teléfono está en posición correcta"
            else "Endereza el teléfono: mantenlo vertical",
            color = TextoSecundario,
            fontSize = 15.sp,
            modifier = Modifier.weight(1f),
        )
        Icon(
            if (inclinacionOk) Icons.Default.CheckCircle else Icons.Default.Warning,
            contentDescription = null,
            // El color no es la única señal: también cambia el ícono y el texto.
            tint = if (inclinacionOk) Verde else Rojo,
            modifier = Modifier.size(30.dp),
        )
    }
}

/** Botones grandes (60 dp de alto) "Cancelar" y "Repetir". */
@Composable
internal fun BotonesAccion(onCancelar: () -> Unit, onRepetir: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Button(
            onClick = onCancelar,
            modifier = Modifier.fillMaxWidth().height(60.dp),
            shape = RoundedCornerShape(30.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MoradoBoton, contentColor = Color.White),
        ) {
            Icon(Icons.Default.Close, null)
            Spacer(Modifier.width(10.dp))
            Text("Cancelar", fontSize = 20.sp)
        }

        Spacer(Modifier.height(14.dp))

        OutlinedButton(
            onClick = onRepetir,
            modifier = Modifier.fillMaxWidth().height(60.dp),
            shape = RoundedCornerShape(30.dp),
            border = BorderStroke(1.dp, Morado),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MoradoClaro),
        ) {
            Icon(Icons.Default.Refresh, null)
            Spacer(Modifier.width(10.dp))
            Text("Repetir", fontSize = 20.sp)
        }
    }
}