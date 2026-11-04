package com.example.myapplication.ui.inicio

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Reemplaza la implementación por tu llamada real al backend (ej. GET /health). */
interface BackendHealth {
    suspend fun estaEnLinea(): Boolean
}

object BackendHealthStub : BackendHealth {
    override suspend fun estaEnLinea(): Boolean = true
}

data class InicioUiState(
    val escuchando: Boolean = false,
    val backendEnLinea: Boolean = false,
)

sealed interface InicioEvento {
    data object Ubicarme : InicioEvento
    data object IrALugar : InicioEvento
}

class InicioViewModel(app: Application) : AndroidViewModel(app) {

    private val backend: BackendHealth = BackendHealthStub

    companion object {
        const val BIENVENIDA =
            "Di uno para saber dónde estás, o dos para ir a un lugar."
        private const val NO_ENTENDI = "No te entendí. $BIENVENIDA"
        private const val MAX_INTENTOS = 3
    }

    private val voz = VoiceController(app)
    private var intentos = 0

    private val _estado = MutableStateFlow(InicioUiState())
    val estado: StateFlow<InicioUiState> = _estado.asStateFlow()

    private val _eventos = MutableSharedFlow<InicioEvento>(extraBufferCapacity = 1)
    val eventos: SharedFlow<InicioEvento> = _eventos.asSharedFlow()

    init {
        // Sondeo periódico del estado de conexión.
        viewModelScope.launch {
            while (true) {
                val ok = runCatching { backend.estaEnLinea() }.getOrDefault(false)
                _estado.value = _estado.value.copy(backendEnLinea = ok)
                delay(15_000)
            }
        }
    }

    /** Al abrir la pantalla: lee las instrucciones y empieza a escuchar. */
    fun alAbrir() {
        intentos = 0
        voz.speak(BIENVENIDA) { escuchar() }
    }

    /** Toque en el orbe: interrumpe la voz y activa/reactiva la escucha. */
    fun alPresionarOrbe() {
        intentos = 0
        navegar(InicioEvento.Ubicarme)   // ← antes: voz.stopAll(); escuchar()
    }

    /** Acciones directas (TalkBack / sin voz). */
    fun ubicarme() = navegar(InicioEvento.Ubicarme)
    fun irALugar() = navegar(InicioEvento.IrALugar)

    fun alPausar() {
        voz.stopAll()
        _estado.value = _estado.value.copy(escuchando = false)
    }

    /** Se llama tras explicar los permisos y que la persona los acepte o rechace. */
    fun explicarPermisos(alTerminar: () -> Unit) {
        voz.speak(
            "Necesito el micrófono para escucharte, la cámara para reconocer " +
                "lo que hay a tu alrededor y los sensores de actividad para saber cómo te mueves.",
            alTerminar,
        )
    }

    private fun escuchar() {
        _estado.value = _estado.value.copy(escuchando = true)
        voz.listen(
            onResult = { texto ->
                _estado.value = _estado.value.copy(escuchando = false)
                when (ComandoParser.parse(texto)) {
                    Comando.UBICARME -> navegar(InicioEvento.Ubicarme)
                    Comando.IR_A_LUGAR -> navegar(InicioEvento.IrALugar)
                    Comando.NINGUNO -> repetirOpciones()
                }
            },
            onFail = {
                _estado.value = _estado.value.copy(escuchando = false)
                repetirOpciones()
            },
        )
    }

    private fun repetirOpciones() {
        if (++intentos >= MAX_INTENTOS) {
            voz.speak("Presiona el botón central cuando quieras hablar.")
            return
        }
        voz.speak(NO_ENTENDI) { escuchar() }
    }

    private fun navegar(evento: InicioEvento) {
        voz.stopAll()
        _estado.value = _estado.value.copy(escuchando = false)
        _eventos.tryEmit(evento)
    }

    override fun onCleared() {
        voz.release()
    }
}