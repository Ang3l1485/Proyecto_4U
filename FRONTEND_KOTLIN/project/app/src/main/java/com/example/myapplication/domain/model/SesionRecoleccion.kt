package com.example.myapplication.domain.model

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Holder en memoria (único por proceso) con los datos que viajan entre las vistas de recolección
 * (decisión abierta 15, resuelta para este flujo):
 *
 *   7.3 UbicacionManual --[iniciar]--> 7.4 Recoleccion --[finalizar]--> 7.5 ResumenVideo
 *
 * Se vive solo mientras el proceso siga vivo. Si Android mata la app, el video ya guardado en disco
 * se puede retomar con `RecoleccionRepository.buscarEnCurso()`.
 */
object SesionDeRecoleccion {

    private val _inicio = MutableStateFlow<InicioRecoleccion?>(null)

    /** Punto, rumbo y nombre elegidos en 7.3; `null` si no hay recolección pendiente de arrancar. */
    val inicio: StateFlow<InicioRecoleccion?> = _inicio.asStateFlow()

    private val _resumen = MutableStateFlow<ResumenRecoleccion?>(null)

    /** Resumen del último video finalizado, para la vista 7.5. */
    val resumen: StateFlow<ResumenRecoleccion?> = _resumen.asStateFlow()

    /** La llama 7.3 al confirmar, justo antes de navegar a 7.4. */
    fun iniciar(inicio: InicioRecoleccion) {
        _inicio.value = inicio
        _resumen.value = null
    }

    /** La llama 7.4 cuando ya consumió el inicio (evita reiniciar el video al rotar o volver). */
    fun consumirInicio(): InicioRecoleccion? {
        val actual = _inicio.value
        _inicio.value = null
        return actual
    }

    /** La llama 7.4 al finalizar. */
    fun finalizar(resumen: ResumenRecoleccion) {
        _resumen.value = resumen
    }

    fun limpiar() {
        _inicio.value = null
        _resumen.value = null
    }
}