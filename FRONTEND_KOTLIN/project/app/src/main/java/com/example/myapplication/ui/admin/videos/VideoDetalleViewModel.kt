package com.example.myapplication.ui.admin.videos

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.repository.RecorridoNoEditableException
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.data.repository.VideoRepositoryCompuesto
import com.example.myapplication.domain.model.PuntosOtros
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** Lo que se está haciendo en 7.14 (FE-4.1): la pantalla tapa el mapa con un aviso mientras dura. */
enum class OperacionVideo(val texto: String) {
    RENOMBRANDO("Guardando el nombre…"),
    ELIMINANDO_FOTO("Eliminando la foto…"),
    ELIMINANDO_VIDEO("Eliminando el video…"),
}

/** Qué se repite con «Reintentar» tras un error. */
sealed interface ReintentoVideo {
    data class Renombrar(val nombre: String) : ReintentoVideo
    data class EliminarFoto(val fotoId: String) : ReintentoVideo
    data object EliminarVideo : ReintentoVideo
}

/** Un error de una operación: título, mensaje para la persona y, si se puede, qué repetir. */
data class AvisoVideo(val titulo: String, val mensaje: String, val reintento: ReintentoVideo?)

/**
 * Estado de 7.14 (FE-4.1). El mapa web recibe todo como JSON: [videoJson] (con `rev`, que cambia en cada carga para que
 * la página reciba el video aunque no haya cambiado, p. ej. tras un borrado de foto que falló) y [otrosJson] (`null`
 * hasta que la página lo pide con «Mostrar otros videos»).
 */
data class VideoDetalleUiState(
    val cargando: Boolean = true,
    val noEncontrado: Boolean = false,
    val errorCarga: String? = null,
    val videoJson: String? = null,
    val otrosJson: String? = null,
    val nombre: String = "",
    val operacion: OperacionVideo? = null,
    val aviso: AvisoVideo? = null,
)

sealed interface VideoDetalleEvento {
    /** El borrado se confirmó: la pantalla avisa y vuelve a la Lista. [fotos] = `fotos_retiradas` (`null` en uno local). */
    data class Eliminado(val nombre: String, val fotos: Int?) : VideoDetalleEvento
}

/**
 * ViewModel de 7.14 (FE-4.1). Carga con `repositorio.obtenerVideo(videoId)` cada vez que emite `repositorio.cambios()`
 * (la primera emisión es la carga inicial). Renombrar, eliminar una foto y eliminar el video atrapan **toda** excepción
 * (salvo la cancelación): nunca cierran la app; muestran [VideoDetalleUiState.aviso] con «Reintentar». Eliminar el video
 * **espera** la respuesta (`202`) y solo entonces emite [VideoDetalleEvento.Eliminado]. Las URLs prefirmadas se renuevan
 * solas: con la pantalla visible ([alReanudar]) se recarga [MARGEN_URLS_MS] antes de que venzan.
 */
class VideoDetalleViewModel(
    private val videoId: String,
    private val repositorio: VideoRepository,
    private val reloj: () -> Long = System::currentTimeMillis,
) : ViewModel() {

    private val _ui = MutableStateFlow(VideoDetalleUiState())
    val ui: StateFlow<VideoDetalleUiState> = _ui.asStateFlow()

    private val _eventos = Channel<VideoDetalleEvento>(Channel.BUFFERED)
    val eventos: Flow<VideoDetalleEvento> = _eventos.receiveAsFlow()

    /** Una vez visto el video, si desaparece (lo eliminamos nosotros) no se muestra "no encontrado". */
    private var huboVideo = false
    private var eliminado = false
    private var rev = 0
    private var vencen: Long? = null
    private var renovacion: Job? = null
    private var otrosPedidos = false

    init {
        viewModelScope.launch { repositorio.cambios().collect { cargar() } }
    }

    fun reintentarCarga() {
        _ui.update { it.copy(cargando = true, errorCarga = null) }
        viewModelScope.launch { cargar() }
    }

    private suspend fun cargar() {
        if (eliminado) return
        try {
            val video = repositorio.obtenerVideo(videoId)
            if (video != null) huboVideo = true
            vencen = video?.urlsVencenEnMs
            _ui.update {
                it.copy(
                    cargando = false,
                    errorCarga = null,
                    noEncontrado = video == null && !huboVideo,
                    videoJson = video?.let(::videoAJson) ?: it.videoJson,
                    nombre = video?.nombre ?: it.nombre,
                )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val texto = TextosVideos.error(e, "cargar el video")
            _ui.update { it.copy(cargando = false, errorCarga = if (huboVideo) null else texto) }
        }
    }

    fun renombrar(nombre: String) {
        val limpio = nombre.trim()
        if (limpio.isEmpty() || limpio.length > MAX_NOMBRE || _ui.value.operacion != null) return
        operar(OperacionVideo.RENOMBRANDO, "No se pudo renombrar", "renombrar el video", ReintentoVideo.Renombrar(limpio)) {
            repositorio.renombrarVideo(videoId, limpio)
        }
    }

    fun eliminarFoto(fotoId: String) {
        if (_ui.value.operacion != null) return
        operar(OperacionVideo.ELIMINANDO_FOTO, "No se pudo eliminar la foto", "eliminar la foto", ReintentoVideo.EliminarFoto(fotoId)) {
            repositorio.eliminarFoto(videoId, fotoId)
        }
    }

    fun eliminarVideo() {
        if (_ui.value.operacion != null) return
        val nombre = _ui.value.nombre
        operar(OperacionVideo.ELIMINANDO_VIDEO, "No se pudo eliminar el video", "eliminar el video", ReintentoVideo.EliminarVideo) {
            val fotos = repositorio.eliminarVideo(videoId)
            eliminado = true
            _eventos.send(VideoDetalleEvento.Eliminado(nombre, fotos))
        }
    }

    fun reintentar() {
        when (val r = _ui.value.aviso?.reintento) {
            is ReintentoVideo.Renombrar -> { descartarAviso(); renombrar(r.nombre) }
            is ReintentoVideo.EliminarFoto -> { descartarAviso(); eliminarFoto(r.fotoId) }
            ReintentoVideo.EliminarVideo -> { descartarAviso(); eliminarVideo() }
            null -> descartarAviso()
        }
    }

    fun descartarAviso() = _ui.update { it.copy(aviso = null) }

    /** La página activó «Mostrar otros videos» por primera vez: se cargan (con tope) y se le envían. */
    fun pedirOtros() {
        if (otrosPedidos) return
        otrosPedidos = true
        viewModelScope.launch {
            val otros = try {
                repositorio.puntosDeOtros(videoId)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                PuntosOtros(emptyMap(), aviso = "No se pudieron cargar los otros videos.")
            }
            _ui.update { it.copy(otrosJson = otrosAJson(otros)) }
        }
    }

    /** ON_RESUME de la pantalla: si las URLs vencen pronto recarga ya; si no, programa la recarga antes de que venzan. */
    fun alReanudar() {
        renovacion?.cancel()
        renovacion = viewModelScope.launch {
            while (true) {
                val v = vencen ?: return@launch
                val falta = v - MARGEN_URLS_MS - reloj()
                if (falta > 0) delay(falta)
                if (_ui.value.operacion == null) cargar()
                if (vencen == v) return@launch // la recarga no trajo URLs nuevas: no insistir en bucle
            }
        }
    }

    /** ON_PAUSE: sin pantalla no hace falta renovar las URLs. */
    fun alPausar() {
        renovacion?.cancel()
        renovacion = null
    }

    private fun operar(
        op: OperacionVideo,
        titulo: String,
        accion: String,
        reintento: ReintentoVideo,
        bloque: suspend () -> Unit,
    ) {
        _ui.update { it.copy(operacion = op, aviso = null) }
        viewModelScope.launch {
            try {
                bloque()
                // Tras eliminar el video el aviso «Eliminando…» se queda hasta que la pantalla sale (evento Eliminado).
                if (!eliminado) _ui.update { it.copy(operacion = null) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val mensaje = TextosVideos.error(e, accion)
                val reintentable = e !is RecorridoNoEditableException
                _ui.update {
                    it.copy(
                        operacion = null,
                        aviso = mensaje?.let { m -> AvisoVideo(titulo, m, reintento.takeIf { reintentable }) },
                    )
                }
                cargar() // vuelve a dibujar lo que hay de verdad (la página quitó la foto o cambió el nombre antes)
            }
        }
    }

    private fun videoAJson(v: Video): String = JSONObject().apply {
        put("id", v.id)
        put("nombre", v.nombre)
        put("fecha", v.creadoEn?.take(10) ?: JSONObject.NULL) // "2026-10-09" (la página la invierte)
        put("local", v.local)
        put("editable", v.editable)
        put("nota", v.nota ?: JSONObject.NULL)
        put("rev", ++rev)
        put("fotos", JSONArray(v.fotos.map { f ->
            JSONObject().apply {
                put("id", f.id)
                put("url", f.urlFoto)
                put("thumb", f.urlMiniatura)
                put("lat", f.lat)
                put("lng", f.lng)
                put("rumbo", f.rumbo?.toDouble() ?: JSONObject.NULL)
            }
        }))
    }.toString()

    private fun otrosAJson(o: PuntosOtros): String = JSONObject().apply {
        put("videos", JSONArray(o.videos.map { (id, puntos) ->
            JSONObject().apply {
                put("id", id)
                put("fotos", JSONArray(puntos.map { p -> JSONObject().put("lat", p.lat).put("lng", p.lng) }))
            }
        }))
        put("aviso", o.aviso ?: JSONObject.NULL)
    }.toString()

    /** Sin contexto desde FE-4.1 (`VideoRepositoryCompuesto.deLaApp()`). */
    class Factory(private val videoId: String) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            VideoDetalleViewModel(videoId, VideoRepositoryCompuesto.deLaApp()) as T
    }

    companion object {
        /** Se recargan las URLs prefirmadas 5 min antes de que venzan (viven 1 h, backend §5.10). */
        const val MARGEN_URLS_MS = 5 * 60_000L

        const val MAX_NOMBRE = AlmacenRecorridos.MAX_NOMBRE
    }
}