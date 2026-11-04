package com.example.myapplication.data.local

import com.example.myapplication.data.remote.ApiException
import com.example.myapplication.data.remote.CampusApi
import com.example.myapplication.data.remote.ConteoFotosDto
import com.example.myapplication.data.remote.FalloApi
import com.example.myapplication.data.remote.ImagenRegistroDto
import com.example.myapplication.data.remote.ImagenesRegistrarDto
import com.example.myapplication.data.remote.InicioRecorridoDto
import com.example.myapplication.data.remote.MapeoDatosApi
import com.example.myapplication.data.remote.RespuestaInesperadaException
import com.example.myapplication.data.remote.VideoCrearDto
import com.example.myapplication.data.remote.llamar
import com.example.myapplication.domain.model.EstadoFoto
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException
import kotlin.math.roundToLong

/** Conteo de fotos por estado que da el backend (`conteo` de `complete` y de `GET /v1/admin/videos/{id}`). */
data class ConteoRemoto(val pendienteSubida: Int, val subida: Int, val procesada: Int, val error: Int) {
    val total: Int get() = pendienteSubida + subida + procesada + error

    companion object {
        fun de(dto: ConteoFotosDto?): ConteoRemoto =
            ConteoRemoto(dto?.pendienteSubida ?: 0, dto?.subida ?: 0, dto?.procesada ?: 0, dto?.error ?: 0)
    }
}

/** En qué va la subida de un recorrido (para la vista 7.5 y el Panel). */
enum class FaseSubida {
    /** Re-codificando las fotos (`hechas` de `total` pendientes). */
    PREPARANDO,

    /** Registrando y subiendo (`hechas` = fotos con `sync = subida`, de `total`). */
    SUBIENDO,

    /** `POST …/complete`. */
    COMPLETANDO,
}

data class ProgresoSubida(val fase: FaseSubida, val hechas: Int, val total: Int)

/** Cómo terminó un intento de subir un recorrido. */
sealed interface ResultadoSubida {
    /** `complete` respondió sin fotos pendientes: `subida_estado = completada`. [conteo] `null` si ya lo estaba. */
    data class Completada(val conteo: ConteoRemoto?) : ResultadoSubida

    /** `complete` respondió con fotos `pendiente_subida` (un `HEAD` de S3 falló): se reintenta más tarde. */
    data class Pendiente(val conteo: ConteoRemoto) : ResultadoSubida

    /** Sin sesión, vencida o rechazada (`ApiException(FalloApi.SesionVencida)`): esperar al login, no reintentar. */
    data class EsperandoSesion(val codigo: String) : ResultadoSubida

    /** Red, *timeout*, `5xx`, `429` o un fallo de S3 distinto de `403`: transitorio, se reintenta con espera. */
    data class SinConexion(val motivo: String) : ResultadoSubida

    /** Error que no se arregla reintentando (409, 422, 404, 403 de permisos, manifest dañado…). No se reintenta solo. */
    data class Fallida(val motivo: String) : ResultadoSubida

    /** Fotos que no se pudieron re-codificar (antes de crear el video en el backend): se pueden descartar en 7.5. */
    data class FotosIlegibles(val ids: List<String>) : ResultadoSubida
}

/** Lo que la cola necesita para subir un recorrido (la app usa [SubidaRecorrido]; las pruebas, un doble). */
fun interface EjecutorSubida {
    suspend fun ejecutar(videoId: String, alProgreso: (ProgresoSubida) -> Unit): ResultadoSubida
}

/**
 * Sube un recorrido local (FE-2.1, ARCHITECTURE §5.10; contrato en backend §5.4). Pasos, todos idempotentes:
 * 1. `subida_estado = subiendo`.
 * 2. Re-codifica las fotos pendientes que no tengan su copia en `subida/` ([PreparadorFoto]; anota `upload`). Si una
 *    no se puede leer y el backend aún no conoce el video, vuelve a `sin_subir` y devuelve [ResultadoSubida.FotosIlegibles].
 * 3. Sin `remote_video_id`: `POST /v1/collect/videos` (`ref_cliente` = `rec_NNNN`) y guarda el UUID.
 * 4. Las fotos con `sync = pendiente`, en lotes de [LOTE]: `POST …/images` y `PUT` de cada copia a su URL con
 *    exactamente los encabezados recibidos ([SubidorS3]); cada `2xx` marca `sync = subida` en el momento. Una foto
 *    que llega sin `subida` (el backend ya la tenía) se marca sin `PUT`. Un `403` de S3 = URL vencida: se vuelven a
 *    pedir URLs para esas fotos (hasta [MAX_RONDAS_403] veces).
 * 5. `POST …/complete`: sin pendientes → `subida_estado = completada` y se borra `subida/`.
 *
 * Como cada foto subida queda marcada en disco y el backend es idempotente por (`video_id`, `orden`), repetir tras un
 * corte de red o tras matar el proceso no duplica fotos (criterio C2). No registra URLs prefirmadas ni tokens.
 */
class SubidaRecorrido(
    private val almacen: AlmacenRecorridos,
    private val api: CampusApi,
    private val s3: SubidorS3,
    private val preparador: PreparadorFoto,
    private val dispositivo: String? = null,
    private val appVersion: String? = null,
    private val registrar: (String) -> Unit = {},
    private val reloj: () -> Long = System::currentTimeMillis,
) : EjecutorSubida {

    override suspend fun ejecutar(videoId: String, alProgreso: (ProgresoSubida) -> Unit): ResultadoSubida = try {
        subir(videoId, alProgreso)
    } catch (e: CancellationException) {
        throw e
    } catch (e: ApiException) {
        clasificar(videoId, e)
    } catch (e: ManifestException) {
        registrar("$videoId: manifest ilegible (${e.message})")
        ResultadoSubida.Fallida("No se pudo leer el recorrido en el teléfono: ${e.message}")
    } catch (e: RespuestaInesperadaException) {
        registrar("$videoId: respuesta inesperada del backend (${e.message})")
        ResultadoSubida.Fallida("Respuesta inesperada del servidor: ${e.message}")
    } catch (e: IOException) {
        // SinConexionException (red, timeout, 5xx de API Gateway) y fallos de red del PUT a S3.
        registrar("$videoId: sin conexión (${e.javaClass.simpleName})")
        ResultadoSubida.SinConexion(e.message ?: e.javaClass.simpleName)
    }

    /**
     * Estados por foto de `GET /v1/admin/videos/{id}` (progreso tras subir) escritos en el manifest. Devuelve el
     * `estado` del video y su conteo, o `null` si no hay `remote_video_id`, no hay sesión o no hay red (nunca lanza,
     * salvo cancelación).
     */
    suspend fun actualizarEstados(videoId: String): EstadoRemoto? = try {
        val r = almacen.leer(videoId)
        val remoto = r.remoteVideoId
        if (remoto == null) {
            null
        } else {
            val dto = llamar { api.video(remoto) }
            val porOrden = r.fotos.associateBy { it.orden }
            val estados = dto.fotos.orEmpty().mapNotNull { img ->
                val foto = porOrden[img.orden] ?: return@mapNotNull null
                val estado = MapeoDatosApi.estadoFoto(img.estado) ?: return@mapNotNull null
                foto.id to (estado to img.error)
            }.toMap()
            almacen.guardarEstadosRemotos(videoId, estados)
            EstadoRemoto(dto.estado ?: "", ConteoRemoto.de(dto.conteo))
        }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        registrar("$videoId: no se pudo leer el progreso del backend (${e.javaClass.simpleName})")
        null
    }

    // ---- pasos ------------------------------------------------------------------------------------------------

    private suspend fun subir(videoId: String, alProgreso: (ProgresoSubida) -> Unit): ResultadoSubida {
        val inicial = almacen.leer(videoId)
        if (!inicial.finalizado) return ResultadoSubida.Fallida("$videoId no está finalizado (se retoma en 7.4)")
        if (inicial.subida == EstadoSubida.COMPLETADA) return ResultadoSubida.Completada(null)
        if (inicial.fotos.isEmpty()) return ResultadoSubida.Fallida("$videoId no tiene fotos")
        inicial.fotos.filter { it.orden == null }.takeIf { it.isNotEmpty() }?.let { malas ->
            return ResultadoSubida.Fallida("Fotos con un id que no es un orden 1–${FotoLocal.ORDEN_MAX}: ${malas.joinToString { it.id }}")
        }
        if (inicial.subida != EstadoSubida.SUBIENDO) almacen.cambiarEstadoSubida(videoId, EstadoSubida.SUBIENDO)

        // 2. Re-codificar
        val pendientes = inicial.fotos.filter { !it.subida }
        val ilegibles = mutableListOf<String>()
        for ((i, foto) in pendientes.withIndex()) {
            alProgreso(ProgresoSubida(FaseSubida.PREPARANDO, i, pendientes.size))
            val destino = almacen.archivoPreparado(videoId, foto.id)
            val previa = foto.preparada
            if (previa != null && destino.isFile && destino.length() == previa.bytes) continue
            try {
                val preparada = withContext(Dispatchers.IO) { preparador.preparar(almacen.archivoFoto(videoId, foto), destino) }
                almacen.guardarPreparada(videoId, foto.id, preparada)
            } catch (e: FotoIlegibleException) {
                registrar("$videoId: foto ${foto.id} ilegible (${e.message})")
                ilegibles += foto.id
            } catch (e: ManifestException) {
                throw e
            } catch (e: IOException) {
                // Escribir la copia falló (p. ej. sin espacio): no es la red y reintentar solo no lo arregla.
                registrar("$videoId: no se pudo preparar la foto ${foto.id} (${e.message})")
                return ResultadoSubida.Fallida("No se pudo preparar la foto ${foto.id}: ${e.message}")
            }
        }
        if (ilegibles.isNotEmpty()) {
            if (inicial.remoteVideoId == null) almacen.cambiarEstadoSubida(videoId, EstadoSubida.SIN_SUBIR)
            return ResultadoSubida.FotosIlegibles(ilegibles)
        }

        // 3. Video en el backend
        var recorrido = almacen.leer(videoId)
        val remoto = recorrido.remoteVideoId ?: crearVideo(recorrido).also {
            almacen.guardarVideoRemoto(videoId, it)
            registrar("$videoId: video creado en el backend")
        }

        // 4. Registrar y subir
        val total = recorrido.fotos.size
        var subidas = recorrido.fotos.count { it.subida }
        var faltan = recorrido.fotos.filter { !it.subida }
        alProgreso(ProgresoSubida(FaseSubida.SUBIENDO, subidas, total))
        var rondas403 = 0
        while (faltan.isNotEmpty()) {
            val vencidas = mutableListOf<FotoLocal>()
            for (lote in faltan.chunked(LOTE)) {
                val respuesta = llamar { api.registrarImagenes(remoto, ImagenesRegistrarDto(lote.map(::registro))) }
                val porOrden = respuesta.imagenes.orEmpty().associateBy { it.orden }
                for (foto in lote) {
                    val item = porOrden[foto.orden]
                        ?: throw RespuestaInesperadaException("images no devolvió la foto ${foto.id}")
                    val subida = item.subida
                    if (subida == null) {
                        if (item.estado == ESTADO_PENDIENTE_SUBIDA) {
                            throw RespuestaInesperadaException("la foto ${foto.id} sigue pendiente y no trae URL")
                        }
                        almacen.marcarSubidas(videoId, listOf(foto.id))
                        alProgreso(ProgresoSubida(FaseSubida.SUBIENDO, ++subidas, total))
                        continue
                    }
                    val url = subida.url ?: throw RespuestaInesperadaException("la foto ${foto.id} no trae URL")
                    val archivo = almacen.archivoPreparado(videoId, foto.id)
                    val inicio = reloj()
                    val codigo = withContext(Dispatchers.IO) { s3.subir(url, subida.encabezados.orEmpty(), archivo) }
                    registrar("PUT S3 $videoId/${foto.id} -> $codigo (${reloj() - inicio} ms, ${archivo.length()} B)")
                    when (codigo) {
                        in 200..299 -> {
                            almacen.marcarSubidas(videoId, listOf(foto.id))
                            alProgreso(ProgresoSubida(FaseSubida.SUBIENDO, ++subidas, total))
                        }
                        403 -> vencidas += foto
                        else -> throw IOException("S3 respondió $codigo a la foto ${foto.id}")
                    }
                }
            }
            if (vencidas.isEmpty()) break
            if (++rondas403 > MAX_RONDAS_403) {
                return ResultadoSubida.Fallida("S3 rechazó (403) las URLs de ${vencidas.size} foto(s) tras pedirlas de nuevo")
            }
            registrar("$videoId: ${vencidas.size} URL(s) vencidas (403); se piden de nuevo")
            faltan = vencidas
        }

        // 5. Completar
        alProgreso(ProgresoSubida(FaseSubida.COMPLETANDO, subidas, total))
        val respuesta = llamar { api.completarSubida(remoto) }
        val conteo = ConteoRemoto.de(respuesta.conteo)
        return if (respuesta.estado != ESTADO_VIDEO_PENDIENTE && conteo.pendienteSubida == 0) {
            almacen.cambiarEstadoSubida(videoId, EstadoSubida.COMPLETADA)
            almacen.borrarPreparadas(videoId)
            registrar("$videoId: subida completa (${conteo.total} fotos en el backend, estado ${respuesta.estado})")
            ResultadoSubida.Completada(conteo)
        } else {
            registrar("$videoId: complete con ${conteo.pendienteSubida} foto(s) pendientes; se reintentará")
            ResultadoSubida.Pendiente(conteo)
        }
    }

    private suspend fun crearVideo(r: RecorridoLocal): String {
        val inicio = if (r.inicioLat != null && r.inicioLng != null) {
            InicioRecorridoDto(r.inicioLat, r.inicioLng, r.inicioRumbo?.let(::rumboContrato))
        } else {
            null
        }
        val dto = VideoCrearDto(
            refCliente = r.id,
            nombre = r.nombre.trim().take(AlmacenRecorridos.MAX_NOMBRE).ifBlank { null },
            iniciadoEn = r.creadoEn,
            finalizadoEn = r.finalizadoEn,
            duracionS = r.duracionSegundos?.coerceIn(0, Int.MAX_VALUE.toLong()),
            distanciaM = r.distanciaMetros?.coerceIn(0.0, DISTANCIA_MAX_M),
            pasos = r.pasos?.coerceAtLeast(0),
            inicio = inicio,
            totalFotos = r.fotos.size.coerceAtMost(FotoLocal.ORDEN_MAX),
            dispositivo = dispositivo?.take(200),
            appVersion = appVersion?.take(40),
        )
        val video = llamar { api.crearVideo(dto) }
        return video.id?.takeIf { it.isNotBlank() } ?: throw RespuestaInesperadaException("POST /v1/collect/videos sin id")
    }

    private fun registro(f: FotoLocal): ImagenRegistroDto = ImagenRegistroDto(
        orden = f.orden ?: error("foto ${f.id} sin orden"),
        lat = f.lat,
        lng = f.lng,
        rumbo = f.rumbo?.let(::rumboContrato),
        capturadaEn = f.capturadaEn,
        bytes = f.preparada?.bytes ?: error("foto ${f.id} sin copia preparada"),
    )

    private fun clasificar(videoId: String, e: ApiException): ResultadoSubida {
        val rid = e.requestId?.let { " (X-Request-Id $it)" }.orEmpty()
        registrar("$videoId: ${e.fallo} HTTP ${e.http}$rid")
        return when (val f = e.fallo) {
            is FalloApi.SesionVencida -> ResultadoSubida.EsperandoSesion(f.codigo)
            FalloApi.DemasiadosIntentos -> ResultadoSubida.SinConexion("Demasiadas peticiones (429)")
            is FalloApi.Desconocido -> {
                val http = f.http ?: e.http
                when {
                    http in 500..599 -> ResultadoSubida.SinConexion("El servidor respondió $http ${f.codigo.orEmpty()}".trim())
                    http == 404 -> ResultadoSubida.Fallida("El video ya no existe en el servidor (404)$rid")
                    else -> ResultadoSubida.Fallida("El servidor respondió $http ${f.codigo.orEmpty()}$rid".trim())
                }
            }
            is FalloApi.Validacion -> if (f.codigo == "VIDEO_ELIMINADO") {
                ResultadoSubida.Fallida("El video se eliminó en el servidor (409 VIDEO_ELIMINADO)$rid")
            } else {
                val campos = f.campos.joinToString { "${it.campo}: ${it.motivo}" }
                ResultadoSubida.Fallida("El servidor rechazó los datos (${f.http} ${f.codigo.orEmpty()}) $campos$rid".trim())
            }
            FalloApi.SinPermisos -> ResultadoSubida.Fallida("La cuenta no tiene permisos de administrador (403)")
            else -> ResultadoSubida.Fallida("Error del servidor: ${e.fallo}$rid")
        }
    }

    /** Estado del video en el backend tras [actualizarEstados]. */
    data class EstadoRemoto(val estado: String, val conteo: ConteoRemoto)

    companion object {
        /** `REC_MAX_LOTE` del backend (§5.4/§5.10): más de 50 se rechaza siempre. */
        const val LOTE = 50

        /** Veces que se piden URLs nuevas para las fotos cuyo `PUT` dio `403` antes de rendirse. */
        const val MAX_RONDAS_403 = 2

        private const val DISTANCIA_MAX_M = 1_000_000.0
        private const val ESTADO_PENDIENTE_SUBIDA = "pendiente_subida"
        private const val ESTADO_VIDEO_PENDIENTE = "pendiente"

        /**
         * Rumbo como lo pide el contrato (backend §5.1): [0, 360), redondeado a 0,1° para que el `real` de la base
         * (float32) nunca lo convierta en 360 (trampa de backend §4.5: 359,9999999 → 360,0 viola el `CHECK`).
         */
        fun rumboContrato(grados: Double): Double {
            val normalizado = ((grados % 360.0) + 360.0) % 360.0
            val redondeado = (normalizado * 10).roundToLong() / 10.0
            return if (redondeado >= 360.0) 0.0 else redondeado
        }
    }
}

/** Para mostrar: el estado remoto del video es definitivo (no quedan fotos `pendiente_subida` ni `subida`). */
fun ConteoRemoto.definitivo(): Boolean = pendienteSubida == 0 && subida == 0

/** Para la UI: cuántas fotos de una lista están en cada estado. */
fun List<FotoLocal>.porEstado(): Map<EstadoFoto, Int> = groupingBy { it.estado }.eachCount()
