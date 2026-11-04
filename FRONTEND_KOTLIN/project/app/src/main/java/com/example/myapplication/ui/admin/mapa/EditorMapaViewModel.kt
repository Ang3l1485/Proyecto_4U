package com.example.myapplication.ui.admin.mapa

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.Alertas
import com.example.myapplication.data.remote.RemoteLugaresRepository
import com.example.myapplication.data.repository.AlertasRepository
import com.example.myapplication.data.repository.CambiosLugares
import com.example.myapplication.data.repository.LugaresRepository
import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.LugarDestino
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

const val MAX_MENSAJE = 200

data class EditorMapaUi(
    val alertas: List<Alerta> = emptyList(),
    // FE-3.4: el modelo único de lugar (antes `Lugar(nombre, lat, lng)`); el mapa web solo usa nombre, lat y lng.
    val lugares: List<LugarDestino> = emptyList(),
    val pendientes: Set<String> = emptySet(),   // ids con cambios sin sincronizar (una operación por id)
    val formulario: Alerta? = null,             // alerta en edición (borrador); null = sin formulario
    val formularioEsNuevo: Boolean = false,
    val errores: ErroresAlerta = ErroresAlerta.NINGUNO,
    val sincronizando: Boolean = false,
    /** FE-3.3: «Ajustar en el mapa» del formulario: la hoja se oculta y el borrador se arrastra en el mapa. */
    val ajustando: Boolean = false,
) {
    val alertasJson: String get() = alertasJson(alertas)

    val lugaresJson: String
        get() = JSONArray().also { arr ->
            lugares.forEach { arr.put(JSONObject().put("nombre", it.nombre).put("lat", it.lat).put("lng", it.lng)) }
        }.toString()

    /** Lo que el mapa dibuja en vivo mientras el formulario está abierto. */
    val borradorJson: String?
        get() = formulario?.jsonMapa()?.toString()
}

/**
 * Vista 7.8 (FE-3.3): local primero sobre [repo] (`AlertasRepository`, compartido con 7.4 y 7.10). Guardar, mover o
 * eliminar se aplica al instante en el teléfono y queda pendiente; «Guardar / Sincronizar» lo envía. Al abrirse lee el
 * disco y la lista del servidor (`GET /v1/admin/alerts`), y los lugares públicos (`GET /v1/places`, se recargan si
 * cambian los lugares, `CambiosLugares`). Los avisos (resultado de sincronizar, errores) van por [avisos] (un `Toast`).
 */
class EditorMapaViewModel(
    private val repo: AlertasRepository,
    private val lugaresRepo: LugaresRepository,
    cambiosLugares: StateFlow<Int>? = null,
) : ViewModel() {
    private val _ui = MutableStateFlow(EditorMapaUi())
    val ui: StateFlow<EditorMapaUi> = _ui.asStateFlow()

    private val _avisos = Channel<String>(Channel.BUFFERED)
    val avisos: Flow<String> = _avisos.receiveAsFlow()

    init {
        viewModelScope.launch {
            repo.estado.collect { e -> _ui.update { it.copy(alertas = e.visibles, pendientes = e.idsPendientes) } }
        }
        viewModelScope.launch { cargarAlertas() }
        viewModelScope.launch { cargarLugares() }
        cambiosLugares?.let { c -> viewModelScope.launch { c.drop(1).collect { cargarLugares() } } }
    }

    private suspend fun cargarAlertas() {
        try {
            repo.cargar()
            repo.refrescar()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            TextosAlertas.deCarga(e)?.let { _avisos.trySend(it) }
        }
    }

    private suspend fun cargarLugares() {
        try {
            val lista = lugaresRepo.obtenerLugares()
            _ui.update { it.copy(lugares = lista) }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // Sin lugares el editor funciona igual (son solo contexto); la línea `Api` queda en app.log.
        }
    }

    // ── Formulario (vista 7.9) ──
    fun abrirFormulario(id: String?, lat: Double, lng: Double) {
        _ui.update { s ->
            val existente = id?.let { i -> s.alertas.firstOrNull { it.id == i } }
            s.copy(
                formulario = existente ?: Alerta(
                    UUID.randomUUID().toString(), FormularioAlerta.redondear(lat), FormularioAlerta.redondear(lng), "",
                ),
                formularioEsNuevo = existente == null,
                errores = ErroresAlerta.NINGUNO,
                ajustando = false,
            )
        }
    }

    fun actualizarFormulario(a: Alerta) = _ui.update { it.copy(formulario = a, errores = ErroresAlerta.NINGUNO) }

    fun cancelarFormulario() = _ui.update { it.copy(formulario = null, errores = ErroresAlerta.NINGUNO, ajustando = false) }

    fun guardarFormulario() {
        val a = _ui.value.formulario ?: return
        val errores = FormularioAlerta.validar(a)
        if (errores.hay) {
            _ui.update { it.copy(errores = errores) }
            return
        }
        _ui.update { it.copy(formulario = null, errores = ErroresAlerta.NINGUNO, ajustando = false) }
        enRepo { repo.guardar(FormularioAlerta.limpia(a)) }
    }

    /** «Ajustar en el mapa»: oculta la hoja y el mapa deja arrastrar el borrador (`ajustarBorrador()` del JS). */
    fun ajustarEnMapa() {
        if (_ui.value.formulario != null) _ui.update { it.copy(ajustando = true) }
    }

    /** El JS terminó el ajuste (Listo o Cancelar, con la posición original): vuelve la hoja con esa posición. */
    fun ajusteTerminado(lat: Double, lng: Double) = _ui.update { s ->
        s.copy(
            formulario = s.formulario?.copy(lat = FormularioAlerta.redondear(lat), lng = FormularioAlerta.redondear(lng)),
            ajustando = false,
        )
    }

    // ── Acciones desde el mapa ──
    fun mover(id: String, lat: Double, lng: Double) =
        enRepo { repo.mover(id, FormularioAlerta.redondear(lat), FormularioAlerta.redondear(lng)) }

    fun eliminar(id: String) {
        _ui.update { s -> if (s.formulario?.id == id) s.copy(formulario = null, ajustando = false) else s }
        enRepo { repo.eliminar(id) }
    }

    fun sincronizar() {
        if (_ui.value.sincronizando) return
        _ui.update { it.copy(sincronizando = true) }
        viewModelScope.launch {
            try {
                _avisos.trySend(TextosAlertas.resultado(repo.sincronizar()))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                TextosAlertas.deExcepcion(e)?.let { _avisos.trySend(it) }
            } finally {
                _ui.update { it.copy(sincronizando = false) }
            }
        }
    }

    fun avisar(texto: String) {
        _avisos.trySend(texto)
    }

    private fun enRepo(accion: suspend () -> Unit) {
        viewModelScope.launch {
            try {
                accion()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                _avisos.trySend(TextosAlertas.NO_SE_GUARDO)
            }
        }
    }

    /** `appContext` = el de la aplicación (la pantalla pasa `LocalContext.current.applicationContext`). */
    class Factory(private val appContext: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            EditorMapaViewModel(Alertas.de(appContext), RemoteLugaresRepository(), CambiosLugares.version) as T
    }
}