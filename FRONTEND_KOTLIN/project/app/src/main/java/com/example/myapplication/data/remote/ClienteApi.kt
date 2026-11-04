package com.example.myapplication.data.remote

import com.example.myapplication.ApiConfig
import com.example.myapplication.logs.AppLog
import com.example.myapplication.session.VigilanteSesion
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

const val ENCABEZADO_REQUEST_ID = "X-Request-Id"
private const val TAG = "Api"

// Rutas que llevan `Authorization: Bearer` (backend §5.1): /v1/admin/... y /v1/collect/...
// (Ojo: en un KDoc, «/*» abre un comentario anidado de Kotlin y rompe la compilación.)
private val RUTA_PROTEGIDA = Regex(".*/v1/(admin|collect)(/.*)?")

/**
 * Pone un `X-Request-Id` (UUID v4) en cada petición que no lo traiga y registra una línea por petición:
 * `GET /v1/health -> 200 (85 ms) rid=<uuid>` o `GET /v1/health -> falla UnknownHostException (3 ms) rid=<uuid>`.
 * Solo método, ruta (sin parámetros), código y duración: nunca encabezados ni cuerpos (token, contraseña).
 */
class RequestIdInterceptor(private val registrar: (String) -> Unit) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val rid = original.header(ENCABEZADO_REQUEST_ID) ?: UUID.randomUUID().toString()
        val peticion = original.newBuilder().header(ENCABEZADO_REQUEST_ID, rid).build()
        val linea = "${peticion.method} ${peticion.url.encodedPath}"
        val inicio = System.nanoTime()
        val respuesta = try {
            chain.proceed(peticion)
        } catch (e: IOException) {
            registrar("$linea -> falla ${e.javaClass.simpleName} (${ms(inicio)} ms) rid=$rid")
            throw e
        }
        val ridServidor = respuesta.header(ENCABEZADO_REQUEST_ID) ?: rid
        registrar("$linea -> ${respuesta.code} (${ms(inicio)} ms) rid=$ridServidor")
        return respuesta
    }

    private fun ms(inicio: Long) = (System.nanoTime() - inicio) / 1_000_000
}

/** Añade `Authorization: Bearer <token>` solo en las rutas protegidas y solo si [token] devuelve uno. */
class AutenticacionInterceptor(private val token: () -> String?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val peticion = chain.request()
        if (!RUTA_PROTEGIDA.matches(peticion.url.encodedPath)) return chain.proceed(peticion)
        val t = token()?.takeIf { it.isNotBlank() } ?: return chain.proceed(peticion)
        return chain.proceed(peticion.newBuilder().header("Authorization", "Bearer $t").build())
    }
}

/**
 * La petición protegida no se envió porque no hay sesión o su `expira_en` ya pasó (FE-1.2). Es una [IOException]
 * porque OkHttp solo admite esas desde un interceptor (otra excepción cerraría la app); [llamar] la convierte en
 * `ApiException(FalloApi.SesionVencida(MapeoErroresApi.SIN_SESION_LOCAL), 401, null)`, nunca en «sin conexión».
 */
class SinSesionException(val ruta: String) : IOException("Sin sesión: la petición a $ruta no se envió")

/**
 * Sesión en las rutas protegidas (`/v1/admin/…`, `/v1/collect/…`; FE-1.2, ARCHITECTURE §5.10). En las demás no hace
 * nada. En una protegida:
 * 1. Pide la sesión a [vigilante]; sin sesión o vencida, lanza [SinSesionException] sin llamar al backend
 *    (el vigilante ya avisó con `onSinSesion`).
 * 2. Envía la petición con `Authorization: Bearer <token de esa sesión>`.
 * 3. Si la respuesta es `401` con `TOKEN_EXPIRADO`, `TOKEN_INVALIDO` o `NO_AUTENTICADO`, avisa a [vigilante] (cierra la
 *    sesión y emite `onSinSesion`) y devuelve la respuesta sin tocarla: [llamar] la convierte en
 *    `ApiException(FalloApi.SesionVencida(codigo))`.
 */
class SesionInterceptor(private val vigilante: VigilanteSesion) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val peticion = chain.request()
        val ruta = peticion.url.encodedPath
        if (!RUTA_PROTEGIDA.matches(ruta)) return chain.proceed(peticion)
        val descripcion = "${peticion.method} $ruta"
        val sesion = vigilante.sesionParaPeticion(descripcion) ?: throw SinSesionException(ruta)
        val respuesta = chain.proceed(peticion.newBuilder().header("Authorization", "Bearer ${sesion.token}").build())
        if (respuesta.code == 401) {
            val codigo = MapeoErroresApi.codigoError(respuesta.peekBody(MAX_CUERPO_ERROR).string())
            if (codigo != null && codigo in MapeoErroresApi.CODIGOS_SESION) {
                vigilante.rechazada(codigo, sesion.token, descripcion)
            }
        }
        return respuesta
    }

    private companion object {
        const val MAX_CUERPO_ERROR = 64L * 1024
    }
}

/**
 * Fábrica del cliente HTTP (ADR-FE-12: Retrofit + OkHttp + Gson). [api] es la instancia única de la app; las pruebas
 * usan [crear] con la URL de MockWebServer y un registrador propio.
 */
object ClienteApi {

    /**
     * Sesión de las rutas protegidas (FE-1.2). `MyApp.onCreate` la asigna una vez, antes de que nadie use [api]; [api]
     * la lee al crearse. Sin vigilante, [api] envía las rutas protegidas sin `Authorization`.
     */
    @Volatile
    var vigilante: VigilanteSesion? = null

    /** Cliente de la app contra [ApiConfig.BASE_URL]; registra en `AppLog` con el tag `Api`. */
    val api: CampusApi by lazy {
        crear(registrar = { AppLog.i(TAG, it) }, vigilante = vigilante)
    }

    /**
     * Con [vigilante], las rutas protegidas pasan por [SesionInterceptor] (y [token] no se usa); sin él, por
     * [AutenticacionInterceptor] con [token]. Orden: sesión o autenticación primero, después [RequestIdInterceptor].
     */
    fun okHttp(
        token: () -> String? = { null },
        registrar: (String) -> Unit,
        vigilante: VigilanteSesion? = null,
    ): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(ApiConfig.TIMEOUT_CONEXION_S, TimeUnit.SECONDS)
        .readTimeout(ApiConfig.TIMEOUT_LECTURA_S, TimeUnit.SECONDS)
        .writeTimeout(ApiConfig.TIMEOUT_ESCRITURA_S, TimeUnit.SECONDS)
        .addInterceptor(if (vigilante != null) SesionInterceptor(vigilante) else AutenticacionInterceptor(token))
        .addInterceptor(RequestIdInterceptor(registrar))
        .build()

    /** [urlBase] con o sin barra final (Retrofit la exige: se añade aquí). */
    fun crear(
        urlBase: String = ApiConfig.BASE_URL,
        token: () -> String? = { null },
        registrar: (String) -> Unit,
        vigilante: VigilanteSesion? = null,
    ): CampusApi = Retrofit.Builder()
        .baseUrl(urlBase.trimEnd('/') + "/")
        .client(okHttp(token, registrar, vigilante))
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(CampusApi::class.java)
}
