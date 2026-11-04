package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.ResultadoFrame
import java.io.File
import java.io.IOException

/**
 * Corrección visual de la guía (FE-5.3): `POST /v1/localize/frame` (backend §5.3, BE-5.1). Implementación real:
 * `RemoteFrameRepository` (`data/remote/`).
 *
 * [foto]: el JPEG tal como salió de la cámara (se re-codifica antes de enviarlo); [rumbo]: el de la foto en norte
 * verdadero, [0, 360), o `null`; ([previaLat], [previaLng]): la posición que la app cree tener ahora; [radioM]: el radio
 * de búsqueda (10 a 100) o `null` (el del backend, 40).
 *
 * Lanza lo que lanza `llamar` (ARCHITECTURE §5.10): `SinConexionException` (una [IOException]), `ApiException` (p. ej.
 * `503 EMBEDDING_NO_DISPONIBLE`, `400 FOTOS_INVALIDAS`) o `RespuestaInesperadaException`; y `FotoIlegibleException` si la
 * foto no se puede re-codificar (no se llama al backend).
 */
interface LocalizacionFrameRepository {
    @Throws(IOException::class)
    suspend fun localizarFrame(
        foto: File,
        rumbo: Double?,
        previaLat: Double,
        previaLng: Double,
        radioM: Double?,
    ): ResultadoFrame
}
