package com.example.myapplication.ui.admin.lugares

import com.example.myapplication.data.remote.CampoInvalido
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.MapeoErroresApi

/**
 * Qué muestra el formulario de lugar (7.7) ante un error del backend al guardar o borrar (FE-3.4; lógica pura, se prueba en `ErroresLugarTest`; tabla de §5.10: «`409` / `422`: mensaje del
 * campo afectado en formularios de admin»).
 */
internal object ErroresLugarMapeo {
    /** El `409 NOMBRE_DUPLICADO` (backend §5.5, `detalle: null`) va bajo el campo nombre con este texto. */
    const val NOMBRE_DUPLICADO = "Ya existe un lugar con ese nombre (sin distinguir mayúsculas ni tildes)."
    const val SIN_CONEXION = "Sin conexión. Revisa tu conexión a internet e inténtalo de nuevo."
    const val NO_EXISTE = "Este lugar ya no existe (lo borró otra persona). Vuelve a la lista."
    const val SIN_PERMISOS = "Tu cuenta no tiene permisos de administrador."
    const val DEMASIADOS_INTENTOS = "Demasiados intentos. Espera un momento."
    const val ALGO_SALIO_MAL = "Algo salió mal. Inténtalo de nuevo."
    const val CAMPO_INVALIDO = "No es válido."
    const val ERROR_CARGA = "No se pudo cargar la lista de lugares."

    /**
     * Error al **leer** los lugares (7.6, 7.7 editando, la hoja de 7.4): «Sin conexión…» o [ERROR_CARGA]; `null` con la
     * sesión perdida (no se muestra nada: `AppNav` va a Login).
     */
    fun errorDeCarga(e: Throwable): String? = when (MapeoErroresApi.deExcepcion(e)) {
        is FalloApi.SesionVencida -> null
        FalloApi.SinConexion -> SIN_CONEXION
        else -> ERROR_CARGA
    }

    /** Para un `catch` del ViewModel. `null` = no mostrar nada (sesión perdida: `AppNav` ya va a Login). */
    fun deExcepcion(e: Throwable): ErroresLugar? = deFallo(MapeoErroresApi.deExcepcion(e))

    fun deFallo(fallo: FalloApi): ErroresLugar? = when (fallo) {
        is FalloApi.SesionVencida -> null
        is FalloApi.Validacion -> when {
            fallo.http == 409 && fallo.codigo == "NOMBRE_DUPLICADO" -> ErroresLugar(nombre = NOMBRE_DUPLICADO)
            fallo.campos.isNotEmpty() -> deCampos(fallo.campos)
            else -> ErroresLugar(general = fallo.mensaje?.takeIf { it.isNotBlank() } ?: ALGO_SALIO_MAL)
        }
        is FalloApi.Desconocido -> if (fallo.http == 404) ErroresLugar(general = NO_EXISTE)
        else ErroresLugar(general = ALGO_SALIO_MAL)
        FalloApi.SinConexion -> ErroresLugar(general = SIN_CONEXION)
        FalloApi.SinPermisos -> ErroresLugar(general = SIN_PERMISOS)
        FalloApi.DemasiadosIntentos -> ErroresLugar(general = DEMASIADOS_INTENTOS)
        else -> ErroresLugar(general = ALGO_SALIO_MAL)
    }

    /**
     * `422 VALIDACION` con `detalle.campos`: cada campo va a su lugar del formulario por el primer tramo conocido de su
     * nombre (`nombre`, `alias.3` → alias, `lat`/`lng` → punto…); un campo desconocido va al mensaje general.
     */
    private fun deCampos(campos: List<CampoInvalido>): ErroresLugar {
        var e = ErroresLugar.NINGUNO
        val otros = mutableListOf<String>()
        for (c in campos) {
            val motivo = c.motivo.ifBlank { CAMPO_INVALIDO }
            when (c.campo.split('.').firstOrNull { it in CLAVES }) {
                "nombre" -> e = e.copy(nombre = e.nombre ?: motivo)
                "alias" -> e = e.copy(alias = e.alias ?: motivo)
                "descripcion" -> e = e.copy(descripcion = e.descripcion ?: motivo)
                "referencias" -> e = e.copy(referencias = e.referencias ?: motivo)
                "categoria" -> e = e.copy(categoria = e.categoria ?: motivo)
                "lat", "lng" -> e = e.copy(punto = e.punto ?: motivo)
                else -> otros += "${c.campo}: $motivo"
            }
        }
        return if (otros.isEmpty()) e else e.copy(general = "Revisa los datos (${otros.joinToString("; ")}).")
    }

    private val CLAVES = setOf("nombre", "alias", "descripcion", "referencias", "categoria", "lat", "lng")
}
