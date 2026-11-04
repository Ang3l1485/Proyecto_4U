package com.example.myapplication.data.remote

import com.example.myapplication.data.local.LimitesRecodificacion
import com.example.myapplication.data.local.MotorImagenAndroid
import com.example.myapplication.data.local.PreparadorFoto
import com.example.myapplication.data.local.Recodificador
import com.example.myapplication.data.repository.LocalizacionFrameRepository
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.ResultadoFrame
import com.example.myapplication.domain.usecase.ConversionRumbo
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.util.Locale

/** Respuesta `200` de `POST /v1/localize/frame`; todo anulable (§5.10, trampa de los DTOs). */
data class FrameRespuestaDto(
    @SerializedName("resultado") val resultado: String? = null,
    @SerializedName("posicion") val posicion: PosicionDto? = null,
    @SerializedName("confianza") val confianza: Double? = null,
    @SerializedName("nivel") val nivel: String? = null,
    @SerializedName("distancia_previa_m") val distanciaPreviaM: Double? = null,
    @SerializedName("radio_busqueda_m") val radioBusquedaM: Double? = null,
    @SerializedName("imagenes_en_radio") val imagenesEnRadio: Int? = null,
    @SerializedName("version_vector") val versionVector: String? = null,
    @SerializedName("latencia_ms") val latenciaMs: Int? = null,
)

/**
 * [LocalizacionFrameRepository] real (FE-5.3): `POST /v1/localize/frame` (backend §5.3). Ruta pública: sin
 * `Authorization` ni sesión. `RemoteFrameRepositoryTest` (MockWebServer).
 *
 * 1. Re-codifica la foto con [preparador] (por defecto, como el escaneo: `LimitesRecodificacion.LOCALIZACION`, lado
 *    mayor 1024 px, calidad 85, ≤ 1 572 864 bytes) en `<carpeta de la foto>/envio_<nombre>`, en `Dispatchers.IO`. La
 *    copia se borra al terminar (también con error); el original es de quien llama.
 * 2. `multipart/form-data`: **una** parte `foto` (`image/jpeg`; no `fotos`, que es la de `/v1/localize`) y la parte
 *    `metadatos` (`application/json; charset=utf-8`) con `{"rumbo": 84.5, "posicion_previa": {"lat": …, "lng": …},
 *    "radio_m": 40.0, "app_version": "1.0"}`: `rumbo` normalizado con [ConversionRumbo.normalizar] o `null` (siempre
 *    presente), `radio_m` recortado a [10, 100] u omitido, `app_version` recortada a 40 u omitida.
 * 3. `llamar { api.localizarFrame(…) }` y [resultado].
 */
class RemoteFrameRepository(
    private val api: CampusApi = ClienteApi.api,
    private val preparador: PreparadorFoto = Recodificador(MotorImagenAndroid(), LimitesRecodificacion.LOCALIZACION),
    private val appVersion: String? = null,
) : LocalizacionFrameRepository {

    private val gson: Gson = GsonBuilder().serializeNulls().create()

    override suspend fun localizarFrame(
        foto: File,
        rumbo: Double?,
        previaLat: Double,
        previaLng: Double,
        radioM: Double?,
    ): ResultadoFrame {
        val copia = File(foto.parentFile, "$PREFIJO_ENVIO${foto.name}")
        try {
            val parte = withContext(Dispatchers.IO) {
                preparador.preparar(foto, copia)
                MultipartBody.Part.createFormData(PARTE_FOTO, copia.name, copia.asRequestBody(JPEG))
            }
            val metadatos = metadatos(
                rumbo = rumbo?.takeIf { it.isFinite() }?.let(ConversionRumbo::normalizar),
                previaLat = previaLat,
                previaLng = previaLng,
                radioM = radioM?.takeIf { it.isFinite() }?.coerceIn(RADIO_MIN_M, RADIO_MAX_M),
                appVersion = appVersion?.trim()?.take(APP_VERSION_MAX)?.ifEmpty { null },
            )
            val dto = llamar { api.localizarFrame(parte, metadatos.toRequestBody(JSON)) }
            return resultado(dto)
        } finally {
            withContext(Dispatchers.IO) { copia.delete() }
        }
    }

    /** JSON de `metadatos`: `rumbo` siempre (aunque sea `null`, el backend lo exige); `radio_m` y `app_version` solo si hay. */
    private fun metadatos(rumbo: Double?, previaLat: Double, previaLng: Double, radioM: Double?, appVersion: String?): String {
        val o = JsonObject()
        if (rumbo == null) o.add("rumbo", JsonNull.INSTANCE) else o.addProperty("rumbo", rumbo)
        o.add("posicion_previa", JsonObject().apply {
            addProperty("lat", previaLat)
            addProperty("lng", previaLng)
        })
        radioM?.let { o.addProperty("radio_m", it) }
        appVersion?.let { o.addProperty("app_version", it) }
        return gson.toJson(o)
    }

    companion object {
        const val PARTE_FOTO = "foto"
        const val PREFIJO_ENVIO = "envio_"
        const val APP_VERSION_MAX = 40

        /** `LOC_FRAME_RADIO_MIN_M` y `LOC_FRAME_RADIO_MAX_M` del backend (§5.10): fuera, `422`. */
        const val RADIO_MIN_M = 10.0
        const val RADIO_MAX_M = 100.0

        private val JPEG = "image/jpeg".toMediaType()
        private val JSON = "application/json; charset=utf-8".toMediaType()

        /**
         * Respuesta → [ResultadoFrame]: `sin_coincidencias` → `SinCoincidencias`; `ok` → `Ubicado` (exige `posicion` con
         * `lat`, `lng` y `radio_m`, `confianza`, un `nivel` conocido y `distancia_previa_m`). Los dos exigen
         * `radio_busqueda_m` e `imagenes_en_radio`. Otro `resultado` o un campo que falta → `RespuestaInesperadaException`.
         */
        fun resultado(dto: FrameRespuestaDto): ResultadoFrame {
            val radio = obligatorio(dto.radioBusquedaM, "radio_busqueda_m")
            val enRadio = obligatorio(dto.imagenesEnRadio, "imagenes_en_radio")
            return when (dto.resultado?.trim()?.lowercase(Locale.ROOT)) {
                "sin_coincidencias" -> ResultadoFrame.SinCoincidencias(radio, enRadio)
                "ok" -> {
                    val p = obligatorio(dto.posicion, "posicion")
                    ResultadoFrame.Ubicado(
                        lat = obligatorio(p.lat, "posicion.lat"),
                        lng = obligatorio(p.lng, "posicion.lng"),
                        radioM = obligatorio(p.radioM, "posicion.radio_m"),
                        confianza = obligatorio(dto.confianza, "confianza"),
                        nivel = MapeoDatosApi.enumDe<NivelConfianza>(dto.nivel)
                            ?: throw RespuestaInesperadaException("nivel desconocido: ${dto.nivel}"),
                        distanciaPreviaM = obligatorio(dto.distanciaPreviaM, "distancia_previa_m"),
                        radioBusquedaM = radio,
                        imagenesEnRadio = enRadio,
                    )
                }
                else -> throw RespuestaInesperadaException("resultado desconocido: ${dto.resultado}")
            }
        }

        private fun <T> obligatorio(valor: T?, campo: String): T =
            valor ?: throw RespuestaInesperadaException("falta $campo en la respuesta de POST /v1/localize/frame")
    }
}
