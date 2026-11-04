package com.example.myapplication.ui.admin.lugares

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.myapplication.data.remote.RemoteLugaresAdminRepository
import com.example.myapplication.data.repository.LugaresAdminRepository
import com.example.myapplication.domain.model.CategoriaLugar
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Vista 7.7 · Formulario de lugar (FE-3.4). [lugarId] `null` = lugar nuevo (`POST`); si no, edita ese lugar (`PUT`),
 * que lee de `GET /v1/admin/places` (no hay `GET` por id; sobrevive a la muerte del proceso porque el id va en la ruta).
 *
 * Guardar: valida en local (`FormularioLugar.validar`); si pasa, envía `FormularioLugar.datos` (coordenada redondeada
 * a 6 decimales: la misma que muestra el pie «Punto: …»). Un error del backend se muestra en su campo
 * (`ErroresLugarMapeo`: el `409 NOMBRE_DUPLICADO` bajo el nombre) y **no** sale del formulario. Un éxito emite
 * [LugarFormEvento.Guardado] y la pantalla vuelve a 7.6, que recarga por `CambiosLugares`.
 */
class LugarFormViewModel(
    private val lugarId: String?,
    private val repo: LugaresAdminRepository,
) : ViewModel() {

    private val _estado = MutableStateFlow(LugarFormUiState(esNuevo = lugarId == null, cargando = lugarId != null))
    val estado: StateFlow<LugarFormUiState> = _estado.asStateFlow()

    private val _eventos = Channel<LugarFormEvento>(Channel.BUFFERED)
    val eventos: Flow<LugarFormEvento> = _eventos.receiveAsFlow()

    init {
        cargar()
    }

    /**
     * Lee los lugares: los demás van al mapa como contexto y, editando, rellena los campos con el lugar. Si falla al
     * crear, sigue sin contexto; si falla al editar, muestra el error con «Reintentar».
     */
    fun cargar() {
        if (lugarId != null) _estado.update { it.copy(cargando = true, errorCarga = null) }
        viewModelScope.launch {
            try {
                val todos = repo.listar()
                val otros = todos.filter { it.id != lugarId }.map { it.lugar }
                if (lugarId == null) {
                    _estado.update { it.copy(otros = otros) }
                    return@launch
                }
                val lugar = todos.firstOrNull { it.id == lugarId }
                _estado.update {
                    if (lugar == null) it.copy(cargando = false, errorCarga = ErroresLugarMapeo.NO_EXISTE)
                    else it.copy(
                        cargando = false, otros = otros, campos = FormularioLugar.campos(lugar), totalFotos = lugar.totalFotos,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (lugarId != null) {
                    val texto = ErroresLugarMapeo.errorDeCarga(e)
                    _estado.update { it.copy(cargando = false, errorCarga = texto?.let { _ -> "No se pudo leer el lugar: $texto" }) }
                }
            }
        }
    }

    private fun cambiar(f: (CamposLugar) -> CamposLugar, limpiar: (ErroresLugar) -> ErroresLugar) =
        _estado.update { it.copy(campos = f(it.campos), errores = limpiar(it.errores).copy(general = null)) }

    fun alNombre(t: String) = cambiar({ it.copy(nombre = t) }, { it.copy(nombre = null) })
    fun alAlias(t: String) = cambiar({ it.copy(aliasTexto = t) }, { it.copy(alias = null) })
    fun alDescripcion(t: String) = cambiar({ it.copy(descripcion = t) }, { it.copy(descripcion = null) })
    fun alReferencias(t: String) = cambiar({ it.copy(referencias = t) }, { it.copy(referencias = null) })
    fun alCategoria(c: CategoriaLugar) = cambiar({ it.copy(categoria = c) }, { it.copy(categoria = null) })

    /** Toque o alfiler soltado en el mapa: se guarda ya redondeado (lo que se ve es lo que se envía). */
    fun alPunto(lat: Double, lng: Double) = cambiar(
        { it.copy(punto = FormularioLugar.redondear(lat) to FormularioLugar.redondear(lng)) },
        { it.copy(punto = null) },
    )

    fun guardar() {
        val s = _estado.value
        if (s.guardando || s.cargando || s.errorCarga != null) return
        val errores = FormularioLugar.validar(s.campos)
        val datos = FormularioLugar.datos(s.campos)
        if (errores.hay || datos == null) {
            _estado.update { it.copy(errores = errores) }
            return
        }
        _estado.update { it.copy(guardando = true, errores = ErroresLugar.NINGUNO) }
        viewModelScope.launch {
            try {
                val guardado = if (lugarId == null) repo.crear(datos) else repo.reemplazar(lugarId, datos)
                _eventos.send(LugarFormEvento.Guardado(guardado.nombre))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _estado.update { it.copy(guardando = false, errores = ErroresLugarMapeo.deExcepcion(e) ?: ErroresLugar.NINGUNO) }
            }
        }
    }

    fun pedirBorrar() = _estado.update { if (it.esNuevo || it.guardando) it else it.copy(confirmandoBorrar = true) }
    fun cancelarBorrar() = _estado.update { it.copy(confirmandoBorrar = false) }

    fun confirmarBorrar() {
        val id = lugarId ?: return
        val nombre = _estado.value.campos.nombre.trim()
        _estado.update { it.copy(confirmandoBorrar = false, guardando = true, errores = ErroresLugar.NINGUNO) }
        viewModelScope.launch {
            try {
                repo.borrar(id)
                _eventos.send(LugarFormEvento.Eliminado(nombre))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val errores = ErroresLugarMapeo.deExcepcion(e)
                _estado.update { it.copy(guardando = false, errores = ErroresLugar(general = errores?.general)) }
            }
        }
    }

    class Factory(private val lugarId: String?) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            LugarFormViewModel(lugarId, RemoteLugaresAdminRepository()) as T
    }
}
