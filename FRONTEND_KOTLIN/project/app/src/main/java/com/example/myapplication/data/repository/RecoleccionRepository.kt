package com.example.myapplication.data.repository

import android.content.Context
import com.example.myapplication.data.local.CerrojoRecoleccion
import com.example.myapplication.domain.model.DatosFoto
import com.example.myapplication.domain.model.FotoRecolectada
import com.example.myapplication.domain.model.InicioRecoleccion
import com.example.myapplication.domain.model.ProgresoRecoleccion
import com.example.myapplication.domain.model.PuntoRecorrido
import com.example.myapplication.domain.model.ResumenRecoleccion
import com.example.myapplication.domain.model.VideoEnCurso
import com.example.myapplication.domain.usecase.ModoCaptura
import com.example.myapplication.logs.AppLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Almacenamiento de los videos que se están recolectando (vista 7.4).
 *
 * Todo se guarda **de forma continua** en disco: cada foto queda registrada en el manifest apenas
 * se toma, para no perder datos si la app se cierra.
 *
 * La subida (vista 7.5, FE-2.1) no pasa por aquí: la hace la cola de `data/local/` (`AlmacenRecorridos`,
 * `SubidaRecorrido`, `ColaSubida`) sobre los mismos manifests y con el mismo cerrojo (`CerrojoRecoleccion`).
 */
interface RecoleccionRepository {

    /** Crea el video (carpeta + manifest) y devuelve su id. No sube nada. */
    @Throws(IOException::class)
    suspend fun crearVideo(inicio: InicioRecoleccion): String

    /** Carpeta donde `ImageCapture.tomarFoto` debe escribir (prefijo recomendado: "tmp"). */
    fun carpetaFotos(videoId: String): File

    /**
     * Registra una foto recién escrita por CameraX: la renombra a `NNNN.jpg` y la agrega al
     * manifest con su coordenada y rumbo.
     */
    @Throws(IOException::class)
    suspend fun registrarFoto(videoId: String, archivo: File, datos: DatosFoto): FotoRecolectada

    /**
     * Re-anclaje manual: desplaza las coordenadas de las fotos desde `desdeIndice` (0 = la
     * primera) en adelante. No crea otro video.
     */
    @Throws(IOException::class)
    suspend fun desplazarFotos(videoId: String, desdeIndice: Int, dLat: Double, dLng: Double)

    @Throws(IOException::class)
    suspend fun fotos(videoId: String): List<FotoRecolectada>

    /** Cierra el video y guarda su resumen. */
    @Throws(IOException::class)
    suspend fun finalizar(videoId: String, duracionSegundos: Long, distanciaMetros: Double, pasos: Int): ResumenRecoleccion

    /** Borra el video y todas sus fotos locales. */
    suspend fun descartar(videoId: String)

    /**
     * Id del video `en_curso` más reciente (mayor `rec_NNNN`; la app se cerró a mitad de recorrido); `null` si no
     * hay. Los manifests ilegibles se saltan.
     */
    suspend fun buscarEnCurso(): String?

    /** Lee un video para retomarlo (FE-2.3): nombre, punto de partida, fotos y el último `progress` guardado. */
    @Throws(IOException::class)
    suspend fun leerEnCurso(videoId: String): VideoEnCurso

    /**
     * Guarda el progreso de la grabación en el manifest (clave `progress`, FE-2.3) para poder retomarla. No hace
     * nada si el video ya no está `en_curso` (p. ej. se finalizó mientras esperaba).
     */
    @Throws(IOException::class)
    suspend fun guardarProgreso(videoId: String, progreso: ProgresoRecoleccion)

    /** Fotos guardadas que aún no se han subido (alimenta "fotos pendientes" del panel, 7.2). */
    suspend fun contarPendientes(): Int

    suspend fun marcarSubida(videoId: String, fotoIds: Set<String>)

    /** Bytes libres en el almacenamiento privado (aviso de "almacenamiento bajo"). */
    fun espacioLibreBytes(): Long
}

/**
 * Implementación local. Estructura (compatible con el formato de `assets/videos/`, 7.11, para que
 * Galería y Detalle de video puedan leerla más adelante):
 *
 * ```
 * files/recoleccion/rec_0001/
 * ├── manifest.json
 * └── photos/0001.jpg ...
 * ```
 *
 * Usa el prefijo `rec_` para no chocar con los ids `vid_NNNN` de los datos de prueba. Claves
 * propias del manifest (el lector actual las ignora): `estado` del video (`en_curso` /
 * `finalizado`), `sync` de cada foto (`pendiente` / `subida`), los datos de cierre y, desde FE-2.3,
 * `progress` (lo necesario para retomar tras matar el proceso).
 *
 * Cada operación relee y reescribe el manifest completo (de forma atómica con un archivo
 * temporal). Es suficiente para unos cientos de fotos; si crece, pasar a Room.
 */
class RecoleccionRepositoryLocal(context: Context) : RecoleccionRepository {

    private val filesDir: File = context.applicationContext.filesDir
    private val raiz = File(filesDir, "recoleccion")

    // FE-2.1: el mismo cerrojo que AlmacenRecorridos (7.5 y la cola de subida escriben en los mismos manifests).
    // Antes era un Mutex por instancia: dos instancias (7.4 y 7.3) no se excluían entre sí.
    private val mutex: Mutex = CerrojoRecoleccion.mutex

    override suspend fun crearVideo(inicio: InicioRecoleccion): String = withContext(Dispatchers.IO) {
        mutex.withLock {
            if (!raiz.exists() && !raiz.mkdirs()) throw IOException("No se pudo crear $raiz")
            val siguiente = (raiz.listFiles()
                ?.mapNotNull { it.name.removePrefix(PREFIJO_ID).toIntOrNull() }
                ?.maxOrNull() ?: 0) + 1
            val id = PREFIJO_ID + "%04d".format(siguiente)
            val carpeta = File(raiz, id)
            if (!File(carpeta, "photos").mkdirs()) throw IOException("No se pudo crear $carpeta")

            val manifest = JSONObject()
                .put("video_id", id)
                .put("name", inicio.nombreVideo)
                .put("created_at", iso(System.currentTimeMillis()))
                .put("estado", ESTADO_EN_CURSO)
                .put("start_lat", inicio.lat)
                .put("start_lng", inicio.lng)
                .put("start_heading", inicio.rumbo.toDouble())
                .put("photos", JSONArray())
            escribir(id, manifest)
            AppLog.i(TAG, "Video creado: $id (${inicio.nombreVideo})")
            id
        }
    }

    override fun carpetaFotos(videoId: String): File = File(File(raiz, videoId), "photos")

    override suspend fun registrarFoto(
        videoId: String,
        archivo: File,
        datos: DatosFoto,
    ): FotoRecolectada = withContext(Dispatchers.IO) {
        mutex.withLock {
            val manifest = leer(videoId)
            val fotos = manifest.getJSONArray("photos")
            val siguiente = (0 until fotos.length())
                .mapNotNull { fotos.getJSONObject(it).optString("id").toIntOrNull() }
                .maxOrNull()?.plus(1) ?: 1
            val id = "%04d".format(siguiente)
            val destino = File(carpetaFotos(videoId), "$id.jpg")
            if (!archivo.renameTo(destino)) throw IOException("No se pudo mover ${archivo.name} a ${destino.name}")

            val obj = JSONObject()
                .put("id", id)
                .put("file", "photos/$id.jpg")
                .put("lat", datos.lat)
                .put("lng", datos.lng)
                .put("captured_at", iso(datos.capturadaEnMs))
                .put("sync", SYNC_PENDIENTE)
            datos.rumbo?.let { obj.put("heading", it.toDouble()) }
            fotos.put(obj)
            escribir(videoId, manifest)

            FotoRecolectada(
                id = id,
                videoId = videoId,
                rutaArchivo = destino.absolutePath,
                lat = datos.lat,
                lng = datos.lng,
                rumbo = datos.rumbo,
                capturadaEnMs = datos.capturadaEnMs,
            )
        }
    }

    override suspend fun desplazarFotos(
        videoId: String,
        desdeIndice: Int,
        dLat: Double,
        dLng: Double,
    ) = withContext(Dispatchers.IO) {
        mutex.withLock {
            val manifest = leer(videoId)
            val fotos = manifest.getJSONArray("photos")
            for (i in desdeIndice.coerceAtLeast(0) until fotos.length()) {
                val f = fotos.getJSONObject(i)
                f.put("lat", f.getDouble("lat") + dLat)
                f.put("lng", f.getDouble("lng") + dLng)
            }
            escribir(videoId, manifest)
            AppLog.i(TAG, "Re-anclaje en $videoId: ${fotos.length() - desdeIndice.coerceAtLeast(0)} foto(s) corregida(s)")
        }
    }

    override suspend fun fotos(videoId: String): List<FotoRecolectada> = withContext(Dispatchers.IO) {
        mutex.withLock { leerFotos(videoId, leer(videoId)) }
    }

    override suspend fun finalizar(
        videoId: String,
        duracionSegundos: Long,
        distanciaMetros: Double,
        pasos: Int,
    ): ResumenRecoleccion = withContext(Dispatchers.IO) {
        mutex.withLock {
            val manifest = leer(videoId)
            manifest.put("estado", ESTADO_FINALIZADO)
                .put("ended_at", iso(System.currentTimeMillis()))
                .put("duration_s", duracionSegundos)
                .put("distance_m", distanciaMetros)
                .put("steps", pasos)
            escribir(videoId, manifest)
            ResumenRecoleccion(
                videoId = videoId,
                nombre = manifest.optString("name", videoId),
                duracionSegundos = duracionSegundos,
                distanciaMetros = distanciaMetros,
                pasos = pasos,
                totalFotos = manifest.getJSONArray("photos").length(),
            )
        }
    }

    override suspend fun descartar(videoId: String) {
        withContext(Dispatchers.IO) {
            mutex.withLock {
                File(raiz, videoId).deleteRecursively()
                AppLog.i(TAG, "Video descartado: $videoId")
            }
        }
    }

    override suspend fun buscarEnCurso(): String? = withContext(Dispatchers.IO) {
        mutex.withLock {
            raiz.listFiles()
                ?.filter { it.isDirectory }
                ?.sortedByDescending { it.name }
                ?.firstOrNull { dir ->
                    runCatching { leer(dir.name).optString("estado") == ESTADO_EN_CURSO }.getOrDefault(false)
                }
                ?.name
        }
    }

    override suspend fun leerEnCurso(videoId: String): VideoEnCurso = withContext(Dispatchers.IO) {
        mutex.withLock {
            val manifest = leer(videoId)
            try {
                VideoEnCurso(
                    videoId = videoId,
                    nombre = manifest.optString("name").ifBlank { videoId },
                    inicioLat = manifest.getDouble("start_lat"),
                    inicioLng = manifest.getDouble("start_lng"),
                    inicioRumbo = manifest.optDouble("start_heading", 0.0).toFloat(),
                    fotos = leerFotos(videoId, manifest),
                    progreso = manifest.optJSONObject("progress")?.let { progresoDesdeJson(it) },
                )
            } catch (e: org.json.JSONException) {
                throw IOException("Manifest incompleto en $videoId", e)
            }
        }
    }

    override suspend fun guardarProgreso(videoId: String, progreso: ProgresoRecoleccion) {
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val manifest = leer(videoId)
                if (manifest.optString("estado") == ESTADO_EN_CURSO) {
                    manifest.put("progress", progresoAJson(progreso))
                    escribir(videoId, manifest)
                }
            }
        }
    }

    /** Regla de ARCHITECTURE §5.10 (FE-2.1): `sync = pendiente` en los manifests con `estado = finalizado`. */
    override suspend fun contarPendientes(): Int = withContext(Dispatchers.IO) {
        mutex.withLock {
            raiz.listFiles()?.filter { it.isDirectory }?.sumOf { dir ->
                runCatching {
                    val manifest = leer(dir.name)
                    if (manifest.optString("estado") != ESTADO_FINALIZADO) return@runCatching 0
                    val fotos = manifest.getJSONArray("photos")
                    (0 until fotos.length()).count { fotos.getJSONObject(it).optString("sync") == SYNC_PENDIENTE }
                }.getOrDefault(0)
            } ?: 0
        }
    }

    override suspend fun marcarSubida(videoId: String, fotoIds: Set<String>) {
        withContext(Dispatchers.IO) {
            mutex.withLock {
                val manifest = leer(videoId)
                val fotos = manifest.getJSONArray("photos")
                for (i in 0 until fotos.length()) {
                    val f = fotos.getJSONObject(i)
                    if (f.getString("id") in fotoIds) f.put("sync", SYNC_SUBIDA)
                }
                escribir(videoId, manifest)
            }
        }
    }

    override fun espacioLibreBytes(): Long = filesDir.usableSpace

    // ---- Manifest ---------------------------------------------------------------------------

    private fun archivoManifest(videoId: String) = File(File(raiz, videoId), "manifest.json")

    private fun leer(videoId: String): JSONObject {
        val f = archivoManifest(videoId)
        if (!f.exists()) throw IOException("No existe el manifest de $videoId")
        return try {
            JSONObject(f.readText())
        } catch (e: org.json.JSONException) {
            throw IOException("Manifest dañado en $videoId", e)
        }
    }

    /** Escritura atómica: se escribe en un temporal y se renombra, para no dejar el manifest a medias. */
    private fun escribir(videoId: String, manifest: JSONObject) {
        val destino = archivoManifest(videoId)
        val tmp = File(destino.parentFile, "manifest.json.tmp")
        tmp.writeText(manifest.toString())
        if (!tmp.renameTo(destino)) {
            destino.delete()
            if (!tmp.renameTo(destino)) throw IOException("No se pudo guardar el manifest de $videoId")
        }
    }

    private fun leerFotos(videoId: String, manifest: JSONObject): List<FotoRecolectada> {
        val fotos = manifest.getJSONArray("photos")
        return (0 until fotos.length()).map { i ->
            val f = fotos.getJSONObject(i)
            FotoRecolectada(
                id = f.getString("id"),
                videoId = videoId,
                rutaArchivo = File(File(raiz, videoId), f.getString("file")).absolutePath,
                lat = f.getDouble("lat"),
                lng = f.getDouble("lng"),
                rumbo = if (f.has("heading")) f.getDouble("heading").toFloat() else null,
                capturadaEnMs = parsearIso(f.optString("captured_at")),
                pendienteSubida = f.optString("sync") != SYNC_SUBIDA,
            )
        }
    }

    // ---- Progreso (clave `progress`, FE-2.3; formato en ARCHITECTURE §5.6) -------------------

    private fun progresoAJson(p: ProgresoRecoleccion): JSONObject {
        val modo = when (val m = p.modo) {
            is ModoCaptura.PorDistancia -> JSONObject().put("type", MODO_DISTANCIA).put("value", m.metros)
            is ModoCaptura.PorTiempo -> JSONObject().put("type", MODO_TIEMPO).put("value", m.segundos)
        }
        val track = JSONArray().apply { p.trayectoria.forEach { put(JSONArray().put(it.lat).put(it.lng)) } }
        return JSONObject()
            .put("lat", p.lat)
            .put("lng", p.lng)
            .put("heading", p.rumbo.toDouble())
            .put("steps", p.pasos)
            .put("distance_m", p.distanciaMetros)
            .put("duration_s", p.duracionSegundos)
            .put("anchor_distance_m", p.distanciaAnclaM)
            .put("anchor_photo_index", p.indiceAnclaFoto)
            .put("anchor_track_index", p.indiceAnclaTrayectoria)
            .put("track", track)
            .put("mode", modo)
            .put("saved_at", iso(p.guardadoEnMs))
    }

    /** `null` si falta algo obligatorio: se retoma como un video sin progreso. */
    private fun progresoDesdeJson(o: JSONObject): ProgresoRecoleccion? = runCatching {
        val track = o.optJSONArray("track") ?: JSONArray()
        val trayectoria = (0 until track.length()).map { i ->
            val punto = track.getJSONArray(i)
            PuntoRecorrido(punto.getDouble(0), punto.getDouble(1))
        }
        val modoJson = o.optJSONObject("mode")
        val modo = if (modoJson == null) {
            ModoCaptura.POR_DEFECTO
        } else {
            when (modoJson.optString("type")) {
                MODO_DISTANCIA -> ModoCaptura.PorDistancia(modoJson.getDouble("value"))
                MODO_TIEMPO -> ModoCaptura.PorTiempo(modoJson.getInt("value"))
                else -> ModoCaptura.POR_DEFECTO
            }
        }
        ProgresoRecoleccion(
            lat = o.getDouble("lat"),
            lng = o.getDouble("lng"),
            rumbo = o.optDouble("heading", 0.0).toFloat(),
            pasos = o.optInt("steps", 0),
            distanciaMetros = o.optDouble("distance_m", 0.0),
            duracionSegundos = o.optLong("duration_s", 0),
            distanciaAnclaM = o.optDouble("anchor_distance_m", 0.0),
            indiceAnclaFoto = o.optInt("anchor_photo_index", 0),
            indiceAnclaTrayectoria = o.optInt("anchor_track_index", 0),
            trayectoria = trayectoria,
            modo = modo,
            guardadoEnMs = parsearIso(o.optString("saved_at")),
        )
    }.onFailure { AppLog.w(TAG, "progress ilegible: se retoma sin él", it) }.getOrNull()

    // ---- Fechas (ISO-8601, el formato que 11.6 pide definir) -------------------------------

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).format(Date(ms))

    private fun parsearIso(texto: String): Long =
        runCatching { SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US).parse(texto)?.time }
            .getOrNull() ?: 0L

    private companion object {
        const val TAG = "RecoleccionRepo"
        const val PREFIJO_ID = "rec_"
        const val ESTADO_EN_CURSO = "en_curso"
        const val ESTADO_FINALIZADO = "finalizado"
        const val SYNC_PENDIENTE = "pendiente"
        const val SYNC_SUBIDA = "subida"
        const val MODO_DISTANCIA = "distance"
        const val MODO_TIEMPO = "time"
    }
}