package com.example.myapplication.ui.navegacion

import android.app.Application
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.logs.AppLog
import com.example.myapplication.ui.inicio.VoiceController
import com.example.myapplication.ui.theme.CampusColors

/*
 * Vista 6.6 — Llegada (FE-5.3). Dice y muestra la instrucción de llegada de la ruta («Has llegado a X.» o, si el destino
 * queda lejos del grafo, «Has llegado al punto del camino más cercano a X. Está a N metros en línea recta, …»), y ofrece
 * «Ir a otro lugar» y «Volver al inicio». Sin descripción del entorno ni pregunta «¿Llegaste bien?» (pendiente).
 */

/** El texto de llegada que deja la guía (6.5) para la 6.6; en memoria, como `SesionDeNavegacion`. */
object LlegadaGuia {
    @Volatile
    var texto: String? = null

    const val SIN_TEXTO = "Has llegado a tu destino."
}

/** Dice la llegada una vez al abrir (y con «Repetir»). */
class LlegadaViewModel(app: Application) : AndroidViewModel(app) {
    private val voz = VoiceController(app)
    val texto: String = LlegadaGuia.texto ?: LlegadaGuia.SIN_TEXTO
    private var abierto = false

    fun alAbrir() {
        if (abierto) return
        abierto = true
        AppLog.i("Guia", "Llegada mostrada (6.6)")
        voz.speak("$texto $AYUDA")
    }

    fun alPausar() = voz.stopAll()

    override fun onCleared() {
        voz.release()
    }

    companion object {
        const val AYUDA = "Puedes tocar «Ir a otro lugar» o «Volver al inicio»."
    }
}

@Composable
fun LlegadaScreen(
    onIrAOtroLugar: () -> Unit,
    onInicio: () -> Unit,
    viewModel: LlegadaViewModel = viewModel(),
) {
    LaunchedEffect(Unit) { viewModel.alAbrir() }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_STOP) viewModel.alPausar() }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
    }
    LlegadaContent(
        texto = viewModel.texto,
        onIrAOtroLugar = { viewModel.alPausar(); onIrAOtroLugar() },
        onInicio = { viewModel.alPausar(); onInicio() },
    )
}

@Composable
internal fun LlegadaContent(texto: String, onIrAOtroLugar: () -> Unit, onInicio: () -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CampusColors.Fondo)
            .systemBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Llegada", color = CampusColors.TextoSecundario, fontSize = 18.sp, modifier = Modifier.semantics { heading() })
        Text(
            text = texto,
            color = CampusColors.TextoPrincipal,
            fontSize = 32.sp,
            lineHeight = 40.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.semantics {
                heading()
                liveRegion = LiveRegionMode.Polite
            },
        )
        Spacer(Modifier.height(8.dp))
        BotonGrande("Ir a otro lugar", principal = true, onClick = onIrAOtroLugar)
        BotonGrande("Volver al inicio", principal = false, onClick = onInicio)
    }
}

@Preview(showBackground = true)
@Composable
private fun PreviewLlegada() {
    LlegadaContent("Has llegado a Bloque 35.", {}, {})
}
