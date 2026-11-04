package com.example.myapplication.ui.admin.imagenes

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.RemoteLugaresAdminRepository
import com.example.myapplication.data.remote.RemoteVideoRepository
import com.example.myapplication.data.repository.CambiosVideos
import com.example.myapplication.data.repository.ImagenesRepository
import com.example.myapplication.data.repository.LugaresAdminRepository
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.data.repository.VideoRepositoryCompuesto
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.FiltrosImagenes
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.ui.admin.videos.TextosVideos
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Fotos por página: el `por_pagina` que se pide al backend (su `PAGINA_POR_DEFECTO` también es 24). */
const val FOTOS_POR_PAGINA = 24

enum class ModoVista { CUADRICULA, MAPA }

/**
 * Filtros de la Galería (FE-4.1: los aplica el **servidor**, `GET /v1/admin/images`). [lugarId] y [videoId] son ids;
 * [busqueda] es el `q` del backend (nombre del video o notas de la foto).
 */
data class GaleriaFiltros(
    val busqueda: String = "",
    val lugarId: String? = null,
    val videoId: String? = null,
    val estado: EstadoFoto? = null,
    val calidad: CalidadFoto? = null,
) {
    val hayActivos: Boolean
        get() = busqueda.isNotBlank() || lugarId != null || videoId != null || estado != null || calidad != null

    fun aDominio(): FiltrosImagenes = FiltrosImagenes(
        q = busqueda.trim().ifEmpty { null },
        videoId = videoId,
        lugarId = lugarId,
        estado = estado,
        calidad = calidad,
    )
}

/** Una opción de los filtros «Lugar» y «Video» y del selector de «Reasignar». */
data class OpcionFiltro(val id: String, val nombre: String)

/** Lo que se está haciendo con la selección (la pantalla deshabilita la barra mientras tanto). */
enum class OperacionLote { ELIMINANDO, REASIGNANDO }

/**
 * Estado de la Galería (7.11, FE-4.1). [fotos] es **solo la página actual** del servidor; [total] es el `total` de
 * `GET /v1/admin/images` con los filtros activos (el «N imágenes» del encabezado). [seleccion] guarda **ids** de imagen
 * (UUID del backend): se conserva al cambiar de página y se vacía al cambiar un filtro.
 */
data class GaleriaUiState(
    val cargando: Boolean = true,
    val error: String? = null,
    val fotos: List<Foto> = emptyList(),
    val total: Int = 0,
    val filtros: GaleriaFiltros = GaleriaFiltros(),
    val modo: ModoVista = ModoVista.CUADRICULA,
    val pagina: Int = 1,
    val seleccion: Set<String> = emptySet(),
    val videos: List<OpcionFiltro> = emptyList(),
    val lugares: List<OpcionFiltro> = emptyList(),
    val lugaresCargados: Boolean = false,
    val operacion: OperacionLote? = null,
    val aviso: String? = null,
) {
    val totalPaginas: Int get() = maxOf(1, (total + FOTOS_POR_PAGINA - 1) / FOTOS_POR_PAGINA)

    /** Nombre del lugar del filtro (si la lista de lugares aún no llegó, «el lugar elegido»). */
    val nombreLugarFiltrado: String?
        get() = filtros.lugarId?.let { id -> lugares.firstOrNull { it.id == id }?.nombre ?: "el lugar elegido" }
}

/**
 * ViewModel de la Galería (7.11, FE-4.1): fotos del servidor con paginación (24) y filtros del servidor; Eliminar y
 * Reasignar en lote con `POST /v1/admin/images/lote` (en partes de 200) y lugares reales. Recarga la página cuando
 * cambian los videos o las fotos ([cambios]: `CambiosVideos`, que sube tras cada escritura de 7.11 y 7.14). Las fotos de
 * los recorridos del teléfono sin subir **no** salen (se ven en 7.5 y en su 7.14).
 */
class GaleriaViewModel(
    private val imagenes: ImagenesRepository,
    private val videos: VideoRepository,
    private val lugares: LugaresAdminRepository,
    cambios: Flow<Int> = CambiosVideos.version,
    filtrosIniciales: GaleriaFiltros = GaleriaFiltros(),
    private val reloj: () -> Long = System::currentTimeMillis,
) : ViewModel() {

    private val _ui = MutableStateFlow(GaleriaUiState(filtros = filtrosIniciales))
    val uiState: StateFlow<GaleriaUiState> = _ui.asStateFlow()

    private var carga: Job? = null
    private var vencen: Long? = null

    init {
        cargarOpciones()
        cargar()
        viewModelScope.launch { cambios.drop(1).collect { cargar(silencioso = true) } }
    }

    /** Pide la página actual (cancela la carga anterior). [espera] = demora antes de pedir (búsqueda al teclear). */
    fun cargar(silencioso: Boolean = false, espera: Long = 0) {
        carga?.cancel()
        if (!silencioso) _ui.update { it.copy(cargando = true, error = null) }
        carga = viewModelScope.launch {
            if (espera > 0) delay(espera)
            val s = _ui.value
            try {
                val p = imagenes.imagenes(s.filtros.aDominio(), s.pagina, FOTOS_POR_PAGINA)
                val ultima = maxOf(1, (p.total + FOTOS_POR_PAGINA - 1) / FOTOS_POR_PAGINA)
                if (p.fotos.isEmpty() && p.total > 0 && s.pagina > ultima) {
                    // Tras borrar, la página quedó más allá del final: se pide la última.
                    _ui.update { it.copy(pagina = ultima) }
                    cargar(silencioso = true)
                    return@launch
                }
                vencen = p.vencenEnMs
                val nombres = _ui.value.videos.associate { it.id to it.nombre }
                _ui.update {
                    it.copy(
                        cargando = false,
                        error = null,
                        fotos = p.fotos.map { f -> f.copy(videoNombre = nombres[f.videoId] ?: f.videoNombre) },
                        total = p.total,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(cargando = false, error = TextosVideos.error(e, "cargar las imágenes")) }
            }
        }
    }

    /** Videos (para el filtro y los nombres de las tarjetas) y lugares (filtro y «Reasignar»). Un fallo no es fatal. */
    private fun cargarOpciones() {
        viewModelScope.launch {
            val lista = try {
                videos.listarVideos().servidor.map { OpcionFiltro(it.id, it.nombre) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                emptyList()
            }
            val nombres = lista.associate { it.id to it.nombre }
            _ui.update { s ->
                s.copy(videos = lista, fotos = s.fotos.map { f -> f.copy(videoNombre = nombres[f.videoId] ?: f.videoNombre) })
            }
        }
        viewModelScope.launch {
            val lista = try {
                lugares.listar().map { OpcionFiltro(it.id, it.nombre) }.sortedBy { it.nombre.lowercase() }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                null
            }
            _ui.update { it.copy(lugares = lista.orEmpty(), lugaresCargados = lista != null) }
        }
    }

    // ── Filtros ─────────────────────────────────────────────────────────────

    fun buscar(texto: String) {
        _ui.update { it.copy(filtros = it.filtros.copy(busqueda = texto.take(MAX_BUSQUEDA)), pagina = 1, seleccion = emptySet()) }
        cargar(espera = ESPERA_BUSQUEDA_MS)
    }

    fun filtrarLugar(lugarId: String?) = cambiarFiltros { it.copy(lugarId = lugarId) }
    fun filtrarVideo(videoId: String?) = cambiarFiltros { it.copy(videoId = videoId) }
    fun filtrarEstado(estado: EstadoFoto?) = cambiarFiltros { it.copy(estado = estado) }
    fun filtrarCalidad(calidad: CalidadFoto?) = cambiarFiltros { it.copy(calidad = calidad) }
    fun limpiarFiltros() = cambiarFiltros { GaleriaFiltros() }

    /** Al cambiar filtros se vuelve a la página 1 y se limpia la selección (evita acciones sobre fotos ocultas). */
    private fun cambiarFiltros(cambio: (GaleriaFiltros) -> GaleriaFiltros) {
        _ui.update { it.copy(filtros = cambio(it.filtros), pagina = 1, seleccion = emptySet()) }
        cargar()
    }

    // ── Vista y paginación ──────────────────────────────────────────────────

    fun cambiarModo(modo: ModoVista) = _ui.update { it.copy(modo = modo) }

    fun irAPagina(pagina: Int) {
        val destino = pagina.coerceIn(1, _ui.value.totalPaginas)
        if (destino == _ui.value.pagina) return
        _ui.update { it.copy(pagina = destino) }
        cargar()
    }

    /** ON_RESUME: si las URLs de la página vencen en menos de [MARGEN_URLS_MS], se vuelve a pedir la página. */
    fun alReanudar() {
        val v = vencen ?: return
        if (reloj() >= v - MARGEN_URLS_MS) cargar(silencioso = true)
    }

    // ── Selección y acciones en lote ────────────────────────────────────────

    fun alternarSeleccion(id: String) = _ui.update {
        it.copy(seleccion = if (id in it.seleccion) it.seleccion - id else it.seleccion + id)
    }

    fun limpiarSeleccion() = _ui.update { it.copy(seleccion = emptySet()) }

    fun descartarAviso() = _ui.update { it.copy(aviso = null) }

    /** `POST /v1/admin/images/lote` con `eliminar`. Informa las procesadas y las `fallidas`. */
    fun eliminarSeleccion() = lote(AccionLote.ELIMINAR, null, null)

    /** `POST /v1/admin/images/lote` con `reasignar` a [lugarId] (`null` = «Sin lugar»). */
    fun reasignarSeleccion(lugarId: String?) {
        val nombre = lugarId?.let { id -> _ui.value.lugares.firstOrNull { it.id == id }?.nombre }
        lote(AccionLote.REASIGNAR, lugarId, nombre)
    }

    private fun lote(accion: AccionLote, lugarId: String?, nombreLugar: String?) {
        val s = _ui.value
        if (s.seleccion.isEmpty() || s.operacion != null) return
        val ids = s.seleccion.toList()
        _ui.update {
            it.copy(operacion = if (accion == AccionLote.ELIMINAR) OperacionLote.ELIMINANDO else OperacionLote.REASIGNANDO)
        }
        viewModelScope.launch {
            try {
                val r = imagenes.lote(accion, ids, lugarId)
                // La página se recarga sola por `CambiosVideos` (el repositorio avisa tras el lote).
                _ui.update {
                    it.copy(operacion = null, seleccion = emptySet(), aviso = TextosVideos.resultadoLote(accion, r, nombreLugar))
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val que = if (accion == AccionLote.ELIMINAR) "eliminar las fotos" else "reasignar las fotos"
                _ui.update { it.copy(operacion = null, aviso = TextosVideos.error(e, que)) }
            }
        }
    }

    /**
     * Factory (FE-4.1): [lugarId] y [videoId] son los filtros con que se abre (argumentos de la ruta `admin/imagenes`).
     */
    class Factory(private val lugarId: String? = null, private val videoId: String? = null) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            GaleriaViewModel(
                imagenes = RemoteVideoRepository(),
                videos = VideoRepositoryCompuesto.deLaApp(),
                lugares = RemoteLugaresAdminRepository(),
                filtrosIniciales = GaleriaFiltros(lugarId = lugarId, videoId = videoId),
            ) as T
    }

    companion object {
        const val ESPERA_BUSQUEDA_MS = 400L
        const val MAX_BUSQUEDA = 100
        const val MARGEN_URLS_MS = 5 * 60_000L
    }
}