package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ReferenciaLugar
import com.example.myapplication.domain.model.ResultadoUbicacion
import kotlinx.coroutines.delay
import java.io.File
import java.io.IOException

/**
 * Una foto del escaneo 360° con su rumbo **verdadero** en [0, 360) (ya convertido con `ConversionRumbo`), o `null` si
 * se desconoce. El orden de la lista que se pasa a [LocalizacionRepository.localizar] es el de `fotos` y `rumbos`.
 */
data class FotoEscaneo(val archivo: File, val rumboGrados: Double?)

/**
 * «Ubicarse» (FE-3.2): `POST /v1/localize` (backend §5.3). Reemplaza al antiguo `ui/ubicacion/EscaneoBackend` (que no
 * seguía la convención de §5.6). Implementación real: `RemoteLocalizacionRepository` (`data/remote/`).
 *
 * Lanza lo que lanza `llamar` (ARCHITECTURE §5.10): `SinConexionException` (una [IOException]), `ApiException` (p. ej.
 * `503 EMBEDDING_NO_DISPONIBLE`) o `RespuestaInesperadaException`; y `FotoIlegibleException` (una [IOException]) si una
 * foto no se puede re-codificar. El ViewModel los traduce con `ErrorEscaneo.deExcepcion`.
 */
interface LocalizacionRepository {
    @Throws(IOException::class)
    suspend fun localizar(fotos: List<FotoEscaneo>): ResultadoUbicacion
}

/** Ubicación de ejemplo (vistas previas y el stub): cerca de la biblioteca, con dos referencias. */
val RESULTADO_DE_PRUEBA = ResultadoUbicacion.Ubicado(
    posicion = PosicionEstimada(6.200104, -75.578612, 8.5),
    confianza = 0.78,
    nivel = NivelConfianza.ALTA,
    correccionRumboGrados = -6.0,
    lugarCercano = LugarCercano("biblioteca-central", "Biblioteca Central", 12.4),
    referencias = listOf(
        ReferenciaLugar("bloque-trillizos", "Bloque de los Trillizos", 35.2, 95.0),
        ReferenciaLugar("cafeteria-principal", "Cafetería Principal", 80.0, 270.0),
    ),
    fotosUsadas = 5,
    fotosConCoincidencia = 4,
)

/** Stub sin red: espera [esperaMs] y devuelve [resultado]. Solo para desarrollo y vistas previas. */
class LocalizacionRepositoryStub(
    private val resultado: ResultadoUbicacion = RESULTADO_DE_PRUEBA,
    private val esperaMs: Long = 2_500,
) : LocalizacionRepository {
    override suspend fun localizar(fotos: List<FotoEscaneo>): ResultadoUbicacion {
        delay(esperaMs)
        return resultado
    }
}
