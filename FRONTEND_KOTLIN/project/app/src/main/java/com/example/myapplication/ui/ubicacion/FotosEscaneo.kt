package com.example.myapplication.ui.ubicacion

import com.example.myapplication.data.repository.FotoEscaneo
import java.io.File

/**
 * Las fotos de **un** escaneo 360° y su carpeta (`files/camera/photos/<yyyy-MM-dd_HH-mm-ss>/`, la crea la pantalla con
 * `crearCarpetaEscaneo`). Decide qué se borra (FE-3.2, decisión abierta 12: `CONSERVAR_FOTOS = false`). Sin Android:
 * la prueba `FotosEscaneoTest`.
 *
 * - [abrir]: empieza un escaneo en una carpeta (cierra el anterior).
 * - [aceptar]: una foto que cuenta, con su rumbo verdadero (o `null`).
 * - [descartar]: una foto que llegó fuera de tiempo (fase distinta de `ESCANEANDO`, otra carpeta o ya cerrada): con
 *   [conservar] en `false` se borra al momento, y su carpeta también si quedó vacía y no es la actual (la captura de
 *   `tomarFoto` vuelve a crear la carpeta con `mkdirs`).
 * - [cerrar]: fin del escaneo (respuesta o error del backend, cancelar, repetir, `onCleared`): con [conservar] en
 *   `false` borra la carpeta **entera** (originales `escaneo_<n>.jpg` y copias `envio_<i>.jpg` de la re-codificación) y
 *   devuelve cuántos archivos había. Idempotente.
 *
 * [conservar] en `true` (solo para depurar) no borra nada.
 */
internal class FotosEscaneo(private val conservar: Boolean) {

    /** Carpeta del escaneo abierto, o `null`. */
    var carpeta: File? = null
        private set

    private val aceptadas = mutableListOf<FotoEscaneo>()

    /** Las fotos aceptadas, en orden de captura. */
    val fotos: List<FotoEscaneo> get() = aceptadas.toList()

    val cantidad: Int get() = aceptadas.size

    fun abrir(nueva: File) {
        cerrar()
        nueva.mkdirs() // por si `cerrar` borró una carpeta con el mismo nombre (dos escaneos en el mismo segundo)
        carpeta = nueva
    }

    /** ¿[archivo] es de la carpeta abierta? (Una foto tardía del escaneo anterior no lo es.) */
    fun esDeLaCarpeta(archivo: File): Boolean = carpeta != null && archivo.parentFile == carpeta

    fun aceptar(archivo: File, rumboGrados: Double?) {
        aceptadas += FotoEscaneo(archivo, rumboGrados)
    }

    fun descartar(archivo: File) {
        if (conservar) return
        archivo.delete()
        val padre = archivo.parentFile ?: return
        if (padre != carpeta && padre.listFiles().isNullOrEmpty()) padre.delete()
    }

    fun cerrar(): Int {
        aceptadas.clear()
        val c = carpeta ?: return 0
        carpeta = null
        if (conservar) return 0
        val archivos = c.walkTopDown().count { it.isFile }
        c.deleteRecursively()
        return archivos
    }
}
