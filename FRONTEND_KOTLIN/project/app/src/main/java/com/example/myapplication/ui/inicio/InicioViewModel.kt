package com.example.myapplication.ui.inicio

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.data.remote.RemoteBackendHealth
import com.example.myapplication.data.repository.BackendHealth
import com.example.myapplication.logs.AppLog
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class InicioUiState(
    val escuchando: Boolean = false,
    val backendEnLinea: Boolean = false,
)

sealed interface InicioEvento {
    data object Ubicarme : InicioEvento
    data object IrALugar : InicioEvento

    /** FE-3.1: abrir el mapa público (ruta `mapa`), por la voz «mapa» o la acción de TalkBack «Ver mapa». */
    data object VerMapa : InicioEvento
}

class InicioViewModel(app: Application) : AndroidViewModel(app) {

    /** `GET /v1/health` real (FE-1.1); cada intento queda en `AppLog` con su `X-Request-Id` (tag `Api`). */
    private val backend: BackendHealth = RemoteBackendHealth(ClienteApi.api)

    companion object {
        // FE-3.1: añade «mapa» (el comando nuevo debe poder descubrirse sin ver la pantalla).
        const val BIENVENIDA =
            "Di uno para saber dónde estás, dos para ir a un lugar, o mapa para ver el mapa."
        private const val NO_ENTENDI = "No te entendí. $BIENVENIDA"

        /** Tras [MAX_INTENTOS] fallos deja de escuchar; tocar el orbe vuelve a escuchar (0.19.0). */
        const val TRAS_FALLOS = "Toca el botón grande del centro cuando quieras hablar."
        private const val MAX_INTENTOS = 3
        private const val TAG = "InicioVM"
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

    /**
     * Toque en el orbe: interrumpe la voz y activa (o reinicia) la escucha. **No navega** (decisión del usuario del
     * 2026-10-28: Ubicarme solo por voz, «uno»/«ubicarme»); si no entiende, repite las opciones como al abrir.
     */
    fun alPresionarOrbe() {
        intentos = 0
        AppLog.i(TAG, "Orbe tocado: escucho")
        voz.stopAll()
        escuchar()
    }

    /** Acción de TalkBack «Ir a un lugar» del orbe (por voz: «dos»). Ubicarme no tiene acción directa (0.19.0). */
    fun irALugar() = navegar(InicioEvento.IrALugar)

    /** FE-3.1: acción de TalkBack «Ver mapa» (por voz: «mapa», [ComandoParser]). */
    fun verMapa() = navegar(InicioEvento.VerMapa)

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
                val comando = ComandoParser.parse(texto)
                AppLog.i(TAG, "Comando de voz: $comando")
                when (comando) {
                    Comando.UBICARME -> navegar(InicioEvento.Ubicarme)
                    Comando.IR_A_LUGAR -> navegar(InicioEvento.IrALugar)
                    Comando.VER_MAPA -> navegar(InicioEvento.VerMapa)
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
        AppLog.i(TAG, "No entendí (fallo ${intentos + 1} de $MAX_INTENTOS)")
        if (++intentos >= MAX_INTENTOS) {
            voz.speak(TRAS_FALLOS)
            return
        }
        voz.speak(NO_ENTENDI) { escuchar() }
    }

    private fun navegar(evento: InicioEvento) {
        AppLog.i(TAG, "Navega: $evento")
        voz.stopAll()
        _estado.value = _estado.value.copy(escuchando = false)
        _eventos.tryEmit(evento)
    }

    override fun onCleared() {
        voz.release()
    }
}