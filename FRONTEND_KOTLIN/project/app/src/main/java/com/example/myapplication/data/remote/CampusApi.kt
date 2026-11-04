package com.example.myapplication.data.remote

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Rutas de la API del backend (contrato: `BACKEND_FASTAPI/docs/ARCHITECTURE.md` §5). La URL base ya termina en
 * `/v1/`, así que las rutas van **sin barra inicial** (`"health"`, no `"/health"`): con barra, Retrofit descartaría el
 * `/v1`. Todas devuelven `Response<T>` y se llaman con [llamar], que aplica el mapeo de errores de §5.10.
 *
 * Cada lote añade aquí sus rutas (places, alerts, admin…).
 */
interface CampusApi {

    /** `GET /v1/health` (backend §5.3). Indicador de conexión de Inicio. */
    @GET("health")
    suspend fun salud(): Response<SaludDto>

    /** `POST /v1/auth/login` (backend §5.3; FE-1.2). Ruta pública: no lleva `Authorization`. */
    @POST("auth/login")
    suspend fun login(@Body cuerpo: LoginPeticionDto): Response<LoginRespuestaDto>

    /**
     * `GET /v1/places` (backend §5.3; FE-3.1). Ruta pública (sin `Authorization`). `lat` y `lng` van juntos o ninguno:
     * con posición el backend da `distancia_m` y ordena por ella; sin ella, `distancia_m` es `null` y ordena por nombre.
     * Retrofit omite los parámetros `null` de la URL.
     */
    @GET("places")
    suspend fun lugares(
        @Query("lat") lat: Double? = null,
        @Query("lng") lng: Double? = null,
        @Query("categoria") categoria: String? = null,
    ): Response<ListaLugaresDto>

    /** `POST /v1/collect/videos` (backend §5.4; FE-2.1): `201` nuevo, `200` si ya existía ese `ref_cliente`. */
    @POST("collect/videos")
    suspend fun crearVideo(@Body cuerpo: VideoCrearDto): Response<VideoResumenDto>

    /** `POST /v1/collect/videos/{id}/images` (backend §5.4; FE-2.1): registra hasta 50 fotos y da sus URLs `PUT`. */
    @POST("collect/videos/{id}/images")
    suspend fun registrarImagenes(
        @Path("id") videoId: String,
        @Body cuerpo: ImagenesRegistrarDto,
    ): Response<ImagenesRegistradasDto>

    /** `POST /v1/collect/videos/{id}/complete` (backend §5.4; FE-2.1). Sin cuerpo (Retrofit envía uno vacío). */
    @POST("collect/videos/{id}/complete")
    suspend fun completarSubida(@Path("id") videoId: String): Response<SubidaCompletadaDto>

    /**
     * `GET /v1/admin/videos/{id}` (backend §5.5; FE-2.1): `VideoResumen` + `fotos` para el progreso por foto. Desde
     * FE-4.1 también el detalle de 7.14 (cada foto con sus URLs GET prefirmadas de 1 h).
     */
    @GET("admin/videos/{id}")
    suspend fun video(@Path("id") videoId: String): Response<VideoResumenDto>

    /**
     * `GET /v1/admin/videos` (backend §5.5; FE-4.1, Lista 7.13): una página de `VideoResumen`, sin los eliminados.
     * `orden` ∈ `fecha`/`nombre`/`fotos`, `dir` ∈ `desc`/`asc`, `por_pagina` ≤ 100. Retrofit omite los `null`.
     */
    @GET("admin/videos")
    suspend fun videos(
        @Query("q") q: String? = null,
        @Query("orden") orden: String? = null,
        @Query("dir") dir: String? = null,
        @Query("pagina") pagina: Int? = null,
        @Query("por_pagina") porPagina: Int? = null,
    ): Response<PaginaVideosDto>

    /** `PATCH /v1/admin/videos/{id}` (FE-4.1, 7.14): renombrar; `200` con el `VideoResumen`; `404`, `422`. */
    @PATCH("admin/videos/{id}")
    suspend fun renombrarVideo(@Path("id") id: String, @Body cuerpo: VideoRenombrarDto): Response<VideoResumenDto>

    /** `DELETE /v1/admin/videos/{id}` (FE-4.1, 7.14): `202` con `VideoBorrado` (repetirlo da lo mismo); `404`. */
    @DELETE("admin/videos/{id}")
    suspend fun borrarVideo(@Path("id") id: String): Response<VideoBorradoDto>

    /**
     * `GET /v1/admin/images` (FE-4.1, Galería 7.11): una página de `ImagenAdmin` con sus URLs GET, por video (el más
     * reciente primero) y `orden`. `estado` ∈ `pendiente_subida`/`subida`/`procesada`/`error`; `calidad` ∈
     * `alta`/`normal`/`baja`; `q` busca en el nombre del video o en las notas.
     */
    @GET("admin/images")
    suspend fun imagenes(
        @Query("video_id") videoId: String? = null,
        @Query("lugar_id") lugarId: String? = null,
        @Query("estado") estado: String? = null,
        @Query("calidad") calidad: String? = null,
        @Query("q") q: String? = null,
        @Query("pagina") pagina: Int? = null,
        @Query("por_pagina") porPagina: Int? = null,
    ): Response<PaginaImagenesDto>

    /** `DELETE /v1/admin/images/{id}` (FE-4.1, 7.14): `204` sin cuerpo ([llamarSinCuerpo]); repetirlo da `404`. */
    @DELETE("admin/images/{id}")
    suspend fun borrarImagen(@Path("id") id: String): Response<Unit>

    /**
     * `POST /v1/admin/images/lote` (FE-4.1, Galería): `{"accion", "ids" (≤ 200), "lugar_id"}`. El cuerpo va como
     * [RequestBody] ya armado (con `"lugar_id": null` explícito para «Sin lugar»), sin pasar por el convertidor.
     */
    @POST("admin/images/lote")
    suspend fun loteImagenes(@Body cuerpo: RequestBody): Response<LoteResultadoDto>

    /**
     * `GET /v1/admin/stats` (backend §5.5, BE-2.3; FE-2.2): totales del dataset, lugares, alertas activas y último
     * video del «Resumen rápido» del Panel. Ruta protegida: va con la sesión del admin (`SesionInterceptor`).
     */
    @GET("admin/stats")
    suspend fun estadisticas(): Response<EstadisticasAdminDto>

    /**
     * `GET /v1/admin/places` (backend §5.5, BE-3.1; FE-3.4): todos los lugares con `descripcion`, `referencias` y
     * `total_fotos`, por nombre. Ruta protegida. La app no usa `q` ni `categoria` (filtra en local), pero Retrofit los
     * omite si son `null`.
     */
    @GET("admin/places")
    suspend fun lugaresAdmin(
        @Query("q") q: String? = null,
        @Query("categoria") categoria: String? = null,
    ): Response<ListaLugaresAdminDto>

    /** `POST /v1/admin/places` (FE-3.4): `201` con el lugar guardado; `409 NOMBRE_DUPLICADO`, `422 VALIDACION`. */
    @POST("admin/places")
    suspend fun crearLugar(@Body cuerpo: LugarEntradaDto): Response<LugarAdminDto>

    /** `PUT /v1/admin/places/{id}` (FE-3.4): reemplaza todos los campos; `200`, `404`, `409`, `422`. */
    @PUT("admin/places/{id}")
    suspend fun reemplazarLugar(@Path("id") id: String, @Body cuerpo: LugarEntradaDto): Response<LugarAdminDto>

    /** `DELETE /v1/admin/places/{id}` (FE-3.4): `204` sin cuerpo (también si no existía): con [llamarSinCuerpo]. */
    @DELETE("admin/places/{id}")
    suspend fun borrarLugar(@Path("id") id: String): Response<Unit>

    /**
     * `GET /v1/alerts` (backend §5.3, BE-3.3; FE-3.3): las alertas activas sin borrar. Ruta **pública** (no pasa por
     * `SesionInterceptor`): la usa 7.4, que no debe arriesgar un `401`. `desde` (diferencias) es para FE-3.6.
     */
    @GET("alerts")
    suspend fun alertasPublicas(@Query("desde") desde: String? = null): Response<AlertasPublicasDto>

    /** `GET /v1/admin/alerts` (backend §5.5, BE-3.3; FE-3.3): las alertas sin borrar, activas o no. Protegida. */
    @GET("admin/alerts")
    suspend fun alertasAdmin(@Query("q") q: String? = null): Response<ListaAlertasAdminDto>

    /** `POST /v1/admin/alerts/sincronizar` (FE-3.3): 1 a 100 cambios, cada uno con su resultado. Protegida. */
    @POST("admin/alerts/sincronizar")
    suspend fun sincronizarAlertas(@Body cuerpo: SincronizarAlertasDto): Response<SincronizarAlertasRespuestaDto>

    /**
     * `POST /v1/localize` (backend §5.3; FE-3.2). Ruta pública (sin `Authorization`). `multipart/form-data`: las partes
     * [fotos] (cada una `fotos`, `image/jpeg`, en el orden de `rumbos`) y la parte [metadatos] (JSON de
     * [MetadatosLocalizacionDto]). Las arma `RemoteLocalizacionRepository`.
     */
    @Multipart
    @POST("localize")
    suspend fun localizar(
        @Part fotos: List<MultipartBody.Part>,
        @Part("metadatos") metadatos: RequestBody,
    ): Response<LocalizacionRespuestaDto>

    /**
     * `POST /v1/localize/frame` (backend §5.3, BE-5.1; FE-5.3). Ruta pública. `multipart/form-data`: **una** parte [foto]
     * (`foto`, `image/jpeg`) y la parte [metadatos] (JSON). Las arma `RemoteFrameRepository`.
     */
    @Multipart
    @POST("localize/frame")
    suspend fun localizarFrame(
        @Part foto: MultipartBody.Part,
        @Part("metadatos") metadatos: RequestBody,
    ): Response<FrameRespuestaDto>
}
