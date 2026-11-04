package com.example.myapplication.ui.ubicacion

import com.example.myapplication.data.local.FotoIlegibleException
import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.domain.model.ResultadoUbicacion
import kotlinx.coroutines.TimeoutCancellationException
import java.io.IOException

/*
 * Modelo de estado de la pantalla de escaneo.
 * La UI solo LEE EscaneoUiState y el ViewModel es el único que lo escribe.
 */

/** Etapa general del escaneo. */
enum class Fase {
    PREPARANDO,   // se están diciendo las instrucciones por voz
    ESCANEANDO,   // el usuario gira y se capturan fotos
    ANALIZANDO,   // 5 fotos listas, esperando al backend
    ERROR,        // algo falló; se muestra el mensaje y "Repetir"
}

/** Instrucción que se muestra (y se dice) mientras escanea. */
enum class Instruccion(val texto: String) {
    GIRAR("Gira lentamente\nhacia la derecha"),
    MAS_DESPACIO("Más despacio"),
    VERTICAL("Mantén el celular vertical"),
}

/** Errores posibles; [mensaje] se muestra y se lee en voz alta (seguido de «. Toca repetir para intentar otra vez.»). */
enum class ErrorEscaneo(val mensaje: String) {
    SIN_CONEXION("Sin conexión con el servidor"),
    TIEMPO_AGOTADO("El análisis tardó demasiado"),
    VUELTA_INCOMPLETA("No completaste la vuelta"),
    SIN_SENSOR("Este teléfono no tiene sensor de giro"),

    /** FE-3.2: `503` de `POST /v1/localize` (`EMBEDDING_NO_DISPONIBLE` u otro 503 del backend). Texto de §5.10. */
    SERVICIO_NO_DISPONIBLE("El servicio de ubicación no está disponible en este momento"),

    /** FE-3.2: `429` (API Gateway o backend). */
    DEMASIADOS_INTENTOS("Demasiados intentos, espera un momento"),

    /** FE-3.2: `400 FOTOS_INVALIDAS` o una foto que no se pudo re-codificar en el teléfono. */
    FOTOS_INVALIDAS("No pude procesar las fotos"),

    /** FE-3.2: cualquier otro error (`422`, `400 SOLICITUD_INVALIDA`, respuesta fuera de contrato, imprevisto). */
    DESCONOCIDO("Algo salió mal"),
    ;

    companion object {
        /**
         * Qué error ve la persona para una excepción de `LocalizacionRepository.localizar` (ARCHITECTURE §5.10,
         * «Ubicarse»). Lógica pura: la prueba `ErrorEscaneoTest`. El orden importa: el tiempo agotado es una
         * `CancellationException` y la foto ilegible y la falta de red son `IOException`.
         */
        fun deExcepcion(t: Throwable): ErrorEscaneo = when {
            t is TimeoutCancellationException -> TIEMPO_AGOTADO
            t is FotoIlegibleException -> FOTOS_INVALIDAS
            t is ApiException && (t.fallo == FalloApi.EmbeddingNoDisponible || t.http == 503) -> SERVICIO_NO_DISPONIBLE
            t is ApiException && t.fallo == FalloApi.DemasiadosIntentos -> DEMASIADOS_INTENTOS
            t is ApiException && t.fallo is FalloApi.FotosInvalidas -> FOTOS_INVALIDAS
            t is IOException -> SIN_CONEXION
            else -> DESCONOCIDO
        }
    }
}

/** Estado completo que dibuja la pantalla. */
data class EscaneoUiState(
    val fase: Fase = Fase.PREPARANDO,
    val progreso: Float = 0f,          // grados girados, 0..360
    val fotos: Int = 0,                // fotos aceptadas hasta ahora
    val inclinacionOk: Boolean = true, // celular suficientemente vertical
    val instruccion: Instruccion = Instruccion.GIRAR,
    val error: ErrorEscaneo? = null,
)

/** Eventos de una sola vez ViewModel -> pantalla (no son estado). Viajan por un `Channel` (no se pierden al rotar). */
sealed interface EscaneoEvento {
    /** Pide a la pantalla que dispare la cámara (la pantalla es dueña de CameraX). */
    data object Capturar : EscaneoEvento

    /**
     * `POST /v1/localize` respondió `200` (FE-3.2): [resultado] y el rumbo **verdadero** de la última lectura del giro
     * ([rumboAlTerminar], [0, 360), o `null`). La ruta lo guarda en `SesionDeNavegacion` y abre el Resultado (6.3).
     */
    data class Completado(val resultado: ResultadoUbicacion, val rumboAlTerminar: Double?) : EscaneoEvento
}
