package com.example.myapplication.data.local

import com.example.myapplication.domain.model.EstadoFoto
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Cerrojo único del proceso para leer y reescribir los `manifest.json` de `files/recoleccion/`. Lo comparten
 * `RecoleccionRepositoryLocal` (7.4) y [AlmacenRecorridos] (7.5 y la cola de subida): así una foto nueva, el progreso
 * de FE-2.3 y una marca de subida nunca se pisan. `Mutex` no es reentrante: no anidar `withLock`.
 */
object CerrojoRecoleccion {
    val mutex = Mutex()
}

/**
 * Regla única de «Fotos pendientes» (7.2, ARCHITECTURE §5.10; lógica pura): las fotos sin `sync = subida`
 * ([RecorridoLocal.fotosPendientes]) de los recorridos `finalizado`. La usan [AlmacenRecorridos.contarFotosPendientes]
 * y el Panel cuando relee los recorridos (FE-2.2).
 */
fun fotosPendientesDe(recorridos: List<RecorridoLocal>): Int =
    recorridos.filter { it.finalizado }.sumOf { it.fotosPendientes }

/**
 * Lo que la vista 7.5, la cola de subida y el `VideoRepository` compuesto hacen sobre `files/recoleccion/` (FE-2.1,
 * ARCHITECTURE §5.6 y §5.10). La **cola** es el propio manifest: `photos[].sync`, `photos[].upload`,
 * `remote_video_id` y `subida_estado`. Cada operación relee y reescribe el manifest completo de forma atómica
 * (temporal `manifest.json.tmp` + renombrar, igual que `RecoleccionRepositoryLocal`) y conserva las claves que no
 * conoce (`progress`, las de 7.4). Sin Android: se prueba en la JVM con una carpeta temporal.
 *
 * @param raiz `files/recoleccion`.
 */
class AlmacenRecorridos(val raiz: File) {

    /** Todos los recorridos legibles (`en_curso` y `finalizado`), por id. Los manifests ilegibles se saltan. */
    suspend fun listar(): List<RecorridoLocal> = conCerrojo {
        carpetas().mapNotNull { dir -> runCatching { leerSinCerrojo(dir.name) }.getOrNull() }
    }

    /** Un recorrido. No existe o está dañado → [ManifestException]. */
    suspend fun leer(videoId: String): RecorridoLocal = conCerrojo { leerSinCerrojo(videoId) }

    /** Los `finalizado` con `subida_estado = subiendo`: lo que la cola retoma al abrir el Panel o 7.5. */
    suspend fun idsEnSubida(): List<String> =
        listar().filter { it.finalizado && it.subida == EstadoSubida.SUBIENDO }.map { it.id }

    /**
     * «Fotos pendientes» del Panel (7.2, ARCHITECTURE §5.10): [fotosPendientesDe] sobre [listar] (las fotos sin
     * `sync = subida` de los recorridos con `estado = finalizado`; los `en_curso` no cuentan, se retoman en 7.4).
     */
    suspend fun contarFotosPendientes(): Int = fotosPendientesDe(listar())

    /**
     * Cambia `name` (recortado, como mucho [MAX_NOMBRE] caracteres). Solo mientras el backend no conoce el video
     * ([RecorridoLocal.editable]): el nombre viaja en `POST /v1/collect/videos`, que es idempotente y no lo actualiza.
     * Devuelve el nombre guardado. En blanco → `IllegalArgumentException`; no editable → `IllegalStateException`.
     */
    suspend fun renombrar(videoId: String, nombre: String): String = modificar(videoId) { json, r ->
        check(r.editable) { "$videoId ya se envió al backend: el nombre no se puede cambiar aquí" }
        val limpio = nombre.trim().take(MAX_NOMBRE)
        require(limpio.isNotEmpty()) { "El nombre no puede quedar vacío" }
        json.addProperty("name", limpio)
        limpio
    }

    /** Quita una foto del manifest y borra su JPG (y su copia re-codificada). Solo si [RecorridoLocal.editable]. */
    suspend fun descartarFoto(videoId: String, fotoId: String) {
        modificar(videoId) { json, r ->
            check(r.editable) { "$videoId ya se envió al backend: sus fotos no se descartan aquí" }
            val fotos = ManifestRecorrido.arregloFotos(json)
            val indice = fotos.indexOfFirst { it.isJsonObject && it.asJsonObject.get("id")?.asString == fotoId }
            require(indice >= 0) { "$videoId no tiene la foto $fotoId" }
            val archivo = fotos[indice].asJsonObject.get("file")?.asString
            fotos.remove(indice)
            archivo?.let { File(carpeta(videoId), it).delete() }
            archivoPreparado(videoId, fotoId).delete()
        }
    }

    /** Borra el recorrido entero (carpeta, fotos y copias). */
    suspend fun descartar(videoId: String) {
        conCerrojo { carpeta(videoId).deleteRecursively() }
    }

    suspend fun cambiarEstadoSubida(videoId: String, estado: EstadoSubida) {
        modificar(videoId) { json, _ -> json.addProperty(ManifestRecorrido.SUBIDA_ESTADO, estado.clave) }
    }

    suspend fun guardarVideoRemoto(videoId: String, remoteId: String) {
        modificar(videoId) { json, _ -> json.addProperty(ManifestRecorrido.VIDEO_REMOTO, remoteId) }
    }

    /** Anota la copia re-codificada (`photos[].upload`). El archivo ya debe estar en [archivoPreparado]. */
    suspend fun guardarPreparada(videoId: String, fotoId: String, preparada: FotoPreparada) {
        modificarFoto(videoId, fotoId) { foto ->
            foto.add(
                ManifestRecorrido.UPLOAD,
                JsonObject().apply {
                    addProperty("bytes", preparada.bytes)
                    addProperty("width", preparada.ancho)
                    addProperty("height", preparada.alto)
                },
            )
        }
    }

    /** `photos[].sync = subida` (su `PUT` respondió 2xx o el backend ya la tenía). */
    suspend fun marcarSubidas(videoId: String, fotoIds: Collection<String>) {
        if (fotoIds.isEmpty()) return
        modificar(videoId) { json, _ ->
            ManifestRecorrido.fotos(json).filter { it.get("id")?.asString in fotoIds }
                .forEach { it.addProperty(ManifestRecorrido.SYNC, ManifestRecorrido.SYNC_SUBIDA) }
        }
    }

    /**
     * Estados que dio `GET /v1/admin/videos/{id}` (por id de foto): escribe `photos[].estado` (`subida`, `procesada`
     * o `error`) y `photos[].error` (motivo, o se quita). `PENDIENTE` no se escribe (lo dice `sync`).
     */
    suspend fun guardarEstadosRemotos(videoId: String, estados: Map<String, Pair<EstadoFoto, String?>>) {
        if (estados.isEmpty()) return
        modificar(videoId) { json, _ ->
            for (foto in ManifestRecorrido.fotos(json)) {
                val (estado, motivo) = estados[foto.get("id")?.asString] ?: continue
                val clave = when (estado) {
                    EstadoFoto.SUBIDA -> "subida"
                    EstadoFoto.PROCESADA -> "procesada"
                    EstadoFoto.ERROR -> "error"
                    EstadoFoto.PENDIENTE -> null
                } ?: continue
                foto.addProperty(ManifestRecorrido.ESTADO, clave)
                if (estado == EstadoFoto.ERROR && motivo != null) foto.addProperty(ManifestRecorrido.ERROR, motivo)
                else foto.remove(ManifestRecorrido.ERROR)
            }
        }
    }

    /** Borra la carpeta `subida/` (copias re-codificadas) al completar; `photos[].upload` queda como registro. */
    suspend fun borrarPreparadas(videoId: String) {
        conCerrojo { File(carpeta(videoId), CARPETA_SUBIDA).deleteRecursively() }
    }

    fun carpeta(videoId: String): File = File(raiz, videoId)

    fun archivoFoto(videoId: String, foto: FotoLocal): File = File(carpeta(videoId), foto.archivo)

    /** Copia re-codificada de una foto: `rec_NNNN/subida/<id>.jpg`. */
    fun archivoPreparado(videoId: String, fotoId: String): File =
        File(File(carpeta(videoId), CARPETA_SUBIDA), "$fotoId.jpg")

    // ---- manifest ----------------------------------------------------------------------------------------------

    private suspend fun <T> conCerrojo(bloque: () -> T): T =
        withContext(Dispatchers.IO) { CerrojoRecoleccion.mutex.withLock { bloque() } }

    private suspend fun <T> modificar(videoId: String, cambio: (JsonObject, RecorridoLocal) -> T): T = conCerrojo {
        val json = leerJson(videoId)
        val resultado = cambio(json, ManifestRecorrido.recorrido(videoId, json))
        escribir(videoId, json)
        resultado
    }

    private suspend fun modificarFoto(videoId: String, fotoId: String, cambio: (JsonObject) -> Unit) {
        modificar(videoId) { json, _ ->
            val foto = ManifestRecorrido.fotos(json).firstOrNull { it.get("id")?.asString == fotoId }
                ?: throw ManifestException("$videoId no tiene la foto $fotoId")
            cambio(foto)
        }
    }

    private fun carpetas(): List<File> =
        raiz.listFiles()?.filter { it.isDirectory && File(it, MANIFEST).isFile }?.sortedBy { it.name }.orEmpty()

    private fun leerSinCerrojo(videoId: String): RecorridoLocal =
        ManifestRecorrido.recorrido(videoId, leerJson(videoId))

    private fun leerJson(videoId: String): JsonObject {
        val archivo = File(carpeta(videoId), MANIFEST)
        if (!archivo.isFile) throw ManifestException("No existe el manifest de $videoId")
        return ManifestRecorrido.parsear(archivo.readText())
    }

    private fun escribir(videoId: String, json: JsonObject) {
        val destino = File(carpeta(videoId), MANIFEST)
        val tmp = File(destino.parentFile, "$MANIFEST.tmp")
        tmp.writeText(ManifestRecorrido.texto(json))
        if (!tmp.renameTo(destino)) {
            destino.delete()
            if (!tmp.renameTo(destino)) throw ManifestException("No se pudo guardar el manifest de $videoId")
        }
    }

    companion object {
        const val MANIFEST = "manifest.json"
        const val CARPETA_SUBIDA = "subida"

        /** Como `MAX_NOMBRE_VIDEO` de 7.3 y el máximo del backend (`nombre` 1–40, §5.4). */
        const val MAX_NOMBRE = 40
    }
}
