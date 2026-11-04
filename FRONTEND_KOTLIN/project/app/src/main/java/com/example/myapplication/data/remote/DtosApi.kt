package com.example.myapplication.data.remote

import com.google.gson.annotations.SerializedName

/*
 * DTOs: el JSON del backend tal cual (backend §5.3 y §5.5), con los nombres en snake_case por @SerializedName.
 *
 * Todos los campos son anulables y con valor por defecto: Gson crea los objetos sin pasar por el constructor de
 * Kotlin, así que un campo que falta queda en null aunque el tipo diga lo contrario y los valores por defecto no se
 * aplican. Las comprobaciones (campo obligatorio, enumerado conocido) se hacen en MapeoDatosApi, que lanza
 * RespuestaInesperadaException si algo obligatorio falta.
 */

/** `GET /v1/health`. */
data class SaludDto(
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("version") val version: String? = null,
    @SerializedName("commit") val commit: String? = null,
)

/**
 * Cuerpo de `POST /v1/auth/login` (backend §5.3): `{"identificador", "password"}`. Es lo que envía la app, así que sus
 * campos no son anulables. `password` va sin recortar; `identificador`, como lo recorta `LoginViewModel`.
 */
data class LoginPeticionDto(
    @SerializedName("identificador") val identificador: String,
    @SerializedName("password") val password: String,
) {
    /** Sin la contraseña: este objeto nunca debe acabar en un registro. */
    override fun toString(): String = "LoginPeticionDto(identificador=…, password=…)"
}

/** `usuario` de `POST /v1/auth/login`. */
data class UsuarioDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("correo") val correo: String? = null,
    @SerializedName("rol") val rol: String? = null,
)

/** Respuesta 200 de `POST /v1/auth/login`. */
data class LoginRespuestaDto(
    @SerializedName("token") val token: String? = null,
    @SerializedName("expira_en") val expiraEn: String? = null,
    @SerializedName("usuario") val usuario: UsuarioDto? = null,
)

/** `LugarPublico` de `GET /v1/places`. */
data class LugarPublicoDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("categoria") val categoria: String? = null,
    @SerializedName("lat") val lat: Double? = null,
    @SerializedName("lng") val lng: Double? = null,
    @SerializedName("alias") val alias: List<String>? = null,
    @SerializedName("descripcion") val descripcion: String? = null,
    @SerializedName("referencias") val referencias: String? = null,
    @SerializedName("imagen_url") val imagenUrl: String? = null,
    @SerializedName("distancia_m") val distanciaM: Double? = null,
)

/** Respuesta 200 de `GET /v1/places` (backend §5.3; FE-3.1): `{"items": [LugarPublico…], "total": n}`. */
data class ListaLugaresDto(
    @SerializedName("items") val items: List<LugarPublicoDto>? = null,
    @SerializedName("total") val total: Int? = null,
)

/**
 * `LugarAdmin` de `/v1/admin/places` (backend §5.5; FE-3.4): `LugarPublico` sin `distancia_m`, más `creado_en`,
 * `actualizado_en` y `total_fotos` (las fechas no pasan al modelo).
 */
data class LugarAdminDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("categoria") val categoria: String? = null,
    @SerializedName("lat") val lat: Double? = null,
    @SerializedName("lng") val lng: Double? = null,
    @SerializedName("alias") val alias: List<String>? = null,
    @SerializedName("descripcion") val descripcion: String? = null,
    @SerializedName("referencias") val referencias: String? = null,
    @SerializedName("imagen_url") val imagenUrl: String? = null,
    @SerializedName("creado_en") val creadoEn: String? = null,
    @SerializedName("actualizado_en") val actualizadoEn: String? = null,
    @SerializedName("total_fotos") val totalFotos: Int? = null,
)

/** Respuesta 200 de `GET /v1/admin/places` (backend §5.5; FE-3.4): `{"items": [LugarAdmin…], "total": n}`. */
data class ListaLugaresAdminDto(
    @SerializedName("items") val items: List<LugarAdminDto>? = null,
    @SerializedName("total") val total: Int? = null,
)

/**
 * Cuerpo de `POST /v1/admin/places` y `PUT /v1/admin/places/{id}` (`LugarEntrada`, backend §5.5; FE-3.4). Es lo que
 * envía la app: `categoria` en minúsculas; `alias` siempre (lista, quizá vacía); `descripcion` y `referencias` se
 * omiten si son `null` (Gson no escribe los `null`), que el backend toma como `null`.
 */
data class LugarEntradaDto(
    @SerializedName("nombre") val nombre: String,
    @SerializedName("categoria") val categoria: String,
    @SerializedName("lat") val lat: Double,
    @SerializedName("lng") val lng: Double,
    @SerializedName("alias") val alias: List<String>,
    @SerializedName("descripcion") val descripcion: String? = null,
    @SerializedName("referencias") val referencias: String? = null,
)

/** `Alerta` de `GET /v1/alerts` (y la base de `AlertaAdmin`). */
data class AlertaDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("lat") val lat: Double? = null,
    @SerializedName("lng") val lng: Double? = null,
    @SerializedName("mensaje") val mensaje: String? = null,
    @SerializedName("tipo") val tipo: String? = null,
    @SerializedName("prioridad") val prioridad: String? = null,
    @SerializedName("radio_m") val radioM: Int? = null,
    @SerializedName("activa") val activa: Boolean? = null,
    @SerializedName("vigencia_desde") val vigenciaDesde: String? = null,
    @SerializedName("vigencia_hasta") val vigenciaHasta: String? = null,
    @SerializedName("actualizado_en") val actualizadoEn: String? = null,
    @SerializedName("version") val version: Int? = null,
)

/**
 * `GET /v1/alerts` (backend §5.3, BE-3.3; FE-3.3 la usa en 7.4). `completo` y `eliminadas` los usará la caché de
 * FE-3.6; hoy la app pide siempre la foto completa (sin `desde`).
 */
data class AlertasPublicasDto(
    @SerializedName("generado_en") val generadoEn: String? = null,
    @SerializedName("completo") val completo: Boolean? = null,
    @SerializedName("alertas") val alertas: List<AlertaDto>? = null,
    @SerializedName("eliminadas") val eliminadas: List<String>? = null,
)

/**
 * `GET /v1/admin/alerts` (backend §5.5, BE-3.3; FE-3.3): `{items: [AlertaAdmin…], total}`. `AlertaAdmin` = `Alerta` +
 * `creado_en`, `creado_por`, `actualizado_por`: la app solo lee los campos de [AlertaDto] (Gson ignora los demás).
 */
data class ListaAlertasAdminDto(
    @SerializedName("items") val items: List<AlertaDto>? = null,
    @SerializedName("total") val total: Int? = null,
)

/**
 * Lo que envía la app (FE-3.3): `AlertaEntrada` (backend §5.5) con su `id` (el de `alerta.id` en `sincronizar`). Gson
 * omite los `null`: sin vigencia, el backend la toma como `null`.
 */
data class AlertaEntradaDto(
    @SerializedName("id") val id: String,
    @SerializedName("lat") val lat: Double,
    @SerializedName("lng") val lng: Double,
    @SerializedName("mensaje") val mensaje: String,
    @SerializedName("tipo") val tipo: String,
    @SerializedName("prioridad") val prioridad: String,
    @SerializedName("radio_m") val radioM: Int,
    @SerializedName("activa") val activa: Boolean,
    @SerializedName("vigencia_desde") val vigenciaDesde: String? = null,
    @SerializedName("vigencia_hasta") val vigenciaHasta: String? = null,
)

/** Un cambio de `sincronizar`: `{"op": "upsert", "alerta": {…}}` o `{"op": "eliminar", "id": "…"}` (Gson omite `null`). */
data class CambioAlertaDto(
    @SerializedName("op") val op: String,
    @SerializedName("alerta") val alerta: AlertaEntradaDto? = null,
    @SerializedName("id") val id: String? = null,
)

/** Cuerpo de `POST /v1/admin/alerts/sincronizar` (1 a 100 cambios). */
data class SincronizarAlertasDto(
    @SerializedName("cambios") val cambios: List<CambioAlertaDto>,
)

/** Respuesta `200` de `sincronizar`: un resultado por cambio, en el mismo orden. */
data class SincronizarAlertasRespuestaDto(
    @SerializedName("generado_en") val generadoEn: String? = null,
    @SerializedName("resultados") val resultados: List<ResultadoCambioAlertaDto>? = null,
)

/** `{"id", "op", "estado": "ok" | "error", "codigo": null | "VALIDACION"}`. */
data class ResultadoCambioAlertaDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("op") val op: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("codigo") val codigo: String? = null,
)

/** `ultimo_video` de `GET /v1/admin/stats`. */
data class UltimoVideoDto(
    @SerializedName("numero") val numero: Int? = null,
    @SerializedName("creado_en") val creadoEn: String? = null,
)

/** `GET /v1/admin/stats`. */
data class EstadisticasAdminDto(
    @SerializedName("total_fotos") val totalFotos: Int? = null,
    @SerializedName("total_lugares") val totalLugares: Int? = null,
    @SerializedName("alertas_activas") val alertasActivas: Int? = null,
    @SerializedName("ultimo_video") val ultimoVideo: UltimoVideoDto? = null,
)

/** `{id, nombre}` de `lugar` y `creado_por`. */
data class ReferenciaDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
)

/** `ImagenAdmin` de `GET /v1/admin/videos/{id}` e `/v1/admin/images`. */
data class ImagenAdminDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("video_id") val videoId: String? = null,
    @SerializedName("orden") val orden: Int? = null,
    @SerializedName("lat") val lat: Double? = null,
    @SerializedName("lng") val lng: Double? = null,
    @SerializedName("rumbo") val rumbo: Double? = null,
    @SerializedName("capturada_en") val capturadaEn: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("error") val error: String? = null,
    @SerializedName("calidad") val calidad: String? = null,
    @SerializedName("lugar") val lugar: ReferenciaDto? = null,
    @SerializedName("notas") val notas: String? = null,
    @SerializedName("url") val url: String? = null,
    @SerializedName("url_miniatura") val urlMiniatura: String? = null,
    @SerializedName("url_expira_en") val urlExpiraEn: String? = null,
)

/** `VideoResumen` (y `VideoResumen` + `fotos` de `GET /v1/admin/videos/{id}`). */
data class VideoResumenDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("numero") val numero: Int? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("ref_cliente") val refCliente: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("creado_en") val creadoEn: String? = null,
    @SerializedName("total_fotos") val totalFotos: Int? = null,
    /** FE-2.1: conteo por estado (siempre las cuatro claves en el backend). */
    @SerializedName("conteo") val conteo: ConteoFotosDto? = null,
    @SerializedName("fotos") val fotos: List<ImagenAdminDto>? = null,
    // FE-4.1 (7.13 y 7.3): lo que envió la app al crear el video (backend §5.4); `null` si no lo envió.
    @SerializedName("iniciado_en") val iniciadoEn: String? = null,
    @SerializedName("finalizado_en") val finalizadoEn: String? = null,
    @SerializedName("duracion_s") val duracionS: Long? = null,
    @SerializedName("distancia_m") val distanciaM: Double? = null,
    @SerializedName("pasos") val pasos: Int? = null,
)

// ---- FE-4.1: administración de videos e imágenes (backend §5.5, BE-4.1) ------------------------------------------

/** Página de `GET /v1/admin/videos` (§5.1: `{items, total, pagina, por_pagina}`). */
data class PaginaVideosDto(
    @SerializedName("items") val items: List<VideoResumenDto>? = null,
    @SerializedName("total") val total: Int? = null,
    @SerializedName("pagina") val pagina: Int? = null,
    @SerializedName("por_pagina") val porPagina: Int? = null,
)

/** Página de `GET /v1/admin/images`. */
data class PaginaImagenesDto(
    @SerializedName("items") val items: List<ImagenAdminDto>? = null,
    @SerializedName("total") val total: Int? = null,
    @SerializedName("pagina") val pagina: Int? = null,
    @SerializedName("por_pagina") val porPagina: Int? = null,
)

/** Cuerpo de `PATCH /v1/admin/videos/{id}` (lo envía la app): solo `nombre` (1–40 tras recortar). */
data class VideoRenombrarDto(@SerializedName("nombre") val nombre: String)

/** Respuesta `202` de `DELETE /v1/admin/videos/{id}` (`VideoBorrado`). */
data class VideoBorradoDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("fotos_retiradas") val fotosRetiradas: Int? = null,
    @SerializedName("purga") val purga: String? = null,
)

/** Un elemento de `fallidas` de `POST /v1/admin/images/lote`. */
data class FallidaLoteDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("codigo") val codigo: String? = null,
)

/**
 * Respuesta `200` de `POST /v1/admin/images/lote` (`LoteResultado`). El cuerpo que se **envía** no es un DTO: lo arma
 * `RemoteVideoRepository.cuerpoLote` a mano, porque `reasignar` a «Sin lugar» exige `"lugar_id": null` explícito y el
 * Gson de Retrofit no escribe los `null`.
 */
data class LoteResultadoDto(
    @SerializedName("procesadas") val procesadas: Int? = null,
    @SerializedName("fallidas") val fallidas: List<FallidaLoteDto>? = null,
)

// ---- Recolección (FE-2.1; backend §5.4). Los cuerpos que envía la app no son anulables salvo los opcionales del
// contrato: Gson omite los `null` (el backend los trata como ausentes).

/** `inicio` de `POST /v1/collect/videos`. `rumbo` en [0, 360) o `null`. */
data class InicioRecorridoDto(
    @SerializedName("lat") val lat: Double,
    @SerializedName("lng") val lng: Double,
    @SerializedName("rumbo") val rumbo: Double? = null,
)

/** Cuerpo de `POST /v1/collect/videos`. `ref_cliente` = id local `rec_NNNN` (idempotencia por admin + ref_cliente). */
data class VideoCrearDto(
    @SerializedName("ref_cliente") val refCliente: String,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("iniciado_en") val iniciadoEn: String? = null,
    @SerializedName("finalizado_en") val finalizadoEn: String? = null,
    @SerializedName("duracion_s") val duracionS: Long? = null,
    @SerializedName("distancia_m") val distanciaM: Double? = null,
    @SerializedName("pasos") val pasos: Int? = null,
    @SerializedName("inicio") val inicio: InicioRecorridoDto? = null,
    @SerializedName("total_fotos") val totalFotos: Int = 0,
    @SerializedName("dispositivo") val dispositivo: String? = null,
    @SerializedName("app_version") val appVersion: String? = null,
)

/** Un elemento de `POST /v1/collect/videos/{id}/images`. `bytes` = tamaño del JPEG re-codificado que se sube. */
data class ImagenRegistroDto(
    @SerializedName("orden") val orden: Int,
    @SerializedName("lat") val lat: Double,
    @SerializedName("lng") val lng: Double,
    @SerializedName("rumbo") val rumbo: Double? = null,
    @SerializedName("capturada_en") val capturadaEn: String? = null,
    @SerializedName("bytes") val bytes: Long,
)

/** Cuerpo de `POST /v1/collect/videos/{id}/images` (1 a 50 imágenes). */
data class ImagenesRegistrarDto(@SerializedName("imagenes") val imagenes: List<ImagenRegistroDto>)

/** `subida` de una imagen registrada: URL prefirmada `PUT` y los encabezados que hay que enviar tal cual. */
data class SubidaPutDto(
    @SerializedName("metodo") val metodo: String? = null,
    @SerializedName("url") val url: String? = null,
    @SerializedName("encabezados") val encabezados: Map<String, String>? = null,
    @SerializedName("expira_en") val expiraEn: String? = null,
) {
    /** Sin la URL: lleva la firma y nunca debe acabar en un registro. */
    override fun toString(): String = "SubidaPutDto(metodo=$metodo, url=…, encabezados=$encabezados, expiraEn=$expiraEn)"
}

/** Un elemento de la respuesta de `images`: `subida` es `null` si la foto ya estaba en S3 o ya no está pendiente. */
data class ImagenRegistradaDto(
    @SerializedName("orden") val orden: Int? = null,
    @SerializedName("id") val id: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("subida") val subida: SubidaPutDto? = null,
)

/** Respuesta 200 de `POST /v1/collect/videos/{id}/images` (mismo orden que la petición). */
data class ImagenesRegistradasDto(@SerializedName("imagenes") val imagenes: List<ImagenRegistradaDto>? = null)

/** `conteo` por estado de las fotos de un video (backend §5.4 y §5.5). */
data class ConteoFotosDto(
    @SerializedName("pendiente_subida") val pendienteSubida: Int? = null,
    @SerializedName("subida") val subida: Int? = null,
    @SerializedName("procesada") val procesada: Int? = null,
    @SerializedName("error") val error: Int? = null,
)

/** Respuesta 200 de `POST /v1/collect/videos/{id}/complete`. */
data class SubidaCompletadaDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("estado") val estado: String? = null,
    @SerializedName("conteo") val conteo: ConteoFotosDto? = null,
)

// --- FE-3.2: POST /v1/localize (backend §5.3) ---------------------------------------------------------------------

/**
 * Parte `metadatos` de `POST /v1/localize` (la envía la app; JSON con Gson, que omite los campos `null` pero escribe los
 * `null` dentro de una lista). `rumbos[i]` es el rumbo verdadero [0, 360) de `fotos[i]` o `null`; `origen` = `escaneo`;
 * `app_version` opcional (≤ 40 caracteres).
 */
data class MetadatosLocalizacionDto(
    @SerializedName("rumbos") val rumbos: List<Double?>,
    @SerializedName("origen") val origen: String = "escaneo",
    @SerializedName("app_version") val appVersion: String? = null,
)

/** `posicion` de la respuesta de `POST /v1/localize`. */
data class PosicionDto(
    @SerializedName("lat") val lat: Double? = null,
    @SerializedName("lng") val lng: Double? = null,
    @SerializedName("radio_m") val radioM: Double? = null,
)

/** `lugar_cercano` (sin rumbo). */
data class LugarCercanoDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("distancia_m") val distanciaM: Double? = null,
)

/** Un elemento de `referencias` (`rumbo_grados` absoluto, [0, 360)). */
data class ReferenciaLugarDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("nombre") val nombre: String? = null,
    @SerializedName("distancia_m") val distanciaM: Double? = null,
    @SerializedName("rumbo_grados") val rumboGrados: Double? = null,
)

/** Respuesta 200 de `POST /v1/localize`. */
data class LocalizacionRespuestaDto(
    @SerializedName("resultado") val resultado: String? = null,
    @SerializedName("posicion") val posicion: PosicionDto? = null,
    @SerializedName("confianza") val confianza: Double? = null,
    @SerializedName("nivel") val nivel: String? = null,
    @SerializedName("correccion_rumbo_grados") val correccionRumboGrados: Double? = null,
    @SerializedName("lugar_cercano") val lugarCercano: LugarCercanoDto? = null,
    @SerializedName("referencias") val referencias: List<ReferenciaLugarDto>? = null,
    @SerializedName("fotos_usadas") val fotosUsadas: Int? = null,
    @SerializedName("fotos_con_coincidencia") val fotosConCoincidencia: Int? = null,
    @SerializedName("version_vector") val versionVector: String? = null,
    @SerializedName("latencia_ms") val latenciaMs: Int? = null,
)
