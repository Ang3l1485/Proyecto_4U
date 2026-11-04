package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.CambiosLugares
import com.example.myapplication.data.repository.CambiosVideos
import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.data.repository.ImagenesRepository
import com.example.myapplication.data.repository.PaginaVideos
import com.example.myapplication.data.repository.VideosServidor
import com.example.myapplication.domain.model.AccionLote
import com.example.myapplication.domain.model.FallidaLote
import com.example.myapplication.domain.model.FiltrosImagenes
import com.example.myapplication.domain.model.OrdenVideos
import com.example.myapplication.domain.model.PaginaImagenes
import com.example.myapplication.domain.model.ResultadoLote
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.model.Video
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.Locale

/**
 * Videos e imágenes del backend (FE-4.1; contrato: backend §5.5, BE-2.1 y BE-4.1). Rutas protegidas: con
 * `ClienteApi.api` las lleva `SesionInterceptor` (sin sesión no salen y `AppNav` vuelve a Login).
 *
 * - [paginaVideos] / [todosLosVideos]: `GET /v1/admin/videos` (todas las páginas de [POR_PAGINA], hasta [MAX_PAGINAS]).
 * - [detalle]: `GET /v1/admin/videos/{id}`; `404` (no existe o eliminado) o `422` (id que no es un UUID) → `null`.
 * - [renombrar] (`PATCH`), [eliminar] (`DELETE`, `202`; un `404` cuenta como hecho), [eliminarImagen] (`DELETE`, `204`;
 *   un `404` cuenta como hecho: repetirlo da `404`, backend §4.12) y [lote] (`POST /v1/admin/images/lote` en partes de
 *   [LOTE_MAX]): tras escribir en el backend llaman a [cambios]`.avisar()` (7.11, 7.13 y 7.14 recargan) y a
 *   [cambiosLugares]`.avisar()` (el «N fotos» de 7.6 y el Panel). Un error no avisa.
 * - Errores: los de [llamar] (§5.10). No registra nada más que la línea `Api` de cada petición (sin nombres ni URLs).
 */
class RemoteVideoRepository(
    private val api: CampusApi = ClienteApi.api,
    private val cambios: ContadorCambios = CambiosVideos,
    private val cambiosLugares: ContadorCambios = CambiosLugares,
) : VideosServidor, ImagenesRepository {

    override suspend fun paginaVideos(q: String?, orden: OrdenVideos, pagina: Int, porPagina: Int): PaginaVideos {
        val dto = llamar { api.videos(limpio(q), orden.orden, orden.dir, pagina, porPagina) }
        val items = dto.items ?: throw RespuestaInesperadaException("GET /v1/admin/videos: la respuesta no trae «items»")
        val total = dto.total ?: throw RespuestaInesperadaException("GET /v1/admin/videos: la respuesta no trae «total»")
        return PaginaVideos(items.map(MapeoDatosApi::resumenVideo), total)
    }

    override suspend fun todosLosVideos(q: String?, orden: OrdenVideos): PaginaVideos {
        val todos = mutableListOf<ResumenVideo>()
        var total = 0
        for (pagina in 1..MAX_PAGINAS) {
            val p = paginaVideos(q, orden, pagina, POR_PAGINA)
            total = p.total
            todos += p.items
            if (p.items.isEmpty() || todos.size >= total) break
        }
        // Un video creado entre dos páginas puede repetir uno: el primero gana.
        return PaginaVideos(todos.distinctBy { it.id }, total)
    }

    override suspend fun detalle(id: String): Video? = try {
        MapeoDatosApi.video(llamar { api.video(id) })
    } catch (e: ApiException) {
        if (e.http == 404 || e.http == 422) null else throw e
    }

    override suspend fun renombrar(id: String, nombre: String): ResumenVideo {
        val dto = llamar { api.renombrarVideo(id, VideoRenombrarDto(nombre.trim())) }
        cambios.avisar()
        return MapeoDatosApi.resumenVideo(dto)
    }

    override suspend fun eliminar(id: String): Int {
        val fotos = try {
            llamar { api.borrarVideo(id) }.fotosRetiradas ?: 0
        } catch (e: ApiException) {
            if (e.http != 404) throw e
            0 // ya no existe: para la persona está hecho
        }
        avisar()
        return fotos
    }

    override suspend fun eliminarImagen(id: String) {
        try {
            llamarSinCuerpo { api.borrarImagen(id) }
        } catch (e: ApiException) {
            if (e.http != 404) throw e // repetir un DELETE de imagen da 404: ya está borrada
        }
        avisar()
    }

    override suspend fun imagenes(filtros: FiltrosImagenes, pagina: Int, porPagina: Int): PaginaImagenes {
        val dto = llamar {
            api.imagenes(
                videoId = filtros.videoId,
                lugarId = filtros.lugarId,
                estado = filtros.estado?.let(MapeoDatosApi::claveEstadoFoto),
                calidad = filtros.calidad?.name?.lowercase(Locale.ROOT),
                q = limpio(filtros.q),
                pagina = pagina,
                porPagina = porPagina,
            )
        }
        return MapeoDatosApi.paginaImagenes(dto, pagina, porPagina)
    }

    override suspend fun lote(accion: AccionLote, ids: List<String>, lugarId: String?): ResultadoLote {
        val unicos = ids.distinct()
        var procesadas = 0
        val fallidas = mutableListOf<FallidaLote>()
        var aplicado = false
        try {
            for (parte in unicos.chunked(LOTE_MAX)) {
                val cuerpo = cuerpoLote(accion, parte, lugarId).toRequestBody(TIPO_JSON)
                val r = MapeoDatosApi.resultadoLote(llamar { api.loteImagenes(cuerpo) })
                aplicado = true
                procesadas += r.procesadas
                fallidas += r.fallidas
            }
        } finally {
            if (aplicado) avisar() // lo de las partes anteriores ya quedó aunque una falle
        }
        return ResultadoLote(procesadas, fallidas)
    }

    private fun avisar() {
        cambios.avisar()
        cambiosLugares.avisar()
    }

    companion object {
        /** `por_pagina` con que se piden las listas enteras (el máximo del backend, `PAGINA_MAX`). */
        const val POR_PAGINA = 100

        /** Tope de páginas de [todosLosVideos] (5000 videos). */
        const val MAX_PAGINAS = 50

        /** Ids por petición de lote (`LOTE_IMAGENES_MAX` del backend). */
        const val LOTE_MAX = 200

        private val TIPO_JSON = "application/json; charset=utf-8".toMediaType()

        private fun limpio(q: String?): String? = q?.trim()?.takeIf { it.isNotEmpty() }

        /**
         * Cuerpo de `POST /v1/admin/images/lote`: `{"accion": …, "ids": […]}` y, con `reasignar`, `"lugar_id"` **siempre**
         * (`null` = «Sin lugar»: el backend lo exige explícito). Gson con `serializeNulls` solo para este cuerpo.
         */
        internal fun cuerpoLote(accion: AccionLote, ids: List<String>, lugarId: String?): String {
            val o = JsonObject()
            o.addProperty("accion", accion.clave)
            o.add("ids", JsonArray().apply { ids.forEach { add(it) } })
            if (accion == AccionLote.REASIGNAR) o.add("lugar_id", lugarId?.let { JsonPrimitive(it) } ?: JsonNull.INSTANCE)
            return GsonBuilder().serializeNulls().create().toJson(o)
        }
    }
}
