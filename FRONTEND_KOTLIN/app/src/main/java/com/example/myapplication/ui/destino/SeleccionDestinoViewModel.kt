package com.example.myapplication.ui.destino

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.LugaresRepository
import com.example.myapplication.data.repository.LugaresRepositoryStub
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.usecase.BuscarLugares
import com.example.myapplication.domain.usecase.InterpretarRespuesta
import com.example.myapplication.domain.usecase.Respuesta
import com.example.myapplication.logs.AppLog
import com.example.myapplication.ui.inicio.VoiceController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException

private const val TAG = "DestinoVM"

/**
 * Cerebro de la vista 6.4 (Selección de destino).
 *
 * Flujo por voz:
 *   pregunta "¿A dónde quieres ir?" -> escucha -> busca coincidencia aproximada ->
 *     · una coincidencia  -> "¿Quieres ir a X? Di sí o no." -> escucha la respuesta
 *     · varias            -> las lee y pide elegir
 *     · ninguna           -> avisa y vuelve a escuchar (máximo [MAX_INTENTOS] veces)
 * Todo lo que se puede decir también se puede tocar (lista, chips, botones Sí / No).
 *
 * Qué NO hace: no navega. Cuando la persona confirma, emite [DestinoEvento.Confirmado].
 */
class SeleccionDestinoViewModel(app: Application) : AndroidViewModel(app) {

    companion object {
        const val PREGUNTA = "¿A dónde quieres ir? Di el nombre del lugar."
        private const val MAX_INTENTOS = 3
    }

    // --- Dependencias -------------------------------------------------------
    private val repositorio: LugaresRepository = LugaresRepositoryStub()
    private val voz = VoiceController(app)

    // --- Salidas hacia la UI ------------------------------------------------
    private val _estado = MutableStateFlow(DestinoUiState())
    val estado: StateFlow<DestinoUiState> = _estado.asStateFlow()

    private val _eventos = MutableSharedFlow<DestinoEvento>(extraBufferCapacity = 1)
    val eventos: SharedFlow<DestinoEvento> = _eventos.asSharedFlow()

    // --- Estado interno -----------------------------------------------------
    private var todos: List<LugarDestino> = emptyList()
    private var conVoz = true
    private var iniciado = false

    /**
     * Se incrementa cada vez que la persona interrumpe (toca algo, pausa, sale).
     * Los callbacks de voz que llegan con un token viejo se ignoran, para que el flujo
     * hablado no continúe después de que la persona tomó el control.
     */
    private var token = 0
    private var intentosDestino = 0
    private var intentosConfirmacion = 0

    // ========================================================================
    // Acciones que dispara la pantalla
    // ========================================================================

    /** Al abrir: carga los lugares y, si hay micrófono, hace la pregunta hablada. */
    fun alAbrir(microfonoDisponible: Boolean) {
        if (iniciado) return
        iniciado = true
        conVoz = microfonoDisponible
        _estado.update { it.copy(sinMicrofono = !microfonoDisponible) }
        cargarLugares()
    }

    fun reintentarCarga() {
        detenerVoz()
        cargarLugares()
    }

    /** Toque en el micrófono: detiene la escucha si estaba activa; si no, empieza a escuchar. */
    fun alPresionarMicrofono() {
        val estabaEscuchando = _estado.value.escuchando
        val candidato = _estado.value.candidato
        detenerVoz()
        if (estabaEscuchando) return
        if (!conVoz) {
            hablar("El micrófono no está disponible. Elige un lugar de la lista.")
            return
        }
        intentosDestino = 0
        if (candidato != null) escucharConfirmacion(candidato) else escucharDestino()
    }

    /** Toque en un lugar de la lista (o en una de las opciones): se pide confirmación. */
    fun alElegirLugar(lugar: LugarDestino) {
        detenerVoz()
        _estado.update { it.copy(textoReconocido = null) }
        proponer(lugar)
    }

    fun alResponderSi() {
        _estado.value.candidato?.let { confirmar(it) }
    }

    fun alResponderNo() {
        detenerVoz()
        rechazar()
    }

    /** La ✕ de la tarjeta "Texto reconocido": descarta lo entendido y cualquier confirmación pendiente. */
    fun descartarTexto() {
        detenerVoz()
        _estado.update { it.copy(textoReconocido = null, candidato = null, opciones = emptyList()) }
    }

    fun alCambiarBusqueda(texto: String) {
        detenerVoz()
        _estado.update { it.copy(busqueda = texto) }
        refiltrar()
    }

    /** Toca el chip: lo activa; si ya estaba activo, lo quita. */
    fun alElegirCategoria(categoria: CategoriaLugar?) {
        _estado.update { it.copy(categoria = categoria) }
        refiltrar()
    }

    fun alCambiarOrden() {
        _estado.update {
            it.copy(
                orden = if (it.orden == OrdenLugares.CERCANIA) OrdenLugares.NOMBRE else OrdenLugares.CERCANIA
            )
        }
        refiltrar()
    }

    fun limpiarFiltros() {
        _estado.update { it.copy(busqueda = "", categoria = null) }
        refiltrar()
    }

    /** La pantalla deja de verse (ON_STOP) o se sale de ella: calla y deja de escuchar. */
    fun alPausar() = detenerVoz()

    fun alSalir() = detenerVoz()

    // ========================================================================
    // Carga y filtrado de la lista
    // ========================================================================

    private fun cargarLugares() {
        _estado.update { it.copy(cargando = true, error = null) }
        viewModelScope.launch {
            try {
                todos = repositorio.obtenerLugares()
                _estado.update { it.copy(cargando = false) }
                refiltrar()
                AppLog.i(TAG, "Lugares cargados: ${todos.size}")
                if (conVoz) preguntarDestino()
            } catch (e: CancellationException) {
                throw e
            } catch (e: IOException) {
                fallarCarga(ErrorDestino.SIN_CONEXION, e)
            } catch (e: Exception) {
                fallarCarga(ErrorDestino.DESCONOCIDO, e)
            }
        }
    }

    private fun fallarCarga(error: ErrorDestino, e: Exception) {
        AppLog.e(TAG, "No se pudieron cargar los lugares", e)
        _estado.update { it.copy(cargando = false, error = error) }
        if (conVoz) hablar("No pude cargar la lista de lugares. Revisa tu conexión y toca reintentar.")
    }

    /** Aplica búsqueda, categoría y orden sobre la lista completa. */
    private fun refiltrar() {
        _estado.update { s ->
            val filtrados = BuscarLugares.filtrar(todos, s.busqueda)
                .filter { s.categoria == null || it.categoria == s.categoria }
            val ordenados = when (s.orden) {
                OrdenLugares.CERCANIA -> filtrados.sortedBy { it.distanciaMetros ?: Int.MAX_VALUE }
                OrdenLugares.NOMBRE -> filtrados.sortedBy { it.nombre }
            }
            s.copy(lugares = ordenados)
        }
    }

    // ========================================================================
    // Flujo hablado
    // ========================================================================

    private fun preguntarDestino() {
        hablar(PREGUNTA) { escucharDestino() }
    }

    private fun escucharDestino() {
        escuchar(
            alResultado = { texto -> procesarDestino(texto) },
            alFallar = { reintentarDestino("No te escuché.") },
        )
    }

    private fun procesarDestino(texto: String) {
        val encontrados = BuscarLugares.mejores(texto, todos)
        AppLog.i(TAG, "Voz: ${encontrados.size} coincidencia(s)")
        _estado.update { it.copy(textoReconocido = texto, candidato = null, opciones = emptyList()) }
        when (encontrados.size) {
            0 -> reintentarDestino("No encontré ese lugar.")
            1 -> proponer(encontrados.first())
            else -> ofrecerOpciones(encontrados)
        }
    }

    private fun reintentarDestino(motivo: String) {
        intentosDestino++
        if (intentosDestino >= MAX_INTENTOS) {
            hablar("$motivo Toca el micrófono para intentarlo otra vez, o elige un lugar de la lista.")
        } else {
            hablar("$motivo Intenta de nuevo.") { escucharDestino() }
        }
    }

    private fun ofrecerOpciones(lista: List<LugarDestino>) {
        _estado.update { it.copy(opciones = lista) }
        val nombres = lista.dropLast(1).joinToString(", ") { it.nombre } + " o " + lista.last().nombre
        hablar("Encontré ${lista.size} lugares: $nombres. Di cuál quieres.") { escucharDestino() }
    }

    /** Muestra la tarjeta de confirmación y pregunta; si hay micrófono, escucha el sí o el no. */
    private fun proponer(lugar: LugarDestino) {
        intentosConfirmacion = 0
        _estado.update { it.copy(candidato = lugar, opciones = emptyList()) }
        AppLog.i(TAG, "Destino propuesto: ${lugar.id}")
        hablar("¿Quieres ir a ${lugar.nombre}? Di sí o no.") {
            if (conVoz) escucharConfirmacion(lugar)
        }
    }

    private fun escucharConfirmacion(lugar: LugarDestino) {
        escuchar(
            alResultado = { texto ->
                when (InterpretarRespuesta.interpretar(texto)) {
                    Respuesta.SI -> confirmar(lugar)
                    Respuesta.NO -> rechazar()
                    Respuesta.NINGUNA -> repetirConfirmacion(lugar)
                }
            },
            alFallar = { repetirConfirmacion(lugar) },
        )
    }

    private fun repetirConfirmacion(lugar: LugarDestino) {
        intentosConfirmacion++
        if (intentosConfirmacion >= MAX_INTENTOS) {
            hablar("Usa los botones Sí o No cuando quieras.")
        } else {
            hablar("No te entendí. ¿Quieres ir a ${lugar.nombre}? Di sí o no.") {
                escucharConfirmacion(lugar)
            }
        }
    }

    private fun rechazar() {
        intentosDestino = 0
        _estado.update { it.copy(textoReconocido = null, candidato = null, opciones = emptyList()) }
        hablar("De acuerdo. ¿A qué lugar quieres ir?") {
            if (conVoz) escucharDestino()
        }
    }

    private fun confirmar(lugar: LugarDestino) {
        detenerVoz()
        AppLog.i(TAG, "Destino confirmado: ${lugar.id}")
        _eventos.tryEmit(DestinoEvento.Confirmado(lugar))
    }

    // ========================================================================
    // Utilidades de voz
    // ========================================================================

    /** Habla [texto] y, al terminar, ejecuta [alTerminar] (si nadie interrumpió mientras tanto). */
    private fun hablar(texto: String, alTerminar: () -> Unit = {}) {
        val t = token
        voz.speak(texto) { if (t == token) alTerminar() }
    }

    /** Escucha una vez; el resultado se ignora si la persona interrumpió mientras tanto. */
    private fun escuchar(alResultado: (String) -> Unit, alFallar: () -> Unit) {
        val t = token
        _estado.update { it.copy(escuchando = true) }
        voz.listen(
            onResult = { texto ->
                if (t == token) {
                    _estado.update { it.copy(escuchando = false) }
                    alResultado(texto)
                }
            },
            onFail = {
                if (t == token) {
                    _estado.update { it.copy(escuchando = false) }
                    alFallar()
                }
            },
        )
    }

    /** Calla, deja de escuchar e invalida los callbacks pendientes. */
    private fun detenerVoz() {
        token++
        voz.stopAll()
        _estado.update { it.copy(escuchando = false) }
    }

    override fun onCleared() {
        token++
        voz.release()
    }
}
