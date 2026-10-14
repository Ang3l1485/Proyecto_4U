package com.example.myapplication.camera

import android.graphics.BitmapFactory
import java.io.File

/*
 * Control de calidad de las fotos ANTES de enviarlas al backend
 * (ver ARCHITECTURE.md §9: "las capturas deben tener control de calidad").
 */

private const val OSCURIDAD_MIN = 40.0   // luminancia media mínima (0-255)
private const val NITIDEZ_MIN = 30.0     // varianza mínima del laplaciano

/** Resultado de evaluar una foto. */
enum class Calidad { OK, OSCURA, BORROSA }

/**
 * Evalúa si una foto es utilizable.
 *
 * 1. Se decodifica reducida (1/8) para que sea rápido.
 * 2. Se pasa a escala de grises; si la luminancia media es baja -> [Calidad.OSCURA].
 * 3. Se calcula la varianza del laplaciano (medida clásica de nitidez):
 *    bordes marcados = varianza alta; imagen movida/desenfocada = varianza baja -> [Calidad.BORROSA].
 *
 * Es una función BLOQUEANTE: llamarla desde un dispatcher de fondo (p. ej. Dispatchers.Default).
 * Si el archivo no se puede decodificar se asume [Calidad.OK] (no bloqueamos al usuario por eso).
 */
fun evaluarCalidad(archivo: File): Calidad {
    val opciones = BitmapFactory.Options().apply { inSampleSize = 8 }
    val bmp = BitmapFactory.decodeFile(archivo.path, opciones) ?: return Calidad.OK
    val w = bmp.width
    val h = bmp.height
    val px = IntArray(w * h)
    bmp.getPixels(px, 0, w, 0, 0, w, h)
    bmp.recycle()

    // Escala de grises (pesos ITU-R BT.601).
    val g = IntArray(px.size) {
        val p = px[it]
        (0.299 * ((p shr 16) and 255) + 0.587 * ((p shr 8) and 255) + 0.114 * (p and 255)).toInt()
    }
    if (g.average() < OSCURIDAD_MIN) return Calidad.OSCURA
    if (w < 3 || h < 3) return Calidad.OK

    // Laplaciano de 4 vecinos: L = 4·centro − (izq + der + arriba + abajo).
    var suma = 0.0
    var suma2 = 0.0
    var n = 0
    for (y in 1 until h - 1) {
        for (x in 1 until w - 1) {
            val i = y * w + x
            val l = (4 * g[i] - g[i - 1] - g[i + 1] - g[i - w] - g[i + w]).toDouble()
            suma += l
            suma2 += l * l
            n++
        }
    }
    val varianza = suma2 / n - (suma / n) * (suma / n)
    return if (varianza < NITIDEZ_MIN) Calidad.BORROSA else Calidad.OK
}