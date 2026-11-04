package com.example.myapplication.data.remote

import com.example.myapplication.data.local.LimitesRecodificacion
import com.example.myapplication.data.local.MotorImagenAndroid
import com.example.myapplication.data.local.PreparadorFoto
import com.example.myapplication.data.local.Recodificador
import com.example.myapplication.data.repository.FotoEscaneo
import com.example.myapplication.data.repository.LocalizacionRepository
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.usecase.ConversionRumbo
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File

/**
 * [LocalizacionRepository] real (FE-3.2): `POST /v1/localize` (backend §5.3; uso desde la app en ARCHITECTURE §5.10,
 * «Ubicarse»). Ruta pública: no lleva `Authorization` ni pasa por la sesión.
 *
 * 1. Re-codifica cada foto con [preparador] (por defecto `Recodificador` con [LimitesRecodificacion.LOCALIZACION]: lado
 *    mayor 1024 px, calidad 85, ≤ 1 572 864 bytes) en `<carpeta de la foto>/envio_<i>.jpg` (i desde 1), en
 *    `Dispatchers.IO`. Esas copias viven en la carpeta del escaneo y se borran con ella (`FotosEscaneo.cerrar`).
 * 2. Arma el `multipart/form-data`: una parte `fotos` por foto (`image/jpeg`, nombre `envio_<i>.jpg`) **en el orden de la
 *    lista** y la parte `metadatos` con [MetadatosLocalizacionDto] (`rumbos` normalizados con
 *    [ConversionRumbo.normalizar], `origen = "escaneo"`, `app_version` recortada a 40 o ausente).
 * 3. `llamar { api.localizar(…) }` y [MapeoDatosApi.resultadoUbicacion].
 *
 * Errores: los de [llamar] (`SinConexionException`, [ApiException] —`503 EMBEDDING_NO_DISPONIBLE` →
 * `FalloApi.EmbeddingNoDisponible`, `400 FOTOS_INVALIDAS` → `FalloApi.FotosInvalidas`—, [RespuestaInesperadaException])
 * y `FotoIlegibleException` si una foto no se puede re-codificar (no se llama al backend). La cancelación se propaga.
 */
class RemoteLocalizacionRepository(
    private val api: CampusApi = ClienteApi.api,
    private val preparador: PreparadorFoto = Recodificador(MotorImagenAndroid(), LimitesRecodificacion.LOCALIZACION),
    private val appVersion: String? = null,
    private val gson: Gson = Gson(),
) : LocalizacionRepository {

    override suspend fun localizar(fotos: List<FotoEscaneo>): ResultadoUbicacion {
        require(fotos.size in 1..MAX_FOTOS) { "POST /v1/localize admite de 1 a $MAX_FOTOS fotos (${fotos.size})" }
        val partes = withContext(Dispatchers.IO) {
            fotos.mapIndexed { i, foto ->
                val copia = File(foto.archivo.parentFile, "$PREFIJO_ENVIO${i + 1}.jpg")
                preparador.preparar(foto.archivo, copia)
                MultipartBody.Part.createFormData(PARTE_FOTOS, copia.name, copia.asRequestBody(JPEG))
            }
        }
        val metadatos = MetadatosLocalizacionDto(
            rumbos = fotos.map { f -> f.rumboGrados?.takeIf { it.isFinite() }?.let(ConversionRumbo::normalizar) },
            origen = ORIGEN,
            appVersion = appVersion?.trim()?.take(APP_VERSION_MAX)?.ifEmpty { null },
        )
        val cuerpo = gson.toJson(metadatos).toRequestBody(JSON)
        val dto = llamar { api.localizar(partes, cuerpo) }
        return MapeoDatosApi.resultadoUbicacion(dto)
    }

    companion object {
        /** `LOC_MAX_FOTOS` del backend (§5.10). */
        const val MAX_FOTOS = 5
        const val PARTE_FOTOS = "fotos"
        const val ORIGEN = "escaneo"
        const val PREFIJO_ENVIO = "envio_"
        const val APP_VERSION_MAX = 40
        private val JPEG = "image/jpeg".toMediaType()
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
