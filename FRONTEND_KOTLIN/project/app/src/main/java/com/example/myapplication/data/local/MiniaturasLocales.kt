package com.example.myapplication.data.local

import android.content.Context
import java.io.File

/**
 * Miniaturas de las fotos de un recorrido del teléfono para el `WebView` de 7.14 (FE-4.1; hallazgo de FE-2.1: salían
 * vacías). Las páginas de `assets/` no pueden cargar `file:///data/…` (`WebView` tiene `allowFileAccess = false` desde la
 * API 30), así que la foto se pide como `https://miniaturas.local/<rec_NNNN>/photos/NNNN.jpg` ([url]) y la intercepta
 * `MapaWebView(recursos = …)` con [archivo]: una copia de como mucho [LADO_PX] px en `cacheDir/miniaturas/<rec>/`
 * (re-codificada con el [preparador], que aplica la orientación EXIF como la subida), generada la primera vez y
 * reutilizada mientras no cambie el original. Nunca sale de esa carpeta: [ruta] solo acepta un id y un archivo con los
 * caracteres de [PATRON_VIDEO] y [PATRON_ARCHIVO] (sin `..` ni barras de más).
 */
class MiniaturasLocales(
    private val raizRecorridos: File,
    private val cache: File,
    private val preparador: PreparadorFoto,
) {

    /** El archivo de la miniatura de [url] (generada si hace falta), o `null` si la URL no es una miniatura válida o la
     *  foto no existe o no se puede leer. Bloquea: llamarlo fuera del hilo principal (el `WebView` lo hace). */
    @Synchronized
    fun archivo(url: String): File? {
        val (videoId, archivo) = ruta(url) ?: return null
        val original = File(File(raizRecorridos, videoId), archivo)
        if (!original.isFile) return null
        val destino = File(File(cache, videoId), archivo.substringAfterLast('/'))
        if (destino.isFile && destino.length() > 0 && destino.lastModified() >= original.lastModified()) return destino
        return try {
            preparador.preparar(original, destino)
            destino
        } catch (_: Exception) {
            destino.delete()
            null
        }
    }

    companion object {
        const val HOST = "miniaturas.local"
        const val LADO_PX = 240
        private val PATRON_VIDEO = Regex("^[A-Za-z0-9_-]{1,64}$")
        private val PATRON_ARCHIVO = Regex("^photos/[A-Za-z0-9_-]{1,64}\\.(jpg|jpeg|png)$")

        /** Límites de la copia: lado ≤ 240 px, ≤ 120 KB (calidades 80 → 60; si no cabe, lado ×3/4 hasta 120 px). */
        val LIMITES = LimitesRecodificacion(LADO_PX, 120_000L, listOf(80, 70, 60), 120)

        /** URL que el `WebView` pide para la foto [archivo] (`photos/0001.jpg`, la del manifest) del recorrido [videoId]. */
        fun url(videoId: String, archivo: String): String = "https://$HOST/$videoId/$archivo"

        /** `(videoId, archivo)` de una URL de [url], o `null` si no es nuestra o no cumple los patrones. */
        fun ruta(url: String): Pair<String, String>? {
            val prefijo = "https://$HOST/"
            if (!url.startsWith(prefijo)) return null
            val resto = url.removePrefix(prefijo).substringBefore('?').substringBefore('#')
            val videoId = resto.substringBefore('/')
            val archivo = resto.substringAfter('/', missingDelimiterValue = "")
            if (!PATRON_VIDEO.matches(videoId) || !PATRON_ARCHIVO.matches(archivo)) return null
            return videoId to archivo
        }

        /** La de la app: `files/recoleccion` y `cacheDir/miniaturas`, con `MotorImagenAndroid`. */
        fun deLaApp(appContext: Context): MiniaturasLocales = MiniaturasLocales(
            raizRecorridos = File(appContext.filesDir, "recoleccion"),
            cache = File(appContext.cacheDir, "miniaturas"),
            preparador = Recodificador(MotorImagenAndroid(), LIMITES),
        )
    }
}
