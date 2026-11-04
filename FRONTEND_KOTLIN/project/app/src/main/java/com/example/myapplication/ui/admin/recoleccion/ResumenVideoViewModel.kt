package com.example.myapplication.ui.admin.recoleccion

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.ColaSubida
import com.example.myapplication.data.local.EstadoCola
import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.data.local.ManifestException
import com.example.myapplication.data.local.RecorridoLocal
import com.example.myapplication.data.local.SubidaRecorrido
import com.example.myapplication.data.local.Subidas
import com.example.myapplication.data.local.definitivo
import com.example.myapplication.domain.model.SesionDeRecoleccion
import com.example.myapplication.session.EventosSesion
import com.example.myapplication.session.MotivoSinSesion
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
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * Vista 7.5 — Resumen de video (FE-2.1, ARCHITECTURE §5.5 y §7.5). Lee el recorrido de `files/recoleccion/` con
 * [AlmacenRecorridos] (nombre, estadísticas, trayectoria y fotos), edita el nombre y descarta fotos mientras el backend
 * no conoce el video, y entrega la subida a la [ColaSubida] del proceso. El progreso por foto sale del manifest
 * (`sync`) y, con la subida completa, de `GET /v1/admin/videos/{id}` cada [SONDEO_MS] mientras la vista está en primer
 * plano (`estado` procesada/error).
 *
 * @param videoIdPedido `rec_NNNN` de la ruta; `null` = el de `SesionDeRecoleccion.resumen` o, si no hay (proceso
 *   muerto), el `finalizado` sin subir más reciente.
 */
class ResumenVideoViewModel(
    private val videoIdPedido: String?,
    private val almacen: AlmacenRecorridos,
    private val cola: ColaSubida,
    private val estadosRemotos: suspend (videoId: String) -> SubidaRecorrido.EstadoRemoto?,
) : ViewModel() {

    private val _ui = MutableStateFlow(ResumenVideoUiState())
    val ui: StateFlow<ResumenVideoUiState> = _ui.asStateFlow()

    private val _eventos = Channel<ResumenVideoEvento>(Channel.BUFFERED)
    val eventos: Flow<ResumenVideoEvento> = _eventos.receiveAsFlow()

    private var videoId: String? = null
    private var sondeo: Job? = null

    init {
        viewModelScope.launch { abrir() }
    }

    private suspend fun abrir() {
        val id = videoIdPedido ?: SesionDeRecoleccion.resumen.value?.videoId ?: masRecienteSinSubir()
        if (id == null) {
            _ui.update { it.copy(cargando = false, noEncontrado = true) }
            return
        }
        videoId = id
        recargar()
        // Lo que quedó `subiendo` (p. ej. tras volver a entrar) sigue solo; con sesión, sin pulsar nada.
        cola.reanudar()
        viewModelScope.launch { cola.cambios.collect { recargar() } }
        viewModelScope.launch { cola.estado.collect { e -> _ui.update { it.copy(subida = subidaDe(e, id)) } } }
    }

    private suspend fun masRecienteSinSubir(): String? = runCatching {
        almacen.listar().filter { it.finalizado && it.subida != EstadoSubida.COMPLETADA }.maxByOrNull { it.id }?.id
    }.getOrNull()

    private fun subidaDe(e: EstadoCola, id: String): SubidaUi = when {
        e.videoId == id -> SubidaUi(e.fase, e.hechas, e.total, e.mensaje, e.reintentoEnS)
        // Sin sesión la cola no dice de qué video: si este estaba subiendo, es el que espera.
        e.fase == FaseCola.ESPERANDO_SESION && _ui.value.estadoSubida == EstadoSubida.SUBIENDO ->
            SubidaUi(e.fase, mensaje = e.mensaje)
        else -> SubidaUi()
    }

    private suspend fun recargar() {
        val id = videoId ?: return
        val r = try {
            almacen.leer(id)
        } catch (e: CancellationException) {
            throw e
        } catch (e: ManifestException) {
            _ui.update { it.copy(cargando = false, noEncontrado = true) }
            return
        }
        _ui.update { actual ->
            val nombreSinCambios = actual.nombre == actual.nombreGuardado
            actual.copy(
                cargando = false,
                noEncontrado = false,
                videoId = id,
                nombre = if (nombreSinCambios || !r.editable) r.nombre else actual.nombre,
                nombreGuardado = r.nombre,
                estadoSubida = r.subida,
                enviadoAlBackend = r.remoteVideoId != null,
                duracionSegundos = r.duracionSegundos ?: 0,
                distanciaMetros = r.distanciaMetros ?: 0.0,
                pasos = r.pasos ?: 0,
                fotos = r.fotos.map { f ->
                    FotoResumen(f.id, almacen.archivoFoto(id, f).absolutePath, f.estado, f.error)
                },
                fotosJson = fotosJson(r),
                trayectoriaJson = trayectoriaJson(r),
                fotoAbierta = actual.fotoAbierta?.takeIf { abierta -> r.fotos.any { it.id == abierta } },
            )
        }
    }

    // ---- acciones ---------------------------------------------------------------------------------------------

    fun alCambiarNombre(texto: String) {
        _ui.update { it.copy(nombre = texto.take(AlmacenRecorridos.MAX_NOMBRE)) }
    }

    fun alSubir() {
        val id = videoId ?: return
        viewModelScope.launch {
            if (!guardarNombre()) return@launch
            cola.subir(id)
        }
    }

    /** «Guardar y subir después»: guarda el nombre y vuelve al Panel. La subida se hace luego desde el Panel. */
    fun alGuardarParaDespues() {
        viewModelScope.launch {
            if (!guardarNombre()) return@launch
            salir()
        }
    }

    /** Atrás: como «Guardar y subir después» si se puede editar; si no, solo sale (la subida sigue en segundo plano). */
    fun alVolver() {
        if (_ui.value.editable) alGuardarParaDespues() else viewModelScope.launch { salir() }
    }

    fun alAbrirFoto(fotoId: String) = _ui.update { it.copy(fotoAbierta = fotoId) }

    fun alCerrarFoto() = _ui.update { it.copy(fotoAbierta = null) }

    fun alDescartarFoto(fotoId: String) {
        val id = videoId ?: return
        viewModelScope.launch {
            try {
                almacen.descartarFoto(id, fotoId)
                _ui.update { it.copy(fotoAbierta = null, aviso = "Foto $fotoId descartada.") }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _ui.update { it.copy(aviso = e.message ?: "No se pudo descartar la foto.") }
            }
            recargar()
        }
    }

    fun alPedirDescartar() = _ui.update { it.copy(confirmandoDescartar = true) }

    fun alCancelarDescartar() = _ui.update { it.copy(confirmandoDescartar = false) }

    /** Borra el recorrido y todas sus fotos del teléfono (solo si el backend no lo conoce: [ResumenVideoUiState.editable]). */
    fun alConfirmarDescartar() {
        val id = videoId ?: return
        if (!_ui.value.editable) {
            _ui.update { it.copy(confirmandoDescartar = false) }
            return
        }
        viewModelScope.launch {
            almacen.descartar(id)
            _ui.update { it.copy(confirmandoDescartar = false) }
            salir()
        }
    }

    fun alDescartarAviso() = _ui.update { it.copy(aviso = null) }

    /**
     * «Iniciar sesión» (con la cola en `ESPERANDO_SESION`): avisa a `AppNav` como lo haría una petición sin sesión
     * (`EventosSesion`, ARCHITECTURE §5.3), que va a Login; tras entrar, el Panel retoma la cola.
     */
    fun alIniciarSesion() = EventosSesion.emitir(MotivoSinSesion.SinSesionLocal)

    /** `ON_RESUME`: retoma la cola y, con la subida completa, consulta el progreso del backend cada [SONDEO_MS]. */
    fun alReanudar() {
        if (videoId != null) cola.reanudar()
        if (sondeo?.isActive == true) return
        sondeo = viewModelScope.launch {
            while (isActive) {
                val id = videoId
                val estado = _ui.value
                if (id != null && estado.estadoSubida == EstadoSubida.COMPLETADA && !estado.terminado) {
                    val remoto = estadosRemotos(id)
                    if (remoto != null) _ui.update { it.copy(estadoRemoto = remoto.estado) }
                    recargar()
                    if (remoto != null && remoto.conteo.definitivo()) break
                }
                delay(SONDEO_MS)
            }
        }
    }

    /** `ON_PAUSE`: deja de consultar el backend (la cola sigue). */
    fun alPausar() {
        sondeo?.cancel()
        sondeo = null
    }

    // ---- ayudas -----------------------------------------------------------------------------------------------

    /** Guarda el nombre si cambió y se puede editar. `false` (con aviso) si quedó vacío. */
    private suspend fun guardarNombre(): Boolean {
        val id = videoId ?: return false
        val estado = _ui.value
        if (!estado.editable || estado.nombre.trim() == estado.nombreGuardado) return true
        return try {
            almacen.renombrar(id, estado.nombre)
            recargar()
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: IllegalArgumentException) {
            _ui.update { it.copy(aviso = e.message ?: "El nombre no puede quedar vacío.") }
            false
        } catch (e: Exception) {
            _ui.update { it.copy(aviso = e.message ?: "No se pudo guardar el nombre.") }
            false
        }
    }

    private suspend fun salir() {
        SesionDeRecoleccion.limpiar()
        _eventos.send(ResumenVideoEvento.IrAlPanel)
    }

    private fun fotosJson(r: RecorridoLocal): String = JSONArray().apply {
        r.fotos.forEach { f ->
            put(JSONObject().put("id", f.id).put("lat", f.lat).put("lng", f.lng).put("rumbo", f.rumbo ?: JSONObject.NULL))
        }
    }.toString()

    private fun trayectoriaJson(r: RecorridoLocal): String {
        val puntos = r.trayectoria.map { it.lat to it.lng }.ifEmpty { r.fotos.map { it.lat to it.lng } }
        return JSONArray().apply { puntos.forEach { (lat, lng) -> put(JSONArray().put(lat).put(lng)) } }.toString()
    }

    /** Espera el contexto de la aplicación (como las de Galería y Videos). */
    class Factory(private val videoId: String?) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            ResumenVideoViewModel(videoId, Subidas.almacen, Subidas.cola, Subidas.subida::actualizarEstados) as T
    }

    companion object {
        /** Cada cuánto se consulta `GET /v1/admin/videos/{id}` con la subida completa y la vista visible. */
        const val SONDEO_MS = 15_000L
    }
}
