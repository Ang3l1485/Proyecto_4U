package com.example.myapplication.ui.navegacion

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.domain.guia.EstadoGuia
import com.example.myapplication.domain.guia.FalloFrame
import kotlinx.coroutines.TimeoutCancellationException
import java.io.IOException
import kotlin.math.roundToInt

/**
 * Estado de la vista 6.5 (Navegación guiada, FE-5.3). [instruccion]: lo último dicho, en grande; [restante]: «Faltan
 * N metros»; [seguimiento]: el estado discreto de las fotos; [error]: no se pudo empezar la guía (sin ubicación, sin
 * ruta, grafo inválido); [simulacion]: modo de simulación (APK de depuración).
 */
data class NavegacionUiState(
    val destino: String = "",
    val instruccion: String = "Preparando la guía…",
    val restante: String? = null,
    val seguimiento: String? = null,
    val error: String? = null,
    val simulacion: Boolean = false,
) {
    companion object {
        /** Textos de la pantalla a partir del estado de la guía. */
        fun de(e: EstadoGuia, simulacion: Boolean): NavegacionUiState = NavegacionUiState(
            destino = e.destino,
            instruccion = e.instruccion,
            restante = if (e.llegado) null else "Faltan ${e.metrosRestantes.roundToInt()} m por el camino",
            seguimiento = buildList {
                add("Fotos: ${e.fotosPedidas} pedidas, ${e.fotosAceptadas} aceptadas")
                e.ultimaFoto?.let { add("última $it") }
                if (e.sinConexion) add("sin conexión: solo pasos")
                if (e.recalculos > 0) add("recalculada ${e.recalculos} ${if (e.recalculos == 1) "vez" else "veces"}")
            }.joinToString(" · "),
            simulacion = simulacion,
        )
    }
}

/** Cosas de una sola vez que hace la pantalla (dueña de la cámara, del PDR y de la navegación). */
sealed interface NavegacionEvento {
    data object TomarFoto : NavegacionEvento
    data class CorregirPosicion(val lat: Double, val lng: Double) : NavegacionEvento
    data object Llegada : NavegacionEvento
}

/** Acciones de 6.5 (valores por defecto para la vista previa). */
data class NavegacionAcciones(
    val onRepetir: () -> Unit = {},
    val onTerminar: () -> Unit = {},
)

/**
 * Qué [FalloFrame] es una excepción de `POST /v1/localize/frame` (`ClasificarFalloFrameTest`), en este orden: tiempo
 * agotado → sin conexión; foto ilegible → foto no válida; `503` (o `EMBEDDING_NO_DISPONIBLE`) → servicio no disponible;
 * `400 FOTOS_INVALIDAS` → foto no válida; otra `ApiException` → otro; otra `IOException` (sin red) → sin conexión; el
 * resto (respuesta rota…) → otro.
 */
internal fun falloFrameDe(t: Throwable): FalloFrame = when {
    t is TimeoutCancellationException -> FalloFrame.SIN_CONEXION
    t is FotoIlegibleException -> FalloFrame.FOTO_NO_VALIDA
    t is ApiException && (t.http == 503 || t.fallo == FalloApi.EmbeddingNoDisponible) -> FalloFrame.SERVICIO_NO_DISPONIBLE
    t is ApiException && t.fallo is FalloApi.FotosInvalidas -> FalloFrame.FOTO_NO_VALIDA
    t is ApiException -> FalloFrame.OTRO
    t is IOException -> FalloFrame.SIN_CONEXION
    else -> FalloFrame.OTRO
}
