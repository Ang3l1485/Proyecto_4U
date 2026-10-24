package com.example.myapplication.ui.admin.recoleccion

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.AssetsVideoRepository
import com.example.myapplication.data.repository.LugaresRepository
import com.example.myapplication.data.repository.LugaresRepositoryStub
import com.example.myapplication.data.repository.VideoRepository
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.InicioRecoleccion
import com.example.myapplication.domain.model.Video
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.math.abs

/**
 * Vista 7.3 — Ubicación manual inicial.
 *
 * Solo fija el punto, el rumbo y el nombre. **No crea el video**: `VideoRepository` aún no tiene
 * `crearVideo` (11.6). Al confirmar emite [UbicacionManualEvento.Confirmado] y quien navega (AppNav)
 * decide qué hacer con él.
 */
class UbicacionManualViewModel(
    private val videos: VideoRepository,
    private val lugares: LugaresRepository,
) : ViewModel() {

    private val _ui = MutableStateFlow(UbicacionManualUiState())
    val ui: StateFlow<UbicacionManualUiState> = _ui.asStateFlow()

    /** `Channel` con búfer: un evento emitido antes de que haya colector no se pierde (como Login). */
    private val _eventos = Channel<UbicacionManualEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    private var iniciado = false
    private var rumboFiltrado: Float? = null

    // ── Ciclo de vida ───────────────────────────────────────────────────────────────

    /** Idempotente: la carga solo corre la primera vez; la disponibilidad de brújula se refresca. */
    fun alAbrir(brujulaDisponible: Boolean) {
        _ui.update { it.copy(brujulaDisponible = brujulaDisponible) }
        if (iniciado) return
        iniciado = true
        viewModelScope.launch { cargarVideos() }
        viewModelScope.launch { cargarLugares() }
    }

    /** ON_STOP: apaga la brújula para no gastar batería en segundo plano. */
    fun alPausar() {
        if (_ui.value.usandoBrujula) _ui.update { it.copy(usandoBrujula = false) }
    }

    /** ON_RESUME: al volver (p. ej. desde 7.4) el botón de confirmar vuelve a estar activo. */
    fun alReanudar() {
        if (_ui.value.confirmando) _ui.update { it.copy(confirmando = false) }
    }

    private suspend fun cargarVideos() {
        val lista = try {
            videos.obtenerVideos()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null // sin historial: se puede fijar el punto a mano; "última posición" queda deshabilitada
        }
        _ui.update { s ->
            val sugerido = siguienteNombre(lista.orEmpty())
            s.copy(
                cargandoUltima = false,
                ultimaPosicion = lista?.let(::calcularUltimaPosicion),
                nombreSugerido = sugerido,
                // No pisa lo que la persona ya haya escrito mientras cargaba.
                nombreVideo = s.nombreVideo.ifEmpty { sugerido },
            )
        }
    }

    private suspend fun cargarLugares() {
        val lista = try {
            lugares.obtenerLugares()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            emptyList() // sin lugares el mapa solo pierde las etiquetas de referencia
        }
        _ui.update { it.copy(lugares = lista) }
    }

    // ── Punto ───────────────────────────────────────────────────────────────────────

    /** Toque o arrastre en el mapa. No pide centrar: el mapa ya está donde la persona lo puso. */
    fun alMoverPunto(lat: Double, lng: Double) {
        if (!lat.isFinite() || !lng.isFinite()) return
        _ui.update {
            it.copy(
                punto = PuntoMapa(lat.coerceIn(-90.0, 90.0), lng.coerceIn(-180.0, 180.0)),
                ultimaAplicada = false,
            )
        }
    }

    /** Copia punto y rumbo del final del video anterior. La persona aún debe confirmar. */
    fun alUsarUltimaPosicion() {
        val ultima = _ui.value.ultimaPosicion ?: return
        rumboFiltrado = null
        _ui.update {
            it.copy(
                punto = ultima.punto,
                rumbo = ultima.rumbo?.let(Rumbo::normalizar) ?: it.rumbo,
                usandoBrujula = false,
                ultimaAplicada = true,
                centrarSolicitud = it.centrarSolicitud + 1,
            )
        }
    }

    // ── Rumbo ───────────────────────────────────────────────────────────────────────

    /** Dial manual: tomar el control apaga la brújula. */
    fun alElegirRumbo(grados: Float) {
        rumboFiltrado = null
        _ui.update { it.copy(rumbo = Rumbo.normalizar(grados), usandoBrujula = false) }
    }

    fun alAlternarBrujula() {
        if (!_ui.value.brujulaDisponible) return
        rumboFiltrado = null
        _ui.update { it.copy(usandoBrujula = !it.usandoBrujula) }
    }

    /**
     * Lectura de [com.example.myapplication.sensors.EscucharOrientacion] (~50 Hz, −180…180).
     * Se normaliza y se suaviza; solo se actualiza el estado si el cambio es de ≥ 1,5°.
     */
    fun alLeerBrujula(acimutGrados: Float) {
        if (!_ui.value.usandoBrujula) return
        val nuevo = Rumbo.suavizar(rumboFiltrado, Rumbo.normalizar(acimutGrados))
        rumboFiltrado = nuevo
        if (Rumbo.diferencia(nuevo, _ui.value.rumbo) >= 1.5f) {
            _ui.update { it.copy(rumbo = nuevo) }
        }
    }

    // ── Coordenadas editables ───────────────────────────────────────────────────────

    fun alEditarCoordenada(campo: CampoCoordenada) {
        val p = _ui.value.punto
        val texto = when {
            p == null -> ""
            campo == CampoCoordenada.LATITUD -> formatearCoordenada(p.lat)
            else -> formatearCoordenada(p.lng)
        }
        _ui.update { it.copy(edicion = EdicionCoordenada(campo, texto)) }
    }

    fun alCambiarTextoEdicion(texto: String) {
        _ui.update { s -> s.copy(edicion = s.edicion?.copy(texto = texto, error = false)) }
    }

    fun alCancelarEdicion() {
        _ui.update { it.copy(edicion = null) }
    }

    /**
     * Valida y aplica. Con [CampoCoordenada.LATITUD] en ±90 y [CampoCoordenada.LONGITUD] en ±180;
     * acepta coma o punto. Si aún no había punto, la otra coordenada se toma del centro del campus.
     */
    fun alAceptarEdicion() {
        val s = _ui.value
        val e = s.edicion ?: return
        val limite = if (e.campo == CampoCoordenada.LATITUD) 90.0 else 180.0
        val valor = parsearCoordenada(e.texto, limite)
        if (valor == null) {
            _ui.update { it.copy(edicion = e.copy(error = true)) }
            return
        }
        val base = s.punto ?: CampusMapa.CENTRO
        val nuevo = if (e.campo == CampoCoordenada.LATITUD) base.copy(lat = valor) else base.copy(lng = valor)
        _ui.update {
            it.copy(
                punto = nuevo,
                edicion = null,
                ultimaAplicada = false,
                centrarSolicitud = it.centrarSolicitud + 1,
            )
        }
    }

    // ── Nombre y confirmación ───────────────────────────────────────────────────────

    fun alCambiarNombre(texto: String) {
        _ui.update { it.copy(nombreVideo = texto.take(MAX_NOMBRE_VIDEO)) }
    }

    fun alConfirmar() {
        val s = _ui.value
        val p = s.punto ?: return
        if (s.confirmando) return
        val nombre = s.nombreVideo.trim().ifBlank { s.nombreSugerido.ifBlank { "${PREFIJO_VIDEO}1" } }
        _ui.update { it.copy(confirmando = true) }
        _eventos.trySend(
            UbicacionManualEvento.Confirmado(
                InicioRecoleccion(
                    lat = p.lat,
                    lng = p.lng,
                    rumbo = s.rumbo,
                    nombreVideo = nombre,
                    continuaVideoAnterior = s.ultimaAplicada,
                ),
            ),
        )
    }

    class Factory(private val appContext: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            UbicacionManualViewModel(
                videos = AssetsVideoRepository(appContext),
                lugares = LugaresRepositoryStub(),
            ) as T
    }
}

// ── Lógica pura (sin Android: se puede probar con pruebas unitarias) ────────────────

/** Utilidades de rumbo en grados, 0 = norte, sentido horario. */
internal object Rumbo {
    private val CARDINALES = listOf("N", "NE", "E", "SE", "S", "SO", "O", "NO")
    private val NOMBRES = listOf(
        "norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste",
    )

    /** A 0…360. Sirve para el acimut de `OrientationProvider`, que sale en −180…180 (11.2). */
    fun normalizar(grados: Float): Float {
        val r = grados % 360f
        return if (r < 0f) r + 360f else r
    }

    /** Diferencia angular más corta, 0…180. */
    fun diferencia(a: Float, b: Float): Float {
        val d = abs(normalizar(a) - normalizar(b))
        return if (d > 180f) 360f - d else d
    }

    /** Promedio exponencial **circular**: 359° y 1° se promedian cerca de 0°, no de 180°. */
    fun suavizar(anterior: Float?, nuevo: Float, alfa: Float = 0.2f): Float {
        if (anterior == null) return nuevo
        var delta = nuevo - anterior
        if (delta > 180f) delta -= 360f else if (delta < -180f) delta += 360f
        return normalizar(anterior + alfa * delta)
    }

    private fun indice(grados: Float): Int = ((normalizar(grados) + 22.5f) / 45f).toInt() % 8

    /** "NE" */
    fun cardinal(grados: Float): String = CARDINALES[indice(grados)]

    /** "noreste" (para TalkBack). */
    fun nombreCardinal(grados: Float): String = NOMBRES[indice(grados)]
}

/** Acepta coma o punto. `null` si no es un número finito dentro de ±[limite]. */
internal fun parsearCoordenada(texto: String, limite: Double): Double? {
    val v = texto.trim().replace(',', '.').toDoubleOrNull() ?: return null
    return if (v.isFinite() && abs(v) <= limite) v else null
}

private val PATRON_NOMBRE = Regex("""^video[_\s-]?(\d+)$""", RegexOption.IGNORE_CASE)

/**
 * "video_N+1", donde N es el mayor número entre los videos llamados "video3", "video_3"…
 * Si ninguno sigue ese patrón (p. ej. se renombraron todos) usa la cantidad de videos.
 * Salta los nombres ya usados.
 */
internal fun siguienteNombre(videos: List<Video>): String {
    val usados = videos.map { it.nombre.trim().lowercase() }.toSet()
    val mayor = videos
        .mapNotNull { PATRON_NOMBRE.matchEntire(it.nombre.trim())?.groupValues?.get(1)?.toIntOrNull() }
        .maxOrNull()
    var n = (mayor ?: videos.size) + 1
    while ("$PREFIJO_VIDEO$n".lowercase() in usados) n++
    return "$PREFIJO_VIDEO$n"
}

/**
 * Última foto del video más reciente que tenga fotos. "Reciente" = mayor `creadoEn` (ISO-8601 ordena
 * como texto); en empate o sin fecha, el último de la lista. Lo mismo para elegir la última foto.
 */
internal fun calcularUltimaPosicion(videos: List<Video>): UltimaPosicion? {
    val video = videos
        .withIndex()
        .filter { it.value.fotos.isNotEmpty() }
        .maxWithOrNull(compareBy<IndexedValue<Video>>({ it.value.creadoEn.orEmpty() }, { it.index }))
        ?.value ?: return null
    val foto: Foto = video.fotos
        .withIndex()
        .maxWithOrNull(compareBy<IndexedValue<Foto>>({ it.value.capturadaEn.orEmpty() }, { it.index }))
        ?.value ?: return null
    return UltimaPosicion(
        punto = PuntoMapa(foto.lat, foto.lng),
        rumbo = foto.rumbo?.let(Rumbo::normalizar),
        videoNombre = video.nombre,
    )
}