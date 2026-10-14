package com.example.myapplication.ui.admin.recoleccion

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.ResumenRecoleccion
import com.example.myapplication.domain.usecase.Deriva
import com.example.myapplication.domain.usecase.EstimacionDeriva
import com.example.myapplication.domain.usecase.ModoCaptura

/** Máximo de fotos por video (el "18 / 200" del diseño). Al llegar, se deja de capturar. */
const val MAX_FOTOS_VIDEO = 200

enum class FaseRecoleccion {
    /** Creando el video en disco y arrancando el PDR. */
    INICIANDO,
    GRABANDO,
    PAUSADA,
    /** Cerrando el video (esperando la última foto y escribiendo el manifest). */
    FINALIZANDO,
}

/** Errores que impiden grabar; la pantalla los muestra y ofrece volver. */
enum class ErrorRecoleccion(val mensaje: String) {
    SIN_INICIO("No hay una posición de partida. Vuelve y márcala en el mapa."),
    NO_SE_PUDO_CREAR("No se pudo crear el video. Revisa el almacenamiento del teléfono."),
}

/** Chips de "Alertas" del diseño. Foto borrosa y poca luz quedan sin uso mientras el control de calidad esté desactivado. */
enum class AvisoRecoleccion(val etiqueta: String) {
    FOTO_BORROSA("Foto borrosa"),
    POCA_LUZ("Poca luz"),
    BATERIA_BAJA("Batería baja"),
    ALMACENAMIENTO_BAJO("Almacenamiento bajo"),
}

/** Punto donde el admin quiere re-anclarse (arrastrado en el mapa). */
data class PuntoReanclaje(val lat: Double, val lng: Double)

/**
 * Estado completo de la vista 7.4. La UI solo lo lee; el ViewModel es el único que lo escribe.
 *
 * Los `...Json` ya vienen serializados para el mapa web (Bache 3) y solo se recalculan cuando
 * cambia su contenido, no en cada paso.
 */
data class RecoleccionUiState(
    val fase: FaseRecoleccion = FaseRecoleccion.INICIANDO,
    val error: ErrorRecoleccion? = null,
    val nombreVideo: String = "",

    // Posición actual (PDR). `null` hasta tener punto de partida.
    val lat: Double? = null,
    val lng: Double? = null,
    /** 0..360, 0 = norte. */
    val rumbo: Float = 0f,

    // Contadores
    val fotosTomadas: Int = 0,
    val distanciaMetros: Double = 0.0,
    val pasos: Int = 0,
    val duracionSegundos: Long = 0,

    // Seguimiento y captura
    val deriva: EstimacionDeriva = Deriva.estimar(0.0),
    val modo: ModoCaptura = ModoCaptura.POR_DEFECTO,
    /** Sube en 1 cada vez que se guarda una foto: la UI lo observa para parpadear. */
    val destelloCaptura: Int = 0,
    val avisos: Set<AvisoRecoleccion> = emptySet(),
    /** Mensaje corto y temporal (p. ej. "No se pudo guardar la foto"); la UI lo muestra y llama `descartarAviso()`. */
    val aviso: String? = null,

    // Capas del mapa
    val fotosJson: String = "[]",
    val trayectoriaJson: String = "[]",
    val alertasJson: String = "[]",
    val alertasActivas: Int = 0,

    // Re-anclaje manual: no nulo = el mapa está en modo "arrastra tu posición".
    val reanclaje: PuntoReanclaje? = null,

    // Diálogos
    val confirmandoFinalizar: Boolean = false,
    /** Borrador del formulario de alerta (`AlertaFormSheet`); `null` = cerrado. */
    val formularioAlerta: Alerta? = null,
    val errorAlerta: String? = null,
) {
    val reubicando: Boolean get() = reanclaje != null
    val enCurso: Boolean get() = fase == FaseRecoleccion.GRABANDO || fase == FaseRecoleccion.PAUSADA
    val llegoAlMaximo: Boolean get() = fotosTomadas >= MAX_FOTOS_VIDEO
}

/** Cosas de una sola vez. Van por `Channel`: no se pierden aunque aún no haya colector (un solo colector). */
sealed interface RecoleccionEvento {
    /** La pantalla debe llamar a `tomarFoto` en `viewModel.carpetaFotos()` y avisar el resultado. */
    data object Capturar : RecoleccionEvento

    /** Video cerrado con fotos: ir a la vista 7.5. El resumen también queda en `SesionDeRecoleccion`. */
    data class Finalizado(val resumen: ResumenRecoleccion) : RecoleccionEvento

    /** Se finalizó sin fotos y el video se borró: volver al panel. */
    data object Descartado : RecoleccionEvento
}