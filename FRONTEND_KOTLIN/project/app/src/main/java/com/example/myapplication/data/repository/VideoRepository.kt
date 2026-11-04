package com.example.myapplication.data.repository

import com.example.myapplication.data.local.AlmacenRecorridos
import com.example.myapplication.data.local.EstadoCola
import com.example.myapplication.data.local.EstadoSubida
import com.example.myapplication.data.local.ManifestException
import com.example.myapplication.data.local.MiniaturasLocales
import com.example.myapplication.data.local.RecorridoLocal
import com.example.myapplication.data.local.Subidas
import com.example.myapplication.data.remote.RemoteVideoRepository
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.FiltrosImagenes
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.OrdenVideos
import com.example.myapplication.domain.model.PaginaImagenes
import com.example.myapplication.domain.model.PuntoFoto
import com.example.myapplication.domain.model.PuntosOtros
import com.example.myapplication.domain.model.ResultadoLote
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.model.Video
import com.example.myapplication.domain.usecase.Fechas
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOf
import java.io.File
import java.util.Locale

/**
 * Contrato de los videos para 7.13, 7.14 y 7.3 (FE-4.1, ARCHITECTURE §5.6). Junta los videos del **servidor** con los
 * recorridos de **este teléfono** que el backend aún no conoce. En la app: [VideoRepositoryCompuesto.deLaApp].
 */
interface VideoRepository {
    /**
     * La Lista (7.13): los recorridos del teléfono sin subir ([ListaVideos.locales], filtrados por [q] y ordenados por
     * [orden] aquí) y **todas** las páginas de `GET /v1/admin/videos` con `q` y `orden` del servidor. Si el servidor
     * falla no lanza: deja la excepción en [ListaVideos.errorServidor] (los locales se ven igual, sin red).
     */
    suspend fun listarVideos(q: String? = null, orden: OrdenVideos = OrdenVideos.RECIENTES): ListaVideos

    /** Los recorridos `finalizado` del teléfono **con sus fotos** (también los ya subidos): 7.3, sin red. */
    suspend fun recorridosDelTelefono(): List<Video>

    /** Detalle (7.14): un recorrido del teléfono (su id `rec_NNNN`) o un video del servidor (UUID). `null` = no existe. */
    suspend fun obtenerVideo(id: String): Video?

    /** `PATCH` en el servidor o `name` del manifest en un recorrido local (solo si se puede editar). */
    suspend fun renombrarVideo(videoId: String, nombre: String)

    /** `DELETE` en el servidor (devuelve `fotos_retiradas`) o borra la carpeta de un recorrido local (`null`). */
    suspend fun eliminarVideo(videoId: String): Int?

    /** `DELETE /v1/admin/images/{id}` o descarta la foto del recorrido local. */
    suspend fun eliminarFoto(videoId: String, fotoId: String)

    /** «Mostrar otros videos» (7.14): coordenadas de las fotos de los demás videos, hasta [maximo]. No lanza por el servidor. */
    suspend fun puntosDeOtros(excluir: String, maximo: Int = MAX_PUNTOS_OTROS): PuntosOtros

    /** Emite al suscribirse y cada vez que algo cambió (renombrar, eliminar, un intento de la cola de subida…). */
    fun cambios(): Flow<Int>

    companion object {
        /** Tope de fotos de «Mostrar otros videos» (5 páginas de `GET /v1/admin/images`). */
        const val MAX_PUNTOS_OTROS = 500
    }
}

/** Lo que muestra la Lista (7.13). [totalServidor] = `total` de `GET /v1/admin/videos` (con `q`), o `null` si falló. */
data class ListaVideos(
    val locales: List<ResumenVideo>,
    val servidor: List<ResumenVideo>,
    val totalServidor: Int?,
    val errorServidor: Exception? = null,
)

/** Una página (o todas) de `GET /v1/admin/videos`: filas y `total`. */
data class PaginaVideos(val items: List<ResumenVideo>, val total: Int)

/** Lo que el compuesto necesita del backend (en la app, `RemoteVideoRepository`; en las pruebas, un doble). */
interface VideosServidor {
    suspend fun paginaVideos(q: String?, orden: OrdenVideos, pagina: Int, porPagina: Int): PaginaVideos
    suspend fun todosLosVideos(q: String?, orden: OrdenVideos): PaginaVideos
    suspend fun detalle(id: String): Video?
    suspend fun renombrar(id: String, nombre: String): ResumenVideo
    suspend fun eliminar(id: String): Int
    suspend fun eliminarImagen(id: String)
    suspend fun imagenes(filtros: FiltrosImagenes, pagina: Int, porPagina: Int): PaginaImagenes
}

/** La Galería (7.11): fotos del servidor con paginación y filtros del servidor, y las acciones en lote (FE-4.1). */
interface ImagenesRepository {
    suspend fun imagenes(filtros: FiltrosImagenes, pagina: Int, porPagina: Int): PaginaImagenes

    /** `POST /v1/admin/images/lote`; [lugarId] solo con `REASIGNAR` (`null` = «Sin lugar»). */
    suspend fun lote(accion: AccionLote, ids: List<String>, lugarId: String?): ResultadoLote
}

/** Contador de cambios de videos e imágenes del proceso (FE-4.1, como `CambiosLugares`): lo suben las escrituras. */
object CambiosVideos : ContadorCambios()

/** No se puede editar un recorrido local (se está subiendo o el backend ya lo conoce). El mensaje se muestra tal cual. */
class RecorridoNoEditableException(mensaje: String) : IllegalStateException(mensaje)

/**
 * [VideoRepository] de la app (FE-4.1): el [servidor] más los recorridos del [almacen] (`files/recoleccion/`).
 *
 * - **Un recorrido sale una sola vez** (decisión del usuario del 2026-10-27): en la Lista solo salen como locales los
 *   `finalizado` **sin** `remote_video_id`; uno con `remote_video_id` lo representa el video del servidor (con sus
 *   datos), esté subido o a medias. Los `en_curso` no salen (se retoman en 7.4). Regla en [MezclaVideos].
 * - Un id es local si su carpeta existe en el [almacen] con un `manifest.json` ([esLocal]); si no, se va al servidor.
 * - Renombrar, eliminar y eliminar una foto de un recorrido local **persisten en disco** (`AlmacenRecorridos.renombrar`,
 *   `descartar`, `descartarFoto`); no se permiten mientras se sube ([subiendo]) ni si el backend ya lo conoce
 *   ([RecorridoNoEditableException], ADR-FE-35). Tras escribir, [cambios]`.avisar()`.
 * - [cambios] = `CambiosVideos` combinado con [cambiosCola] (en la app, cada fin de intento de la cola de subida).
 */
class VideoRepositoryCompuesto(
    private val servidor: VideosServidor,
    private val almacen: AlmacenRecorridos,
    private val estadoCola: () -> EstadoCola = { EstadoCola() },
    private val cambiosCola: Flow<Int> = flowOf(0),
    private val cambiosVideos: ContadorCambios = CambiosVideos,
) : VideoRepository {

    override suspend fun listarVideos(q: String?, orden: OrdenVideos): ListaVideos {
        val locales = MezclaVideos.locales(almacen.listar(), q, orden, ::subiendo)
        return try {
            val p = servidor.todosLosVideos(q, orden)
            ListaVideos(locales, p.items, p.total)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ListaVideos(locales, emptyList(), null, e)
        }
    }

    override suspend fun recorridosDelTelefono(): List<Video> =
        almacen.listar().filter { it.finalizado }.map { MezclaVideos.videoLocal(it, subiendo(it)) }

    override suspend fun obtenerVideo(id: String): Video? {
        val local = leerLocal(id)
        if (local != null) return MezclaVideos.videoLocal(local, subiendo(local))
        if (!MezclaVideos.esUuid(id)) return null
        return servidor.detalle(id)
    }

    override suspend fun renombrarVideo(videoId: String, nombre: String) {
        val local = leerLocal(videoId)
        if (local == null) {
            servidor.renombrar(videoId, nombre)
            return
        }
        exigirEditable(local)
        almacen.renombrar(videoId, nombre)
        cambiosVideos.avisar()
    }

    override suspend fun eliminarVideo(videoId: String): Int? {
        val local = leerLocal(videoId) ?: return servidor.eliminar(videoId)
        exigirEditable(local)
        almacen.descartar(videoId)
        cambiosVideos.avisar()
        return null
    }

    override suspend fun eliminarFoto(videoId: String, fotoId: String) {
        val local = leerLocal(videoId)
        if (local == null) {
            servidor.eliminarImagen(fotoId)
            return
        }
        exigirEditable(local)
        almacen.descartarFoto(videoId, fotoId)
        cambiosVideos.avisar()
    }

    override suspend fun puntosDeOtros(excluir: String, maximo: Int): PuntosOtros {
        val videos = linkedMapOf<String, MutableList<PuntoFoto>>()
        var cuantos = 0
        // Los del teléfono sin subir, del disco (los subidos ya vienen del servidor).
        for (r in almacen.listar()) {
            if (!r.finalizado || r.remoteVideoId != null || r.id == excluir) continue
            videos.getOrPut(r.id) { mutableListOf() } += r.fotos.map { PuntoFoto(it.lat, it.lng) }
            cuantos += r.fotos.size
        }
        var truncado = false
        var aviso: String? = null
        try {
            var pagina = 1
            while (cuantos < maximo) {
                val p = servidor.imagenes(FiltrosImagenes(), pagina, RemoteVideoRepository.POR_PAGINA)
                for (f in p.fotos) {
                    if (f.videoId == excluir) continue
                    if (cuantos >= maximo) {
                        truncado = true
                        break
                    }
                    videos.getOrPut(f.videoId) { mutableListOf() } += PuntoFoto(f.lat, f.lng)
                    cuantos++
                }
                if (p.fotos.isEmpty() || pagina * p.porPagina >= p.total || pagina >= MAX_PAGINAS_OTROS) break
                if (cuantos >= maximo) {
                    truncado = true
                    break
                }
                pagina++
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            aviso = "No se pudieron cargar las fotos de los videos del servidor."
        }
        if (truncado) aviso = "Se muestran las primeras $maximo fotos de otros videos."
        return PuntosOtros(videos, truncado, aviso)
    }

    override fun cambios(): Flow<Int> = combine(cambiosVideos.version, cambiosCola) { a, b -> a * 100_003 + b }

    /** El recorrido local [id], o `null` si no es una carpeta del almacén con manifest (o el manifest está dañado). */
    private suspend fun leerLocal(id: String): RecorridoLocal? {
        if (!MezclaVideos.esIdLocal(id) || !File(almacen.carpeta(id), "manifest.json").isFile) return null
        return try {
            almacen.leer(id)
        } catch (_: ManifestException) {
            null
        }
    }

    private fun subiendo(r: RecorridoLocal): Boolean {
        val cola = estadoCola()
        return r.subida == EstadoSubida.SUBIENDO || (cola.activa && cola.videoId == r.id)
    }

    private fun exigirEditable(r: RecorridoLocal) {
        MezclaVideos.motivoNoEditable(r, subiendo(r))?.let { throw RecorridoNoEditableException(it) }
    }

    companion object {
        /** Tope de páginas de `GET /v1/admin/images` para «Mostrar otros videos» (además de [maximo]). */
        const val MAX_PAGINAS_OTROS = 10

        /** El de la app: `RemoteVideoRepository()` + `Subidas.almacen`, con el estado y los cambios de `Subidas.cola`. */
        fun deLaApp(): VideoRepositoryCompuesto = VideoRepositoryCompuesto(
            servidor = RemoteVideoRepository(),
            almacen = Subidas.almacen,
            estadoCola = { Subidas.cola.estado.value },
            cambiosCola = Subidas.cola.cambiosVideos,
        )
    }
}

/**
 * Reglas puras de la mezcla servidor + teléfono (FE-4.1; `VideoRepositoryCompuestoTest`). Sin Android ni red.
 */
internal object MezclaVideos {

    private val PATRON_ID_LOCAL = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val PATRON_UUID = Regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    /** Un id que puede ser una carpeta de `files/recoleccion/` (sin `/`, `.` ni otros caracteres). */
    fun esIdLocal(id: String): Boolean = PATRON_ID_LOCAL.matches(id)

    fun esUuid(id: String): Boolean = PATRON_UUID.matches(id)

    /**
     * Las filas locales de 7.13: los `finalizado` **sin** `remote_video_id` (los demás los representa el servidor),
     * cuyo nombre contiene [q] sin distinguir mayúsculas (como el `q` del backend), ordenadas como [orden].
     */
    fun locales(
        recorridos: List<RecorridoLocal>,
        q: String?,
        orden: OrdenVideos,
        subiendo: (RecorridoLocal) -> Boolean,
    ): List<ResumenVideo> {
        val texto = q?.trim()?.lowercase(Locale.ROOT).orEmpty()
        val filas = recorridos
            .filter { it.finalizado && it.remoteVideoId == null }
            .filter { texto.isEmpty() || it.nombre.lowercase(Locale.ROOT).contains(texto) }
            .map { r ->
                ResumenVideo(
                    id = r.id,
                    nombre = r.nombre,
                    creadoEn = r.creadoEn,
                    finalizadoEn = r.finalizadoEn,
                    fotos = r.fotos.size,
                    distanciaMetros = r.distanciaMetros,
                    duracionSegundos = r.duracionSegundos,
                    estado = if (subiendo(r)) EstadoVideo.SUBIENDO else EstadoVideo.SIN_SUBIR,
                    local = true,
                )
            }
        return when (orden) {
            OrdenVideos.RECIENTES -> filas.sortedWith(
                compareByDescending<ResumenVideo> { Fechas.aMilis(it.creadoEn) ?: Long.MIN_VALUE }.thenByDescending { it.id },
            )
            OrdenVideos.NOMBRE -> filas.sortedWith(compareBy<ResumenVideo> { it.nombre.lowercase(Locale.ROOT) }.thenBy { it.id })
            OrdenVideos.MAS_FOTOS -> filas.sortedWith(compareByDescending<ResumenVideo> { it.fotos }.thenByDescending { it.id })
        }
    }

    /** Por qué no se puede editar un recorrido local, o `null` si se puede. */
    fun motivoNoEditable(r: RecorridoLocal, subiendo: Boolean): String? = when {
        r.remoteVideoId != null || r.subida == EstadoSubida.COMPLETADA ->
            "Este recorrido ya está en el servidor: ábrelo desde la lista para renombrarlo o eliminarlo."
        subiendo -> "Se está subiendo: espera a que termine (o a que la subida se detenga) para renombrarlo o eliminarlo."
        !r.finalizado -> "La grabación no ha terminado: retómala desde «Recolector de imágenes»."
        else -> null
    }

    /** Un recorrido del teléfono como [Video] de 7.14: miniaturas por `https://miniaturas.local/…`, sin lugar. */
    fun videoLocal(r: RecorridoLocal, subiendo: Boolean): Video {
        val nota = motivoNoEditable(r, subiendo)
        return Video(
            id = r.id,
            nombre = r.nombre,
            creadoEn = r.creadoEn,
            fotos = r.fotos.map { f ->
                Foto(
                    id = f.id,
                    videoId = r.id,
                    videoNombre = r.nombre,
                    urlFoto = MiniaturasLocales.url(r.id, f.archivo),
                    urlMiniatura = MiniaturasLocales.url(r.id, f.archivo),
                    lat = f.lat,
                    lng = f.lng,
                    rumbo = f.rumbo?.toFloat(),
                    capturadaEn = f.capturadaEn,
                    estado = f.estado,
                    orden = f.orden,
                )
            }.sortedBy { it.id },
            local = true,
            editable = nota == null,
            nota = nota,
            finalizadoEn = r.finalizadoEn,
        )
    }
}