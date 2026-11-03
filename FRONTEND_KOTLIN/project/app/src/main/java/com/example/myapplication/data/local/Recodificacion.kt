package com.example.myapplication.data.local

import java.io.File
import java.io.IOException
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Límites de lo que se sube (FE-2.1, criterio C3; ARCHITECTURE §5.10 y backend §5.4/§5.10): cada JPEG con el lado
 * mayor ≤ [LADO_MAX_PX] y ≤ [BYTES_MAX] bytes (`REC_MAX_BYTES_FOTO` del backend; el `worker` rechaza lo que pase).
 */
object LimitesSubida {
    const val LADO_MAX_PX = 1600
    const val BYTES_MAX = 4_194_304L

    /** Calidades JPEG que se prueban en orden hasta que el archivo quepa en [BYTES_MAX] (la primera es la de §5.10). */
    val CALIDADES = listOf(90, 85, 80, 75, 70, 60, 50)

    /** Si ni con calidad 50 cabe, se reduce el lado a 3/4 y se repite; nunca por debajo de este lado mayor. */
    const val LADO_MIN_REINTENTO_PX = 640
}

/**
 * Límites de una re-codificación (FE-3.2: el mismo [Recodificador] sirve a la subida y a la localización).
 * [ladoMaxPx]: lado mayor máximo; [bytesMax]: tamaño máximo; [calidades]: calidades JPEG en orden; [ladoMinReintentoPx]:
 * por debajo de este lado ya no se reintenta (×3/4).
 */
data class LimitesRecodificacion(
    val ladoMaxPx: Int,
    val bytesMax: Long,
    val calidades: List<Int>,
    val ladoMinReintentoPx: Int,
) {
    companion object {
        /** Subida de recorridos (FE-2.1): ≤ 1600 px y ≤ 4 MB, calidad 90 bajando ([LimitesSubida]). */
        val SUBIDA = LimitesRecodificacion(
            LimitesSubida.LADO_MAX_PX,
            LimitesSubida.BYTES_MAX,
            LimitesSubida.CALIDADES,
            LimitesSubida.LADO_MIN_REINTENTO_PX,
        )

        /**
         * `POST /v1/localize` (FE-3.2; ARCHITECTURE §5.10 y backend §5.3): lado mayor 1024 px y calidad 85 (bajando si
         * hace falta) para quedar en ≤ 1 572 864 bytes (`LOC_MAX_BYTES_FOTO` del backend).
         */
        val LOCALIZACION = LimitesRecodificacion(
            ladoMaxPx = 1024,
            bytesMax = 1_572_864L,
            calidades = listOf(85, 80, 75, 70, 60, 50),
            ladoMinReintentoPx = 480,
        )
    }
}

/** Ancho y alto en píxeles. */
data class Dimensiones(val ancho: Int, val alto: Int) {
    val ladoMayor: Int get() = max(ancho, alto)
}

/** Cálculos puros de la re-codificación (sin Android): los prueba `RecodificacionFotoTest`. */
object PlanRecodificacion {

    /** La orientación EXIF 5–8 gira 90° o 270°: ancho y alto se intercambian. */
    fun orientada(d: Dimensiones, orientacionExif: Int): Dimensiones =
        if (orientacionExif in 5..8) Dimensiones(d.alto, d.ancho) else d

    /**
     * Tamaño final: el lado mayor pasa a [ladoMax] (nunca se amplía) y el otro se escala igual, redondeado y como
     * mínimo 1 px. 4000×3000 → 1600×1200; 3000×4000 → 1200×1600; 1200×900 no cambia.
     */
    fun destino(d: Dimensiones, ladoMax: Int): Dimensiones {
        if (d.ladoMayor <= ladoMax) return d
        val factor = ladoMax.toDouble() / d.ladoMayor
        return if (d.ancho >= d.alto) {
            Dimensiones(ladoMax, (d.alto * factor).roundToInt().coerceIn(1, ladoMax))
        } else {
            Dimensiones((d.ancho * factor).roundToInt().coerceIn(1, ladoMax), ladoMax)
        }
    }

    /**
     * `inSampleSize` de `BitmapFactory`: la mayor potencia de 2 con la que la imagen decodificada todavía tiene el lado
     * mayor ≥ [ladoMax] (así se escala después hacia abajo, sin perder nitidez y sin decodificar los 12 MP enteros).
     * 4000 px con 1600 → 2 (queda 2000); 1200 px → 1.
     */
    fun muestreo(d: Dimensiones, ladoMax: Int): Int {
        var s = 1
        while (d.ladoMayor / (s * 2) >= ladoMax) s *= 2
        return s
    }
}

/** La foto no se puede leer ni re-codificar (archivo dañado o que no es una imagen). */
class FotoIlegibleException(mensaje: String) : IOException(mensaje)

/** Prepara la copia que se sube de una foto. La implementación de la app es [Recodificador]. */
fun interface PreparadorFoto {
    /** Escribe en [destino] la copia que se sube y devuelve sus bytes y píxeles. [FotoIlegibleException] si no se puede. */
    @Throws(IOException::class)
    fun preparar(original: File, destino: File): FotoPreparada
}

/**
 * Lo que la re-codificación necesita de la plataforma, con la imagen en memoria como [T] (`Bitmap` en la app,
 * `MotorImagenAndroid`; un doble en las pruebas). Todas las llamadas ocurren en el hilo de quien llama a
 * [Recodificador.preparar] (IO).
 */
interface MotorImagen<T : Any> {
    /** Dimensiones sin decodificar los píxeles; `null` si no es una imagen legible. */
    fun medir(original: File): Dimensiones?

    /** Orientación EXIF (1–8; 1 si no hay o no se puede leer). */
    fun orientacion(original: File): Int

    /** Decodifica con `inSampleSize = muestreo`, sin girar; `null` si falla. */
    fun cargar(original: File, muestreo: Int): T?

    /** Aplica la orientación EXIF y escala a [destino] (que ya está orientado). Puede devolver la misma imagen. */
    fun transformar(imagen: T, orientacion: Int, destino: Dimensiones): T

    fun dimensiones(imagen: T): Dimensiones

    /** Escribe un JPEG de calidad [calidad] (sin EXIF) en [archivo] y devuelve los bytes escritos. */
    fun comprimir(imagen: T, calidad: Int, archivo: File): Long

    fun liberar(imagen: T)
}

/**
 * Re-codifica cada foto antes de subirla (ARCHITECTURE §5.10): lado mayor ≤ 1600 px (orientación EXIF aplicada a los
 * píxeles, porque el JPEG nuevo no lleva EXIF) y calidad 90; si pasa de 4 MB, baja la calidad
 * ([LimitesSubida.CALIDADES]) y, como último recurso, el lado (×3/4, hasta [LimitesSubida.LADO_MIN_REINTENTO_PX]).
 * Garantiza el criterio C3: lo que devuelve nunca pasa de 1600 px ni de 4 194 304 bytes.
 *
 * Desde FE-3.2 los límites son un parámetro ([LimitesRecodificacion]; por defecto [LimitesRecodificacion.SUBIDA], así
 * la subida no cambia): la localización usa [LimitesRecodificacion.LOCALIZACION] (1024 px, calidad 85, ≤ 1,5 MB).
 */
class Recodificador<T : Any>(
    private val motor: MotorImagen<T>,
    private val limites: LimitesRecodificacion = LimitesRecodificacion.SUBIDA,
) : PreparadorFoto {

    override fun preparar(original: File, destino: File): FotoPreparada {
        val medida = motor.medir(original) ?: throw FotoIlegibleException("no se pudo leer ${original.name}")
        val orientacion = motor.orientacion(original)
        destino.parentFile?.mkdirs()
        var lado = limites.ladoMaxPx
        while (lado >= limites.ladoMinReintentoPx) {
            val objetivo = PlanRecodificacion.destino(PlanRecodificacion.orientada(medida, orientacion), lado)
            val crudo = motor.cargar(original, PlanRecodificacion.muestreo(medida, lado))
                ?: throw FotoIlegibleException("no se pudo decodificar ${original.name}")
            val final = try {
                motor.transformar(crudo, orientacion, objetivo)
            } catch (e: Throwable) {
                motor.liberar(crudo)
                throw e
            }
            // `transformar` puede devolver la misma imagen: solo se libera la intermedia si es otra.
            if (final !== crudo) motor.liberar(crudo)
            try {
                val d = motor.dimensiones(final)
                if (d.ladoMayor <= limites.ladoMaxPx) {
                    for (calidad in limites.calidades) {
                        val bytes = motor.comprimir(final, calidad, destino)
                        if (bytes in 1..limites.bytesMax) return FotoPreparada(bytes, d.ancho, d.alto)
                    }
                }
            } finally {
                motor.liberar(final)
            }
            lado = lado * 3 / 4
        }
        destino.delete()
        throw FotoIlegibleException("${original.name} no cabe en ${limites.bytesMax} bytes")
    }
}
