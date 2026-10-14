package com.example.myapplication.ui.admin.calibracion

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.repository.CalibracionPasoRepository
import com.example.myapplication.domain.usecase.CalibracionPaso
import com.example.myapplication.domain.usecase.ResultadoCalibracion
import com.example.myapplication.sensors.PdrEngine
import com.example.myapplication.sensors.PdrTracker
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Calibración de la longitud de paso (una sola pasada sobre un tramo A→B de distancia conocida).
 *
 * Usa su **propio** [PdrTracker] (no el de la recolección) y mide con la resta de contadores:
 * `pasos = PdrEstado.pasos(Fin) − PdrEstado.pasos(Inicio)`. La longitud calibrada que ya tuviera
 * el tracker no influye: solo se leen pasos, no distancia.
 *
 * Al tocar «Inicio» se fija la posición en A, porque `PdrEngine.onPaso` **no cuenta** pasos
 * mientras no haya posición inicial.
 */
class CalibracionViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = CalibracionPasoRepository(app)
    private val tracker = PdrTracker(app)

    private val _ui = MutableStateFlow(
        CalibracionUiState(
            longitudActualM = repo.longitudPasoM(),
            calibrada = repo.guardada() != null,
        )
    )
    val ui: StateFlow<CalibracionUiState> = _ui.asStateFlow()

    private var pasosInicio = 0
    private var inicioMs = 0L
    private var reloj: Job? = null

    init {
        // Solo reacciona cuando cambian los pasos o la fuente (el estado se publica ~20 Hz por el rumbo).
        viewModelScope.launch {
            tracker.estado
                .map { it.pasos to it.fuentePasos }
                .distinctUntilChanged()
                .collect { (pasos, fuente) ->
                    _ui.update { s ->
                        if (s.fase == FaseCalibracion.CAMINANDO) {
                            s.copy(pasos = (pasos - pasosInicio).coerceAtLeast(0), fuentePasos = fuente)
                        } else {
                            s.copy(fuentePasos = fuente)
                        }
                    }
                }
        }
    }

    // ── Puntos del tramo ──────────────────────────

    /** Toque en el mapa: el primero marca A, el segundo B; con ambos puestos se ignora (se arrastran). */
    fun alTocarMapa(lat: Double, lng: Double) = _ui.update { s ->
        if (s.mapaBloqueado) return@update s
        val p = PuntoTramo(lat, lng)
        when {
            s.puntoA == null -> s.conPuntos(p, s.puntoB)
            s.puntoB == null -> s.conPuntos(s.puntoA, p)
            else -> s
        }
    }

    fun alMoverPunto(extremo: ExtremoTramo, lat: Double, lng: Double) = _ui.update { s ->
        if (s.mapaBloqueado) return@update s
        val p = PuntoTramo(lat, lng)
        if (extremo == ExtremoTramo.A) s.conPuntos(p, s.puntoB) else s.conPuntos(s.puntoA, p)
    }

    fun alLimpiarPuntos() = _ui.update { s ->
        if (s.mapaBloqueado) s else s.conPuntos(null, null)
    }

    // ── Medición ──────────────────────────────────

    fun alIniciar() {
        val s = _ui.value
        val a = s.puntoA ?: return
        if (!s.puedeIniciar) return

        tracker.fijarPosicion(a.lat, a.lng) // sin posición, el motor no cuenta pasos
        tracker.iniciar()
        pasosInicio = tracker.estado.value.pasos
        inicioMs = SystemClock.elapsedRealtime()

        _ui.update {
            it.copy(
                fase = FaseCalibracion.CAMINANDO,
                pasos = 0,
                segundos = 0,
                resultado = null,
                aviso = null,
            )
        }
        reloj?.cancel()
        reloj = viewModelScope.launch {
            while (true) {
                delay(500)
                val seg = ((SystemClock.elapsedRealtime() - inicioMs) / 1000).toInt()
                _ui.update { if (it.fase == FaseCalibracion.CAMINANDO) it.copy(segundos = seg) else it }
            }
        }
    }

    fun alFinalizar() {
        val s = _ui.value
        if (s.fase != FaseCalibracion.CAMINANDO) return

        // Se lee el contador ANTES de detener el tracker.
        val pasos = (tracker.estado.value.pasos - pasosInicio).coerceAtLeast(0)
        val duracionS = (SystemClock.elapsedRealtime() - inicioMs) / 1000.0
        reloj?.cancel()
        tracker.detener()

        _ui.update {
            it.copy(
                fase = FaseCalibracion.RESULTADO,
                pasos = pasos,
                segundos = duracionS.toInt(),
                resultado = CalibracionPaso.calcular(s.distanciaM ?: 0.0, pasos, duracionS),
            )
        }
    }

    /** Cancela la medición en curso y vuelve a «Inicio» con los mismos A y B. */
    fun alCancelarMedicion() {
        if (_ui.value.fase != FaseCalibracion.CAMINANDO) return
        reloj?.cancel()
        tracker.detener()
        _ui.update { it.copy(fase = FaseCalibracion.LISTO, pasos = 0, segundos = 0) }
    }

    /** Descarta el resultado y vuelve a «Inicio» con los mismos A y B. */
    fun alRepetir() = _ui.update { s ->
        if (s.fase != FaseCalibracion.RESULTADO) s
        else s.copy(fase = FaseCalibracion.LISTO, pasos = 0, segundos = 0, resultado = null)
    }

    fun alGuardar() {
        val s = _ui.value
        val medicion = s.resultado as? ResultadoCalibracion.Valido ?: return
        if (s.fase != FaseCalibracion.RESULTADO) return
        repo.guardar(medicion)
        _ui.update {
            it.copy(
                fase = FaseCalibracion.GUARDADA,
                longitudActualM = medicion.longitudPasoM,
                calibrada = true,
            )
        }
    }

    /** Vuelve a la longitud genérica. No toca una medición en curso. */
    fun alRestablecer() {
        if (_ui.value.fase == FaseCalibracion.CAMINANDO) return
        repo.restablecer()
        _ui.update {
            it.copy(
                longitudActualM = PdrEngine.LONGITUD_PASO_DEFECTO_M,
                calibrada = false,
                aviso = AvisoCalibracion.VALOR_RESTABLECIDO,
            )
        }
    }

    // ── Ciclo de vida ─────────────────────────────

    /** ON_STOP: los sensores no siguen el ciclo de vida, así que se detienen aquí. Cancela la medición. */
    fun alIrASegundoPlano() {
        tracker.detener()
        reloj?.cancel()
        _ui.update { s ->
            if (s.fase == FaseCalibracion.CAMINANDO) {
                s.copy(
                    fase = FaseCalibracion.LISTO,
                    pasos = 0,
                    segundos = 0,
                    aviso = AvisoCalibracion.CANCELADA_SEGUNDO_PLANO,
                )
            } else s
        }
    }

    fun descartarAviso() = _ui.update { it.copy(aviso = null) }

    override fun onCleared() {
        tracker.liberar()
        super.onCleared()
    }

    // ── Auxiliares ────────────────────────────────

    private fun CalibracionUiState.conPuntos(a: PuntoTramo?, b: PuntoTramo?): CalibracionUiState {
        val distancia = if (a != null && b != null) {
            CalibracionPaso.distanciaEntre(a.lat, a.lng, b.lat, b.lng)
        } else null
        return copy(
            puntoA = a,
            puntoB = b,
            distanciaM = distancia,
            fase = if (distancia != null) FaseCalibracion.LISTO else FaseCalibracion.PUNTOS,
            resultado = null,
        )
    }
}