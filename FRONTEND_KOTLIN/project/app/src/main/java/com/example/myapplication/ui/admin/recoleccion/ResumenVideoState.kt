package com.example.myapplication.ui.admin.recoleccion

import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.domain.model.EstadoFoto

/** Una foto del carrusel de 7.5. [ruta] es la ruta absoluta del JPG original en `files/recoleccion/`. */
data class FotoResumen(val id: String, val ruta: String, val estado: EstadoFoto, val error: String? = null)

/** Lo que dice la cola de subida sobre **este** recorrido (`EstadoCola` filtrado por `videoId`). */
data class SubidaUi(
    val fase: FaseCola = FaseCola.INACTIVA,
    val hechas: Int = 0,
    val total: Int = 0,
    val mensaje: String? = null,
    val reintentoEnS: Int? = null,
) {
    val activa: Boolean
        get() = fase == FaseCola.PREPARANDO || fase == FaseCola.SUBIENDO || fase == FaseCola.COMPLETANDO ||
            fase == FaseCola.SIN_CONEXION
}

/** Estado de la vista 7.5 (`ResumenVideoViewModel.ui`). */
data class ResumenVideoUiState(
    val cargando: Boolean = true,
    /** No hay recorrido que mostrar (id inexistente o manifest ilegible). */
    val noEncontrado: Boolean = false,
    val videoId: String? = null,
    /** Lo que hay en el campo de texto (puede no estar guardado todavía). */
    val nombre: String = "",
    /** `name` guardado en el manifest. */
    val nombreGuardado: String = "",
    val estadoSubida: EstadoSubida = EstadoSubida.SIN_SUBIR,
    /** Ya tiene `remote_video_id`: nombre y fotos no se pueden cambiar aquí. */
    val enviadoAlBackend: Boolean = false,
    val duracionSegundos: Long = 0,
    val distanciaMetros: Double = 0.0,
    val pasos: Int = 0,
    val fotos: List<FotoResumen> = emptyList(),
    /** `[{id, lat, lng, rumbo|null}]` para `RecoleccionMapaContent`. */
    val fotosJson: String = "[]",
    /** `[[lat, lng], …]`: `progress.track` o, si no hay, las fotos en orden. */
    val trayectoriaJson: String = "[]",
    val subida: SubidaUi = SubidaUi(),
    /** `estado` del video en el backend tras consultar `GET /v1/admin/videos/{id}` (`procesando`, `procesado`…). */
    val estadoRemoto: String? = null,
    /** Id de la foto abierta en grande (diálogo con «Descartar foto»). */
    val fotoAbierta: String? = null,
    val confirmandoDescartar: Boolean = false,
    /** Aviso temporal (se descarta al tocarlo). */
    val aviso: String? = null,
) {
    /** Nombre y fotos se pueden cambiar: el backend aún no conoce el video y la cola no lo está subiendo. */
    val editable: Boolean
        get() = !enviadoAlBackend && estadoSubida != EstadoSubida.COMPLETADA && !subida.activa

    val puedeSubir: Boolean
        get() = videoId != null && fotos.isNotEmpty() && estadoSubida != EstadoSubida.COMPLETADA && !subida.activa &&
            nombre.isNotBlank()

    /** Fotos que ya no están pendientes (subidas, procesadas o con error). */
    val subidas: Int get() = fotos.count { it.estado != EstadoFoto.PENDIENTE }

    val conteo: Map<EstadoFoto, Int> get() = fotos.groupingBy { it.estado }.eachCount()

    /** Subida completa y el backend terminó con todas (procesadas o con error). */
    val terminado: Boolean
        get() = estadoSubida == EstadoSubida.COMPLETADA && fotos.isNotEmpty() &&
            fotos.all { it.estado == EstadoFoto.PROCESADA || it.estado == EstadoFoto.ERROR }
}

sealed interface ResumenVideoEvento {
    /** Salir de 7.5 al Panel (la ruta decide cómo). */
    data object IrAlPanel : ResumenVideoEvento
}

/** Acciones de `ResumenVideoContent` (`{}` por defecto, para los previews). */
data class ResumenVideoAcciones(
    val onVolver: () -> Unit = {},
    val onNombre: (String) -> Unit = {},
    val onAbrirFoto: (String) -> Unit = {},
    val onCerrarFoto: () -> Unit = {},
    val onDescartarFoto: (String) -> Unit = {},
    val onSubir: () -> Unit = {},
    val onGuardarDespues: () -> Unit = {},
    val onPedirDescartar: () -> Unit = {},
    val onConfirmarDescartar: () -> Unit = {},
    val onCancelarDescartar: () -> Unit = {},
    val onDescartarAviso: () -> Unit = {},
    /** Con la cola en `ESPERANDO_SESION`: ir a Login (vía `EventosSesion`). */
    val onIniciarSesion: () -> Unit = {},
)
