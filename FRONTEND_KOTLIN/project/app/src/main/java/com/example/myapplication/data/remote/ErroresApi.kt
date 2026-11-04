package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.CredencialesInvalidasException
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import retrofit2.Response
import java.io.IOException

/**
 * Qué significa para la app una respuesta de error (tabla «Errores → modelos de la app» de ARCHITECTURE §5.10).
 * Lo produce [MapeoErroresApi.clasificar]; cada ViewModel decide qué decir con él.
 */
sealed interface FalloApi {
    /** Sin red, *timeout* o `5xx` generado por API Gateway (cuerpo `{"message": …}`). */
    data object SinConexion : FalloApi

    /** `401 CREDENCIALES_INVALIDAS` (login). */
    data object CredencialesInvalidas : FalloApi

    /** `401 TOKEN_EXPIRADO`, `TOKEN_INVALIDO` o `NO_AUTENTICADO`: cerrar la sesión e ir a Login (FE-1.2). */
    data class SesionVencida(val codigo: String) : FalloApi

    /** `403 SIN_PERMISOS`. */
    data object SinPermisos : FalloApi

    /** `429`, del backend o de API Gateway. */
    data object DemasiadosIntentos : FalloApi

    /** `503 EMBEDDING_NO_DISPONIBLE` (`POST /v1/localize` con embeddings apagado o arrancando). */
    data object EmbeddingNoDisponible : FalloApi

    /**
     * `400 FOTOS_INVALIDAS` (`POST /v1/localize`, FE-3.2): `detalle.indice` (la foto, 0 = la primera) y `detalle.motivo`
     * (texto corto para humanos, p. ej. «embeddings la rechazó (IMAGEN_INVALIDA)»). Solo se registra; la persona oye
     * «No pude procesar las fotos».
     */
    data class FotosInvalidas(val indice: Int?, val motivo: String?) : FalloApi

    /** `409` o `422`: [campos] sale de `detalle.campos` (vacío en los `409`, que solo traen [codigo]). */
    data class Validacion(
        val http: Int,
        val codigo: String?,
        val mensaje: String?,
        val campos: List<CampoInvalido>,
    ) : FalloApi

    /** Cualquier otra respuesta: «Algo salió mal»; se registra el `X-Request-Id`. */
    data class Desconocido(val http: Int?, val codigo: String?) : FalloApi
}

/** Un elemento de `detalle.campos` de un `422 VALIDACION`. */
data class CampoInvalido(val campo: String, val motivo: String)

/**
 * Error de la API que no es «sin conexión» ni «credenciales inválidas» (esos dos se lanzan como
 * [SinConexionException] y [CredencialesInvalidasException], que ya entienden los ViewModels de hoy).
 * [requestId] es el `X-Request-Id` de la respuesta, para buscarla en los logs del servidor.
 */
class ApiException(
    val fallo: FalloApi,
    val http: Int,
    val requestId: String?,
) : Exception("HTTP $http: $fallo")

/** «Sin conexión» (§5.10). Es una [IOException]: los ViewModels que ya atrapan `IOException` la tratan igual. */
class SinConexionException(val requestId: String? = null, causa: Throwable? = null) :
    IOException("Sin conexión con el backend", causa)

/** Respuesta 2xx que no cumple el contrato (cuerpo vacío, JSON roto, falta un campo obligatorio). */
class RespuestaInesperadaException(mensaje: String, causa: Throwable? = null) : Exception(mensaje, causa)

/** Mapeo de errores de ARCHITECTURE §5.10. Lógica pura (sin Android): se prueba en `MapeoErroresApiTest`. */
object MapeoErroresApi {

    val CODIGOS_SESION = setOf("TOKEN_EXPIRADO", "TOKEN_INVALIDO", "NO_AUTENTICADO")

    /**
     * Código de [FalloApi.SesionVencida] cuando la petición protegida no salió del teléfono porque no había sesión o su
     * `expira_en` ya había pasado (FE-1.2, [SinSesionException]). No lo envía nunca el backend.
     */
    const val SIN_SESION_LOCAL = "SIN_SESION_LOCAL"

    /** `error.codigo` de un cuerpo de error del backend (§5.1), o `null` (otro formato, vacío o JSON roto). */
    fun codigoError(cuerpo: String?): String? =
        objetoJson(cuerpo)?.get("error")?.takeIf { it.isJsonObject }?.asJsonObject?.texto("codigo")

    /** Clasifica una respuesta no exitosa a partir de su código HTTP y su cuerpo (texto, puede ser null). */
    fun clasificar(http: Int, cuerpo: String?): FalloApi {
        val json = objetoJson(cuerpo)
        val error = json?.get("error")?.takeIf { it.isJsonObject }?.asJsonObject
        val codigo = error?.texto("codigo")
        // API Gateway responde con {"message": …} y sin la clave "error" (backend §5.1, infra §5.13).
        val deApiGateway = error == null && json?.has("message") == true
        return when {
            http == 429 -> FalloApi.DemasiadosIntentos
            http in 500..599 && deApiGateway -> FalloApi.SinConexion
            http == 401 && codigo == "CREDENCIALES_INVALIDAS" -> FalloApi.CredencialesInvalidas
            http == 401 && codigo in CODIGOS_SESION -> FalloApi.SesionVencida(codigo!!)
            http == 403 && codigo == "SIN_PERMISOS" -> FalloApi.SinPermisos
            http == 503 && codigo == "EMBEDDING_NO_DISPONIBLE" -> FalloApi.EmbeddingNoDisponible
            http == 400 && codigo == "FOTOS_INVALIDAS" -> {
                val detalle = error?.get("detalle")?.takeIf { it.isJsonObject }?.asJsonObject
                val indice = detalle?.get("indice")?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber }?.asInt
                FalloApi.FotosInvalidas(indice, detalle?.texto("motivo"))
            }
            http == 409 || http == 422 -> FalloApi.Validacion(http, codigo, error?.texto("mensaje"), campos(error))
            else -> FalloApi.Desconocido(http, codigo)
        }
    }

    /** La excepción que lanza [llamar] para un fallo. */
    fun excepcion(fallo: FalloApi, http: Int, requestId: String?): Exception = when (fallo) {
        FalloApi.SinConexion -> SinConexionException(requestId)
        FalloApi.CredencialesInvalidas -> CredencialesInvalidasException()
        else -> ApiException(fallo, http, requestId)
    }

    /** Qué fallo representa cualquier excepción de una llamada (para los ViewModels). */
    fun deExcepcion(t: Throwable): FalloApi = when (t) {
        is ApiException -> t.fallo
        is CredencialesInvalidasException -> FalloApi.CredencialesInvalidas
        is SinSesionException -> FalloApi.SesionVencida(SIN_SESION_LOCAL)
        is IOException -> FalloApi.SinConexion
        else -> FalloApi.Desconocido(null, null)
    }

    private fun campos(error: JsonObject?): List<CampoInvalido> {
        val lista = error?.get("detalle")?.takeIf { it.isJsonObject }?.asJsonObject
            ?.get("campos")?.takeIf { it.isJsonArray }?.asJsonArray ?: return emptyList()
        return lista.mapNotNull { e ->
            val o = e.takeIf { it.isJsonObject }?.asJsonObject ?: return@mapNotNull null
            val campo = o.texto("campo") ?: return@mapNotNull null
            CampoInvalido(campo, o.texto("motivo") ?: "")
        }
    }

    private fun objetoJson(cuerpo: String?): JsonObject? {
        if (cuerpo.isNullOrBlank()) return null
        return try {
            JsonParser.parseString(cuerpo).takeIf { it.isJsonObject }?.asJsonObject
        } catch (_: RuntimeException) {
            null
        }
    }

    private fun JsonObject.texto(clave: String): String? =
        get(clave)?.takeIf(JsonElement::isJsonPrimitive)?.asString
}

/**
 * Ejecuta una llamada de [CampusApi] y devuelve el cuerpo de un 2xx, o lanza la excepción de §5.10:
 * [SinConexionException] (red, *timeout*, 5xx de API Gateway), [CredencialesInvalidasException] o [ApiException].
 * Un 2xx sin cuerpo o con JSON roto lanza [RespuestaInesperadaException]. La cancelación de la corrutina se propaga.
 */
suspend fun <T : Any> llamar(peticion: suspend () -> Response<T>): T {
    val respuesta = ejecutarPeticion(peticion)
    if (respuesta.isSuccessful) {
        return respuesta.body() ?: throw RespuestaInesperadaException("Respuesta ${respuesta.code()} sin cuerpo")
    }
    lanzarError(respuesta)
}

/**
 * Como [llamar], para rutas que responden sin cuerpo (`204`, p. ej. `DELETE /v1/admin/images/{id}`): Retrofit da
 * `body() == null` en un 204, así que [llamar] lo trataría como respuesta inesperada. Declararlas `Response<Unit>`.
 */
suspend fun llamarSinCuerpo(peticion: suspend () -> Response<Unit>) {
    val respuesta = ejecutarPeticion(peticion)
    if (!respuesta.isSuccessful) lanzarError(respuesta)
}

private suspend fun <T> ejecutarPeticion(peticion: suspend () -> Response<T>): Response<T> = try {
    peticion()
} catch (e: SinSesionException) {
    // Va antes de IOException: la petición protegida no salió del teléfono (sin sesión o vencida), no es la red.
    throw ApiException(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), 401, null)
} catch (e: com.google.gson.stream.MalformedJsonException) {
    // Va antes de IOException: Gson la lanza como IOException, pero es un cuerpo 2xx roto, no un fallo de red.
    throw RespuestaInesperadaException("JSON inválido en una respuesta 2xx", e)
} catch (e: com.google.gson.JsonParseException) {
    throw RespuestaInesperadaException("JSON inválido en una respuesta 2xx", e)
} catch (e: IOException) {
    throw SinConexionException(null, e)
}

private fun lanzarError(respuesta: Response<*>): Nothing {
    val requestId = respuesta.headers()[ENCABEZADO_REQUEST_ID]
    val cuerpo = try {
        respuesta.errorBody()?.string()
    } catch (_: IOException) {
        null
    }
    val fallo = MapeoErroresApi.clasificar(respuesta.code(), cuerpo)
    throw MapeoErroresApi.excepcion(fallo, respuesta.code(), requestId)
}
