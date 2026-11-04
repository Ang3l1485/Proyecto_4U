package com.example.myapplication.domain.model

/**
 * Modelos de FE-4.1 (vistas 7.11, 7.13 y 7.14 contra el backend, ARCHITECTURE §5.6). Sin Android: se prueban en la JVM.
 */

/** Estado de un video en la Lista (7.13). Los dos primeros son de un recorrido del teléfono que el backend no conoce. */
enum class EstadoVideo {
    /** Recorrido del teléfono sin subir (`finalizado`, sin `remote_video_id`). */
    SIN_SUBIR,

    /** Recorrido del teléfono que la cola está preparando (aún sin `remote_video_id`). */
    SUBIENDO,

    /** `pendiente` del backend: faltan fotos por subir o la app no llamó a `complete`. */
    SUBIDA_A_MEDIAS,

    /** `procesando` del backend (alguna foto `subida` sin procesar; con `embedding` apagado se queda así). */
    PROCESANDO,

    /** `procesado` del backend (también un video sin fotos). */
    PROCESADO,

    /** `con_errores` del backend. */
    CON_ERRORES,
}

/** Orden de la Lista (7.13): los parámetros `orden` y `dir` de `GET /v1/admin/videos` (backend §5.5). */
enum class OrdenVideos(val orden: String, val dir: String, val etiqueta: String) {
    RECIENTES("fecha", "desc", "Recientes"),
    NOMBRE("nombre", "asc", "Nombre"),
    MAS_FOTOS("fotos", "desc", "Más fotos"),
}

/**
 * Una fila de la Lista (7.13): un `VideoResumen` del backend o un recorrido del teléfono sin subir ([local]).
 * [fotos] = fotos registradas (la suma del `conteo`; en uno local, las del manifest). [distanciaMetros] y
 * [duracionSegundos] son las que midió el PDR (`distancia_m`, `duracion_s`), o `null`.
 */
data class ResumenVideo(
    val id: String,
    val nombre: String,
    val creadoEn: String?,
    val finalizadoEn: String?,
    val fotos: Int,
    val distanciaMetros: Double?,
    val duracionSegundos: Long?,
    val estado: EstadoVideo,
    val local: Boolean = false,
    val numero: Int? = null,
)

/**
 * Filtros de `GET /v1/admin/images` (Galería 7.11): todos opcionales y combinados con Y en el servidor. [q] busca en el
 * nombre del video o en las notas de la foto (sin distinguir mayúsculas; no ignora tildes).
 */
data class FiltrosImagenes(
    val q: String? = null,
    val videoId: String? = null,
    val lugarId: String? = null,
    val estado: EstadoFoto? = null,
    val calidad: CalidadFoto? = null,
)

/** Una página de `GET /v1/admin/images`. [vencenEnMs] = el vencimiento más temprano de sus URLs, o `null`. */
data class PaginaImagenes(
    val fotos: List<Foto>,
    val total: Int,
    val pagina: Int,
    val porPagina: Int,
    val vencenEnMs: Long? = null,
)

/** Acción de `POST /v1/admin/images/lote`. */
enum class AccionLote(val clave: String) {
    ELIMINAR("eliminar"),
    REASIGNAR("reasignar"),
}

/** Un elemento de `fallidas` del lote: `codigo` ∈ `NO_ENCONTRADO`, `VALIDACION`, `ERROR_INTERNO` (backend §5.5). */
data class FallidaLote(val id: String, val codigo: String)

/** Respuesta del lote (sumada si se envió en varias partes de 200). */
data class ResultadoLote(val procesadas: Int, val fallidas: List<FallidaLote>)

/** Coordenada de una foto de otro video («Mostrar otros videos» de 7.14). */
data class PuntoFoto(val lat: Double, val lng: Double)

/**
 * Las fotos de los demás videos para «Mostrar otros videos» (7.14): por video, solo coordenadas. [truncado] si se llegó
 * al tope; [aviso] es lo que se le dice a la persona (tope alcanzado o el servidor no respondió), o `null`.
 */
data class PuntosOtros(
    val videos: Map<String, List<PuntoFoto>>,
    val truncado: Boolean = false,
    val aviso: String? = null,
)
