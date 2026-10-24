package com.example.myapplication.ui.admin.recoleccion

import com.example.myapplication.domain.model.InicioRecoleccion
import com.example.myapplication.domain.model.LugarDestino
import java.util.Locale

/** Máximo de caracteres del nombre del video (mismo límite que renombrar en 7.14). */
const val MAX_NOMBRE_VIDEO = 40

/** Prefijo del nombre autonumerado ("video_3"). Cámbialo aquí si prefieres "video3". */
const val PREFIJO_VIDEO = "video_"

/** Punto en WGS84. */
data class PuntoMapa(val lat: Double, val lng: Double)

/** Final del video anterior: de aquí sale "Usar mi última posición". */
data class UltimaPosicion(
    val punto: PuntoMapa,
    /** `null` si la foto no guardó rumbo. */
    val rumbo: Float?,
    val videoNombre: String,
)

enum class CampoCoordenada { LATITUD, LONGITUD }

/** Diálogo abierto para editar una coordenada a mano. */
data class EdicionCoordenada(
    val campo: CampoCoordenada,
    val texto: String,
    val error: Boolean = false,
)

internal object CampusMapa {
    /** ⚠ Aproximado (EAFIT). Solo es el encuadre inicial: ajústalo al centro real del campus. */
    val CENTRO = PuntoMapa(6.2006, -75.5783)
    const val ZOOM_INICIAL = 17
}

data class UbicacionManualUiState(
    val lugares: List<LugarDestino> = emptyList(),
    /** `null` hasta que el admin toca el mapa, edita una coordenada o usa su última posición. */
    val punto: PuntoMapa? = null,
    /** Grados 0…360, 0 = norte, sentido horario. */
    val rumbo: Float = 0f,
    val brujulaDisponible: Boolean = false,
    val usandoBrujula: Boolean = false,
    val cargandoUltima: Boolean = true,
    val ultimaPosicion: UltimaPosicion? = null,
    /** `true` si el punto actual salió de "Usar mi última posición" y no se ha movido. */
    val ultimaAplicada: Boolean = false,
    val nombreVideo: String = "",
    val nombreSugerido: String = "",
    val edicion: EdicionCoordenada? = null,
    /** Sube cada vez que el punto cambia desde fuera del mapa: la pantalla centra el mapa. */
    val centrarSolicitud: Int = 0,
    val confirmando: Boolean = false,
) {
    /** Sin punto no se puede empezar: un ancla equivocada contamina todo el video. */
    val puedeConfirmar: Boolean get() = punto != null && !confirmando

    val latitudTexto: String get() = punto?.let { formatearCoordenada(it.lat) } ?: "—"
    val longitudTexto: String get() = punto?.let { formatearCoordenada(it.lng) } ?: "—"
}

/** 6 decimales ≈ 0,1 m; siempre con punto, sin importar la región. */
internal fun formatearCoordenada(valor: Double): String =
    String.format(Locale.US, "%.6f", valor)

sealed interface UbicacionManualEvento {
    data class Confirmado(val inicio: InicioRecoleccion) : UbicacionManualEvento
}

/** Acciones de la pantalla agrupadas (convención de 11.1). */
data class UbicacionManualAcciones(
    val onVolver: () -> Unit = {},
    val onAjustes: () -> Unit = {},
    val onPuntoCambiado: (lat: Double, lng: Double) -> Unit = { _, _ -> },
    val onRumbo: (Float) -> Unit = {},
    val onAlternarBrujula: () -> Unit = {},
    val onEditarCoordenada: (CampoCoordenada) -> Unit = {},
    val onTextoEdicion: (String) -> Unit = {},
    val onAceptarEdicion: () -> Unit = {},
    val onCancelarEdicion: () -> Unit = {},
    val onUsarUltima: () -> Unit = {},
    val onNombre: (String) -> Unit = {},
    val onCancelar: () -> Unit = {},
    val onConfirmar: () -> Unit = {},
    val onCalibrar: () -> Unit = {},
)