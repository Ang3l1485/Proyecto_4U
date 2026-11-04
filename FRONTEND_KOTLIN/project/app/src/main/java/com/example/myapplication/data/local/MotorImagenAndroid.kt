package com.example.myapplication.data.local

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.io.IOException

/**
 * [MotorImagen] de la app con `BitmapFactory`, `android.media.ExifInterface` (existe desde la API 5; no hace falta la
 * dependencia `androidx.exifinterface`) y `Bitmap.compress(JPEG)`. El JPEG que escribe no lleva EXIF: por eso
 * [transformar] aplica la orientación a los píxeles. Sin pruebas en la JVM (usa `android.graphics`); la lógica que
 * decide tamaños y calidades está en [Recodificador] y [PlanRecodificacion], que sí las tienen.
 */
class MotorImagenAndroid : MotorImagen<Bitmap> {

    override fun medir(original: File): Dimensiones? {
        val opciones = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(original.absolutePath, opciones)
        return if (opciones.outWidth > 0 && opciones.outHeight > 0) Dimensiones(opciones.outWidth, opciones.outHeight) else null
    }

    override fun orientacion(original: File): Int = try {
        ExifInterface(original.absolutePath).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
            .takeIf { it in 1..8 } ?: ExifInterface.ORIENTATION_NORMAL
    } catch (_: IOException) {
        ExifInterface.ORIENTATION_NORMAL
    }

    override fun cargar(original: File, muestreo: Int): Bitmap? =
        BitmapFactory.decodeFile(
            original.absolutePath,
            BitmapFactory.Options().apply {
                inSampleSize = muestreo.coerceAtLeast(1)
                inPreferredConfig = Bitmap.Config.ARGB_8888
            },
        )

    override fun transformar(imagen: Bitmap, orientacion: Int, destino: Dimensiones): Bitmap {
        // Matrices de la orientación EXIF (las mismas que usa Glide en TransformationUtils).
        val m = Matrix()
        when (orientacion) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> m.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 -> m.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> { m.setRotate(180f); m.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_TRANSPOSE -> { m.setRotate(90f); m.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_90 -> m.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> { m.setRotate(-90f); m.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_270 -> m.setRotate(-90f)
        }
        val gira = orientacion in 5..8
        val anchoOrientado = if (gira) imagen.height else imagen.width
        val altoOrientado = if (gira) imagen.width else imagen.height
        m.postScale(destino.ancho.toFloat() / anchoOrientado, destino.alto.toFloat() / altoOrientado)
        // Con la matriz identidad y la imagen inmutable, createBitmap devuelve la misma instancia.
        return Bitmap.createBitmap(imagen, 0, 0, imagen.width, imagen.height, m, true)
    }

    override fun dimensiones(imagen: Bitmap): Dimensiones = Dimensiones(imagen.width, imagen.height)

    override fun comprimir(imagen: Bitmap, calidad: Int, archivo: File): Long {
        FileOutputStream(archivo).use { salida ->
            if (!imagen.compress(Bitmap.CompressFormat.JPEG, calidad, salida)) {
                throw IOException("Bitmap.compress falló con calidad $calidad")
            }
        }
        return archivo.length()
    }

    override fun liberar(imagen: Bitmap) {
        if (!imagen.isRecycled) imagen.recycle()
    }
}
