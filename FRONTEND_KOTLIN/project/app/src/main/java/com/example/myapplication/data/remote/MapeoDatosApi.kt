package com.example.myapplication.data.remote

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.CalidadFoto
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.DatosLugar
import com.example.myapplication.domain.model.EstadoFoto
import com.example.myapplication.domain.model.EstadoVideo
import com.example.myapplication.domain.model.FallidaLote
import com.example.myapplication.domain.model.Foto
import com.example.myapplication.domain.model.PaginaImagenes
import com.example.myapplication.domain.model.ResultadoLote
import com.example.myapplication.domain.model.ResumenVideo
import com.example.myapplication.domain.model.LugarAdmin
import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.OperacionAlerta
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ReferenciaLugar
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.model.ResumenAdmin
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.domain.model.Video
import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import kotlin.math.roundToInt

/**
 * Mapeo de datos de ARCHITECTURE §5.10 (backend JSON → modelos de la app). Lógica pura, sin Android: se prueba en
 * `MapeoDatosApiTest`. Un campo obligatorio que falta lanza [RespuestaInesperadaException].
 */
object MapeoDatosApi {

    /**
     * Enumerado en minúsculas del backend → enum de Kotlin (`"biblioteca"` → `BIBLIOTECA`). `null` si no existe.
     * Usa `Locale.ROOT`: con el idioma del teléfono en turco, `"biblioteca".uppercase()` daría una `İ`.
     */
    inline fun <reified E : Enum<E>> enumDe(valor: String?): E? {
        if (valor == null) return null
        val nombre = valor.trim().uppercase(Locale.ROOT)
        return enumValues<E>().firstOrNull { it.name == nombre }
    }

    fun usuario(dto: UsuarioDto?): Usuario {
        val u = dto ?: throw RespuestaInesperadaException("login sin usuario")
        return Usuario(
            id = obligatorio(u.id, "usuario.id"),
            nombre = u.nombre ?: "",
            correo = obligatorio(u.correo, "usuario.correo"),
            rol = enumDe<Rol>(u.rol) ?: throw RespuestaInesperadaException("rol desconocido: ${u.rol}"),
        )
    }

    /** `expira_en` del login en milisegundos (FE-1.2 lo guarda con la sesión). */
    fun expiraEnMs(dto: LoginRespuestaDto): Long =
        isoAMilis(dto.expiraEn) ?: throw RespuestaInesperadaException("expira_en ausente o inválido")

    /**
     * Respuesta 200 del login → [Sesion] (FE-1.2). Obligatorios: `token` (no vacío), `expira_en` y lo de [usuario].
     * No filtra por rol: un `user` también recibe su sesión (lo decide `LoginViewModel`).
     */
    fun sesion(dto: LoginRespuestaDto): Sesion = Sesion(
        token = dto.token?.takeIf { it.isNotBlank() } ?: throw RespuestaInesperadaException("login sin token"),
        usuario = usuario(dto.usuario),
        expiraEnMs = expiraEnMs(dto),
    )

    /** `LugarPublico` → `LugarDestino`. `null` si la categoría no la conoce la app (se descarta el lugar). */
    fun lugarDestino(dto: LugarPublicoDto): LugarDestino? {
        val categoria = enumDe<CategoriaLugar>(dto.categoria) ?: return null
        return LugarDestino(
            id = obligatorio(dto.id, "lugar.id"),
            nombre = obligatorio(dto.nombre, "lugar.nombre"),
            categoria = categoria,
            lat = obligatorio(dto.lat, "lugar.lat"),
            lng = obligatorio(dto.lng, "lugar.lng"),
            alias = dto.alias.orEmpty(),
            distanciaMetros = dto.distanciaM?.roundToInt(),
            imagenUrl = dto.imagenUrl,
        )
    }

    /**
     * `LugarAdmin` → [LugarAdmin] (FE-3.4). `null` si la categoría no la conoce la app (se descarta, como en
     * [lugarDestino]). Obligatorios: `id`, `nombre`, `lat`, `lng`; `alias` ausente → `[]`, `total_fotos` ausente → 0.
     * `creado_en` y `actualizado_en` no pasan al modelo.
     */
    fun lugarAdmin(dto: LugarAdminDto): LugarAdmin? {
        val categoria = enumDe<CategoriaLugar>(dto.categoria) ?: return null
        return LugarAdmin(
            lugar = LugarDestino(
                id = obligatorio(dto.id, "lugar.id"),
                nombre = obligatorio(dto.nombre, "lugar.nombre"),
                categoria = categoria,
                lat = obligatorio(dto.lat, "lugar.lat"),
                lng = obligatorio(dto.lng, "lugar.lng"),
                alias = dto.alias.orEmpty(),
                imagenUrl = dto.imagenUrl,
            ),
            descripcion = dto.descripcion,
            referencias = dto.referencias,
            totalFotos = dto.totalFotos ?: 0,
        )
    }

    /** [DatosLugar] → cuerpo `LugarEntrada` (FE-3.4): la categoría en minúsculas (`Locale.ROOT`), el resto tal cual. */
    fun entradaLugar(datos: DatosLugar): LugarEntradaDto = LugarEntradaDto(
        nombre = datos.nombre,
        categoria = datos.categoria.name.lowercase(Locale.ROOT),
        lat = datos.lat,
        lng = datos.lng,
        alias = datos.alias,
        descripcion = datos.descripcion,
        referencias = datos.referencias,
    )

    /** `Alerta` del backend → `Alerta` (`radio_m` → `radio`; `tipo` y `prioridad` quedan como texto). */
    /**
     * `Alerta` (y `AlertaAdmin`) → [Alerta]. FE-3.3: también la vigencia, `version` y `actualizado_en` (fechas UTC con
     * `Z` → milisegundos con [isoAMilis]; otra forma queda `null`).
     */
    fun alerta(dto: AlertaDto): Alerta = Alerta(
        id = obligatorio(dto.id, "alerta.id"),
        lat = obligatorio(dto.lat, "alerta.lat"),
        lng = obligatorio(dto.lng, "alerta.lng"),
        mensaje = obligatorio(dto.mensaje, "alerta.mensaje"),
        tipo = dto.tipo ?: "otro",
        prioridad = dto.prioridad ?: "normal",
        radio = dto.radioM ?: 15,
        activa = dto.activa ?: true,
        vigenciaDesdeMs = isoAMilis(dto.vigenciaDesde),
        vigenciaHastaMs = isoAMilis(dto.vigenciaHasta),
        version = dto.version,
        actualizadoEnMs = isoAMilis(dto.actualizadoEn),
    )

    /** [Alerta] → `AlertaEntrada` con su `id` (FE-3.3). La vigencia, en UTC con `Z` y sin fracciones ([milisAIso]). */
    fun entradaAlerta(a: Alerta): AlertaEntradaDto = AlertaEntradaDto(
        id = a.id,
        lat = a.lat,
        lng = a.lng,
        mensaje = a.mensaje,
        tipo = a.tipo,
        prioridad = a.prioridad,
        radioM = a.radio,
        activa = a.activa,
        vigenciaDesde = a.vigenciaDesdeMs?.let(::milisAIso),
        vigenciaHasta = a.vigenciaHastaMs?.let(::milisAIso),
    )

    /** Un pendiente → un cambio de `sincronizar` (FE-3.3). */
    fun cambioAlerta(op: OperacionAlerta): CambioAlertaDto = when (op) {
        is OperacionAlerta.Upsert -> CambioAlertaDto(op = "upsert", alerta = entradaAlerta(op.alerta))
        is OperacionAlerta.Eliminar -> CambioAlertaDto(op = "eliminar", id = op.id)
    }

    /** Milisegundos → `yyyy-MM-dd'T'HH:mm:ss'Z'` en UTC (descarta los milisegundos: la resolución del backend, §5.1). */
    fun milisAIso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT).apply { timeZone = TimeZone.getTimeZone("UTC") }
            .format(java.util.Date(ms))

    /**
     * `GET /v1/admin/stats` → `ResumenAdmin`. [fotosPendientes] sale de la cola local de subida, no del backend.
     * FE-2.2: el último video es el del backend (`ultimo_video`); si viene, su `numero` es obligatorio y `creado_en`
     * (UTC con `Z`, backend §5.1) pasa a milisegundos con [isoAMilis] (en otro formato queda `null`: el Panel muestra
     * el número sin fecha). `ultimo_video = null` (sin videos) → número y fecha `null` (el Panel muestra «—»).
     */
    fun resumenAdmin(dto: EstadisticasAdminDto, fotosPendientes: Int): ResumenAdmin = ResumenAdmin(
        totalFotos = obligatorio(dto.totalFotos, "total_fotos"),
        totalLugares = obligatorio(dto.totalLugares, "total_lugares"),
        alertasActivas = obligatorio(dto.alertasActivas, "alertas_activas"),
        ultimoVideoNumero = dto.ultimoVideo?.let { obligatorio(it.numero, "ultimo_video.numero") },
        ultimoVideoFecha = isoAMilis(dto.ultimoVideo?.creadoEn),
        fotosPendientes = fotosPendientes,
    )

    /**
     * `estado` de `ImagenAdmin` (backend §5.5) → `EstadoFoto`: `pendiente_subida` → `PENDIENTE` (FE-2.1), `subida`,
     * `procesada` y `error` → el suyo. Cualquier otro valor da `null` ([foto] lo muestra como `SUBIDA`).
     */
    fun estadoFoto(valor: String?): EstadoFoto? = when (valor?.trim()?.lowercase(Locale.ROOT)) {
        "pendiente_subida" -> EstadoFoto.PENDIENTE
        "subida" -> EstadoFoto.SUBIDA
        "procesada" -> EstadoFoto.PROCESADA
        "error" -> EstadoFoto.ERROR
        else -> null
    }

    /**
     * `ImagenAdmin` → `Foto` del video [videoNombre]. `url` `null` (la foto sigue `pendiente_subida`, o S3 sin configurar)
     * queda `""`; sin `url_miniatura` (solo existe para las `procesada`, backend §5.5) la miniatura es la `url` original
     * (FE-4.1). `lugar.id` → `lugarId` y `orden` pasan al modelo desde FE-4.1.
     */
    fun foto(dto: ImagenAdminDto, videoNombre: String): Foto = Foto(
        id = obligatorio(dto.id, "imagen.id"),
        videoId = obligatorio(dto.videoId, "imagen.video_id"),
        videoNombre = videoNombre,
        urlFoto = dto.url ?: "",
        urlMiniatura = dto.urlMiniatura ?: dto.url ?: "",
        lat = obligatorio(dto.lat, "imagen.lat"),
        lng = obligatorio(dto.lng, "imagen.lng"),
        rumbo = dto.rumbo?.toFloat(),
        capturadaEn = dto.capturadaEn,
        lugar = dto.lugar?.nombre,
        estado = estadoFoto(dto.estado) ?: EstadoFoto.SUBIDA,
        calidad = enumDe<CalidadFoto>(dto.calidad) ?: CalidadFoto.NORMAL,
        lugarId = dto.lugar?.id,
        orden = dto.orden,
    )

    /**
     * `VideoResumen` (+ `fotos` si viene del detalle) → `Video`. El `id` es el UUID del backend. Desde FE-4.1 también
     * `finalizado_en` y [Video.urlsVencenEnMs] (el `url_expira_en` más temprano de sus fotos).
     */
    fun video(dto: VideoResumenDto): Video {
        val nombre = dto.nombre ?: ""
        val fotos = dto.fotos.orEmpty().sortedBy { it.orden ?: Int.MAX_VALUE }
        return Video(
            id = obligatorio(dto.id, "video.id"),
            nombre = nombre,
            creadoEn = dto.creadoEn,
            fotos = fotos.map { foto(it, nombre) },
            urlsVencenEnMs = fotos.mapNotNull { isoAMilis(it.urlExpiraEn) }.minOrNull(),
            finalizadoEn = dto.finalizadoEn,
        )
    }

    /**
     * `estado` de `VideoResumen` → [EstadoVideo] (FE-4.1): `pendiente` → `SUBIDA_A_MEDIAS`, `procesando`, `procesado`,
     * `con_errores` → el suyo; otro valor (o ausente) → `PROCESANDO`.
     */
    fun estadoVideo(valor: String?): EstadoVideo = when (valor?.trim()?.lowercase(Locale.ROOT)) {
        "pendiente" -> EstadoVideo.SUBIDA_A_MEDIAS
        "procesado" -> EstadoVideo.PROCESADO
        "con_errores" -> EstadoVideo.CON_ERRORES
        else -> EstadoVideo.PROCESANDO
    }

    /**
     * `VideoResumen` → fila de 7.13 (FE-4.1). Obligatorio: `id`. `fotos` = la suma del `conteo` (las registradas); sin
     * `conteo`, `total_fotos` (el declarado). `distancia_m` y `duracion_s` tal cual (`null` si la app no los envió).
     */
    fun resumenVideo(dto: VideoResumenDto): ResumenVideo {
        val c = dto.conteo
        val registradas = c?.let { (it.pendienteSubida ?: 0) + (it.subida ?: 0) + (it.procesada ?: 0) + (it.error ?: 0) }
        return ResumenVideo(
            id = obligatorio(dto.id, "video.id"),
            nombre = dto.nombre ?: "",
            creadoEn = dto.creadoEn,
            finalizadoEn = dto.finalizadoEn,
            fotos = registradas ?: dto.totalFotos ?: 0,
            distanciaMetros = dto.distanciaM,
            duracionSegundos = dto.duracionS,
            estado = estadoVideo(dto.estado),
            local = false,
            numero = dto.numero,
        )
    }

    /** [EstadoFoto] → el `estado` de `ImagenAdmin` (filtro de `GET /v1/admin/images`). */
    fun claveEstadoFoto(estado: EstadoFoto): String = when (estado) {
        EstadoFoto.PENDIENTE -> "pendiente_subida"
        EstadoFoto.SUBIDA -> "subida"
        EstadoFoto.PROCESADA -> "procesada"
        EstadoFoto.ERROR -> "error"
    }

    /**
     * Página de `GET /v1/admin/images` → [PaginaImagenes] (FE-4.1). `items` y `total` obligatorios; cada foto con
     * `videoNombre = ""` (la imagen no trae el nombre de su video: lo pone la Galería con su lista de videos).
     */
    fun paginaImagenes(dto: PaginaImagenesDto, pagina: Int, porPagina: Int): PaginaImagenes {
        val items = obligatorio(dto.items, "items")
        return PaginaImagenes(
            fotos = items.map { foto(it, videoNombre = "") },
            total = obligatorio(dto.total, "total"),
            pagina = dto.pagina ?: pagina,
            porPagina = dto.porPagina ?: porPagina,
            vencenEnMs = items.mapNotNull { isoAMilis(it.urlExpiraEn) }.minOrNull(),
        )
    }

    /** `LoteResultado` → [ResultadoLote] (FE-4.1). `procesadas` obligatorio; `fallidas` ausente = vacía. */
    fun resultadoLote(dto: LoteResultadoDto): ResultadoLote = ResultadoLote(
        procesadas = obligatorio(dto.procesadas, "procesadas"),
        fallidas = dto.fallidas.orEmpty().map {
            FallidaLote(obligatorio(it.id, "fallidas.id"), it.codigo ?: "ERROR_INTERNO")
        },
    )

    /**
     * Fecha ISO-8601 en UTC del backend (`2026-10-23T15:04:05Z`, backend §5.1) → milisegundos epoch, o `null`.
     * Acepta fracciones de segundo (se descartan) y solo la zona `Z`. Usa `SimpleDateFormat` y no `java.time`
     * porque `minSdk = 24` (java.time llega en la API 26).
     */
    fun isoAMilis(texto: String?): Long? {
        val t = texto?.trim()?.takeIf { it.endsWith("Z") } ?: return null
        val sinZona = t.dropLast(1).substringBefore('.')
        val formato = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
            isLenient = false
        }
        return try {
            formato.parse(sinZona)?.time
        } catch (_: ParseException) {
            null
        }
    }

    /**
     * Respuesta 200 de `POST /v1/localize` (backend §5.3; FE-3.2) → [ResultadoUbicacion]. `resultado = ok` exige
     * `posicion` (`lat`, `lng`, `radio_m`), `confianza` y un `nivel` conocido; cada `lugar_cercano` y `referencias[]`, su
     * `id`, `nombre`, `distancia_m` (y `rumbo_grados`). `sin_coincidencias` solo necesita `fotos_usadas`. Otro
     * `resultado` o algo obligatorio que falta → [RespuestaInesperadaException]. `referencias` ausente = vacía.
     */
    fun resultadoUbicacion(dto: LocalizacionRespuestaDto): ResultadoUbicacion {
        val fotosUsadas = obligatorio(dto.fotosUsadas, "fotos_usadas")
        return when (dto.resultado?.trim()?.lowercase(Locale.ROOT)) {
            "sin_coincidencias" -> ResultadoUbicacion.SinCoincidencias(fotosUsadas)
            "ok" -> {
                val p = obligatorio(dto.posicion, "posicion")
                ResultadoUbicacion.Ubicado(
                    posicion = PosicionEstimada(
                        lat = obligatorio(p.lat, "posicion.lat"),
                        lng = obligatorio(p.lng, "posicion.lng"),
                        radioM = obligatorio(p.radioM, "posicion.radio_m"),
                    ),
                    confianza = obligatorio(dto.confianza, "confianza"),
                    nivel = enumDe<NivelConfianza>(dto.nivel)
                        ?: throw RespuestaInesperadaException("nivel desconocido: ${dto.nivel}"),
                    correccionRumboGrados = dto.correccionRumboGrados,
                    lugarCercano = dto.lugarCercano?.let {
                        LugarCercano(
                            id = obligatorio(it.id, "lugar_cercano.id"),
                            nombre = obligatorio(it.nombre, "lugar_cercano.nombre"),
                            distanciaM = obligatorio(it.distanciaM, "lugar_cercano.distancia_m"),
                        )
                    },
                    referencias = dto.referencias.orEmpty().map {
                        ReferenciaLugar(
                            id = obligatorio(it.id, "referencias.id"),
                            nombre = obligatorio(it.nombre, "referencias.nombre"),
                            distanciaM = obligatorio(it.distanciaM, "referencias.distancia_m"),
                            rumboGrados = obligatorio(it.rumboGrados, "referencias.rumbo_grados"),
                        )
                    },
                    fotosUsadas = fotosUsadas,
                    fotosConCoincidencia = dto.fotosConCoincidencia ?: 0,
                )
            }
            else -> throw RespuestaInesperadaException("resultado desconocido: ${dto.resultado}")
        }
    }

    private fun <T : Any> obligatorio(valor: T?, campo: String): T =
        valor ?: throw RespuestaInesperadaException("falta $campo")
}
