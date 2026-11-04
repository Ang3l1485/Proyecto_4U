package com.example.myapplication.ui.admin.panel

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.ColaSubida
import com.example.myapplication.data.local.EstadoCola
import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.FaseCola
import com.example.myapplication.data.local.RecorridoLocal
import com.example.myapplication.data.local.Subidas
import com.example.myapplication.data.local.fotosPendientesDe
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.MapeoErroresApi
import com.example.myapplication.data.remote.RemoteAdminRepository
import com.example.myapplication.data.repository.AdminRepository
import com.example.myapplication.data.repository.CambiosAlertas
import com.example.myapplication.data.repository.CambiosLugares
import com.example.myapplication.domain.model.ResumenAdmin
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.session.SessionManager
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PanelUiState(
    val nombre: String = "",
    val rolTexto: String = "",
    val resumen: ResumenAdmin? = null,
    val cargandoResumen: Boolean = true,
    val errorResumen: Boolean = false,
    /** FE-2.1: aviso de la cola de subida (subiendo, esperando, recorridos sin subir); `null` = nada pendiente. */
    val avisoSubidas: AvisoSubidas? = null,
)

/**
 * Tarjeta de subidas del Panel (FE-2.1). Tocarla abre la vista 7.5 de [videoId] (así se retoma una subida tras volver
 * a entrar, y se suben los recorridos de «Guardar y subir después»).
 */
data class AvisoSubidas(val videoId: String, val titulo: String, val detalle: String, val accion: String)

/** Arma [AvisoSubidas] a partir de la cola y de los recorridos locales (lógica pura). */
internal fun avisoSubidas(estado: EstadoCola, recorridos: List<RecorridoLocal>): AvisoSubidas? {
    val sinTerminar = recorridos.filter { it.finalizado && it.subida != EstadoSubida.COMPLETADA }
    val nombreDe = { id: String -> recorridos.firstOrNull { it.id == id }?.nombre ?: id }
    estado.videoId?.let { id ->
        val nombre = nombreDe(id)
        when (estado.fase) {
            FaseCola.PREPARANDO -> return AvisoSubidas(id, "Preparando «$nombre»", "${estado.hechas} de ${estado.total} fotos", "Ver")
            FaseCola.SUBIENDO, FaseCola.COMPLETANDO ->
                return AvisoSubidas(id, "Subiendo «$nombre»", "${estado.hechas} de ${estado.total} fotos", "Ver")
            FaseCola.SIN_CONEXION ->
                return AvisoSubidas(id, "Subida de «$nombre» en pausa", "Sin conexión: reintento en ${estado.reintentoEnS ?: 0} s", "Ver")
            FaseCola.ERROR, FaseCola.FOTOS_ILEGIBLES ->
                return AvisoSubidas(id, "La subida de «$nombre» se detuvo", estado.mensaje ?: "Revisa el recorrido", "Revisar")
            else -> Unit
        }
    }
    val aMedias = sinTerminar.filter { it.subida == EstadoSubida.SUBIENDO }.maxByOrNull { it.id }
    if (aMedias != null) {
        return AvisoSubidas(aMedias.id, "Subida pendiente de «${aMedias.nombre}»", "${aMedias.fotosPendientes} fotos por subir", "Ver")
    }
    val ultimo = sinTerminar.maxByOrNull { it.id } ?: return null
    val detalle = if (sinTerminar.size == 1) "«${ultimo.nombre}», ${ultimo.fotos.size} fotos"
    else "${sinTerminar.size} recorridos; el más reciente, «${ultimo.nombre}»"
    return AvisoSubidas(ultimo.id, "Recorridos sin subir", detalle, "Revisar y subir")
}

/**
 * FE-2.2: el resumen con «Fotos pendientes» recalculado desde los recorridos locales (lógica pura; regla de
 * [fotosPendientesDe]). Sin resumen (cargando o con error) o sin poder leer los recorridos (`null`), lo deja como
 * está; los datos del backend nunca se tocan.
 */
internal fun resumenConPendientes(resumen: ResumenAdmin?, recorridos: List<RecorridoLocal>?): ResumenAdmin? =
    if (resumen == null || recorridos == null) resumen else resumen.copy(fotosPendientes = fotosPendientesDe(recorridos))

/**
 * FE-2.2: ¿el Panel muestra «No se pudo cargar el resumen» por este fallo? No para una sesión perdida
 * (`FalloApi.SesionVencida`, también sin sesión local): `AppNav` ya vuelve a Login (ARCHITECTURE §5.3, paso 4).
 */
internal fun errorVisibleDelResumen(e: Throwable): Boolean = MapeoErroresApi.deExcepcion(e) !is FalloApi.SesionVencida

/**
 * FE-3.4, `ON_RESUME`: ¿hay que volver a pedir el «Resumen rápido» al backend? Sí si los lugares cambiaron desde la
 * última carga ([cargada] ≠ [actual] de `CambiosLugares`: se creó, editó o borró un lugar en 7.6, 7.7 o 7.4) y no hay
 * una carga en curso. Sin contador ([actual] `null`, previews y pruebas), nunca. Lógica pura (`RecargaResumenTest`).
 */
internal fun debeRecargarResumen(cargada: Int?, actual: Int?, cargando: Boolean): Boolean =
    !cargando && actual != null && cargada != actual

sealed interface PanelEvento {
    /** El admin cerró sesión: volver al flujo público. */
    data object SesionCerrada : PanelEvento
    /** No hay sesión ADMIN válida: redirigir a Login. */
    data object SinSesion : PanelEvento
}

class PanelAdminViewModel(
    private val repo: AdminRepository,
    private val session: SessionManager,
    // FE-2.1: cola de subida del proceso (`Subidas`); `null` en previews o pruebas sin subida.
    private val almacen: AlmacenRecorridos? = null,
    private val cola: ColaSubida? = null,
    // FE-3.4: cambios de lugares del proceso (`CambiosLugares.version`); `null` en previews o pruebas.
    private val cambiosLugares: StateFlow<Int>? = null,
    // FE-3.3: cambios de alertas confirmados por el backend (`CambiosAlertas.version`): «Alertas activas» al día.
    private val cambiosAlertas: StateFlow<Int>? = null,
) : ViewModel() {

    /** Versión de `CambiosLugares` cuando empezó la última carga del resumen (FE-3.4). */
    private var versionLugaresCargada: Int? = null

    /** Versión de `CambiosAlertas` cuando empezó la última carga del resumen (FE-3.3). */
    private var versionAlertasCargada: Int? = null

    private val _state = MutableStateFlow(PanelUiState())
    val state: StateFlow<PanelUiState> = _state.asStateFlow()

    private val _eventos = Channel<PanelEvento>(Channel.BUFFERED)
    val eventos = _eventos.receiveAsFlow()

    /** Pasó la guarda de rol de `init` (sin ella, [alReanudar] no hace nada). */
    private var conSesionAdmin = false

    init {
        val sesion = session.obtener()
        if (sesion == null || sesion.usuario.rol != Rol.ADMIN) {
            // Guarda de rol: sin sesión ADMIN no se muestra el panel.
            _eventos.trySend(PanelEvento.SinSesion)
        } else {
            conSesionAdmin = true
            _state.update {
                it.copy(
                    nombre = sesion.usuario.nombre.trim().substringBefore(' '),
                    rolTexto = "Administrador del sistema",
                )
            }
            cargarResumen()
            vigilarSubidas()
        }
    }

    /**
     * FE-2.1: con sesión ADMIN, retoma la cola (lo que quedó `subiendo`; ARCHITECTURE §5.8: tras volver a Login se cae
     * aquí) y mantiene [PanelUiState.avisoSubidas] al día. FE-2.2: también «Fotos pendientes» del resumen.
     */
    private fun vigilarSubidas() {
        val c = cola ?: return
        val a = almacen ?: return
        c.reanudar()
        viewModelScope.launch {
            combine(c.estado, c.cambiosVideos) { estado, _ -> estado }.collect { estado ->
                refrescarLocal(a, estado)
                // La cola se paró por falta de sesión y el Panel (vivo en la pila) ya no la tiene (p. ej. venció a las
                // 12 h): a Login, como haría su guarda de `init`. Con sesión vigente (recién entró) no pasa nada.
                if (estado.fase == FaseCola.ESPERANDO_SESION && runCatching { session.obtener() }.getOrNull() == null) {
                    _eventos.trySend(PanelEvento.SinSesion)
                }
            }
        }
    }

    /**
     * FE-2.2, `ON_RESUME` de la pantalla: al volver al Panel (7.5 con «Guardar y subir después» o «Descartar video»
     * vuelve a esta misma entrada de la pila, con este ViewModel) relee los recorridos locales para la tarjeta de
     * subidas y «Fotos pendientes». No llama al backend: totales, lugares, alertas y último video se cargan en `init`
     * y con «Reintentar»; desde FE-3.4, también aquí si los lugares cambiaron desde la última carga
     * ([debeRecargarResumen]): así «Lugares registrados» está al día al volver de 7.6/7.7.
     */
    fun alReanudar() {
        if (!conSesionAdmin) return
        val cargando = _state.value.cargandoResumen
        if (debeRecargarResumen(versionLugaresCargada, cambiosLugares?.value, cargando) ||
            debeRecargarResumen(versionAlertasCargada, cambiosAlertas?.value, cargando)
        ) {
            cargarResumen()
        }
        val c = cola ?: return
        val a = almacen ?: return
        viewModelScope.launch { refrescarLocal(a, c.estado.value) }
    }

    /** Relee los recorridos y actualiza la tarjeta de subidas y «Fotos pendientes» (si ya hay resumen). */
    private suspend fun refrescarLocal(a: AlmacenRecorridos, estado: EstadoCola) {
        val recorridos = try {
            a.listar()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            null
        }
        _state.update {
            it.copy(
                avisoSubidas = avisoSubidas(estado, recorridos.orEmpty()),
                resumen = resumenConPendientes(it.resumen, recorridos),
            )
        }
    }

    fun cargarResumen() {
        versionLugaresCargada = cambiosLugares?.value
        versionAlertasCargada = cambiosAlertas?.value
        _state.update { it.copy(cargandoResumen = true, errorResumen = false) }
        viewModelScope.launch {
            try {
                val resumen = repo.obtenerResumen()
                _state.update { it.copy(resumen = resumen, cargandoResumen = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(cargandoResumen = false, errorResumen = errorVisibleDelResumen(e)) }
            }
        }
    }

    fun cerrarSesion() {
        session.cerrarSesion()
        _eventos.trySend(PanelEvento.SesionCerrada)
    }

    class Factory(private val context: Context) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PanelAdminViewModel(
                // FE-2.2: GET /v1/admin/stats + la cola local de subida (ARCHITECTURE §5.6 y §5.10).
                RemoteAdminRepository(fotosPendientes = { Subidas.almacen.contarFotosPendientes() }),
                SessionManager(context.applicationContext),
                Subidas.almacen,
                Subidas.cola,
                CambiosLugares.version,
                CambiosAlertas.version,
            ) as T
    }
}