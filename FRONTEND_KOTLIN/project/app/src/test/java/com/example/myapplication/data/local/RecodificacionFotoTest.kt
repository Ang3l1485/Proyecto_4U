package com.example.myapplication.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * FE-2.1, criterio C3 (ARCHITECTURE §5.10): ninguna foto que se sube pasa de 1600 px de lado mayor ni de 4 194 304
 * bytes. Prueba la lógica pura (`PlanRecodificacion`) y el bucle de `Recodificador` con un motor de imágenes falso (el
 * real, `MotorImagenAndroid`, usa `android.graphics` y no corre en la JVM).
 */
class RecodificacionFotoTest {

    @get:Rule
    val tmp = TemporaryFolder()

    /** Imagen en memoria del motor falso. */
    private data class Img(val ancho: Int, val alto: Int)

    /**
     * Motor falso: [original] son las dimensiones del archivo (sin orientar); [bytesPorPixel] da, por calidad, cuántos
     * bytes ocupa cada píxel del JPEG final. Cuenta cargas y liberaciones.
     */
    private class MotorFalso(
        val original: Dimensiones?,
        val orientacionExif: Int = 1,
        val bytesPorPixel: (calidad: Int) -> Double = { 0.3 },
        val decodifica: Boolean = true,
    ) : MotorImagen<Img> {
        val calidades = mutableListOf<Int>()
        var cargadas = 0
        var liberadas = 0
        val muestreos = mutableListOf<Int>()

        override fun medir(original: File) = this.original
        override fun orientacion(original: File) = orientacionExif
        override fun cargar(original: File, muestreo: Int): Img? {
            if (!decodifica) return null
            muestreos += muestreo
            cargadas++
            val d = this.original!!
            return Img(d.ancho / muestreo, d.alto / muestreo)
        }

        override fun transformar(imagen: Img, orientacion: Int, destino: Dimensiones): Img {
            cargadas++
            return Img(destino.ancho, destino.alto)
        }

        override fun dimensiones(imagen: Img) = Dimensiones(imagen.ancho, imagen.alto)
        override fun comprimir(imagen: Img, calidad: Int, archivo: File): Long {
            calidades += calidad
            val bytes = (imagen.ancho.toLong() * imagen.alto * bytesPorPixel(calidad)).toLong().coerceAtLeast(1)
            archivo.writeBytes(ByteArray(minOf(bytes, 64L).toInt()))
            return bytes
        }

        override fun liberar(imagen: Img) {
            liberadas++
        }
    }

    private fun preparar(motor: MotorFalso): Pair<FotoPreparada, File> {
        val original = File.createTempFile("original", ".jpg", tmp.root)
        val destino = File(tmp.root, "subida/0001.jpg")
        return Recodificador(motor).preparar(original, destino) to destino
    }

    // ---- PlanRecodificacion -----------------------------------------------------------------------------------

    @Test
    fun destino_llevaElLadoMayorA1600SinAmpliar() {
        assertEquals(Dimensiones(1600, 1200), PlanRecodificacion.destino(Dimensiones(4000, 3000), 1600))
        assertEquals(Dimensiones(1200, 1600), PlanRecodificacion.destino(Dimensiones(3000, 4000), 1600))
        assertEquals(Dimensiones(1600, 1200), PlanRecodificacion.destino(Dimensiones(4032, 3024), 1600))
        assertEquals(Dimensiones(1600, 900), PlanRecodificacion.destino(Dimensiones(4000, 2250), 1600))
        assertEquals(Dimensiones(1200, 900), PlanRecodificacion.destino(Dimensiones(1200, 900), 1600))
        assertEquals(Dimensiones(1600, 1600), PlanRecodificacion.destino(Dimensiones(1600, 1600), 1600))
        assertEquals(Dimensiones(1600, 1), PlanRecodificacion.destino(Dimensiones(20000, 2), 1600)) // mínimo 1 px
    }

    @Test
    fun muestreo_esLaMayorPotenciaDe2QueNoBajaDel1600() {
        assertEquals(2, PlanRecodificacion.muestreo(Dimensiones(4000, 3000), 1600)) // 2000 ≥ 1600 > 1000
        assertEquals(1, PlanRecodificacion.muestreo(Dimensiones(3000, 2000), 1600)) // 1500 < 1600
        assertEquals(4, PlanRecodificacion.muestreo(Dimensiones(8000, 6000), 1600))
        assertEquals(1, PlanRecodificacion.muestreo(Dimensiones(1200, 900), 1600))
    }

    @Test
    fun orientada_5a8IntercambiaAnchoYAlto() {
        val d = Dimensiones(4000, 3000)
        for (o in listOf(1, 2, 3, 4)) assertEquals(d, PlanRecodificacion.orientada(d, o))
        for (o in listOf(5, 6, 7, 8)) assertEquals(Dimensiones(3000, 4000), PlanRecodificacion.orientada(d, o))
    }

    // ---- Recodificador ----------------------------------------------------------------------------------------

    @Test
    fun preparar_12MP_da1600x1200ConCalidad90() {
        val motor = MotorFalso(Dimensiones(4000, 3000))
        val (p, destino) = preparar(motor)
        assertEquals(FotoPreparada((1600L * 1200 * 0.3).toLong(), 1600, 1200), p)
        assertEquals(listOf(90), motor.calidades)
        assertEquals(listOf(2), motor.muestreos)
        assertTrue(destino.isFile)
    }

    @Test
    fun preparar_orientacionExif6_daRetrato1200x1600() {
        val (p, _) = preparar(MotorFalso(Dimensiones(4000, 3000), orientacionExif = 6))
        assertEquals(1200, p.ancho)
        assertEquals(1600, p.alto)
    }

    @Test
    fun preparar_fotoPequena_noSeAmplia() {
        val (p, _) = preparar(MotorFalso(Dimensiones(1024, 768)))
        assertEquals(1024, p.ancho)
        assertEquals(768, p.alto)
    }

    @Test
    fun preparar_siNoCabe_bajaLaCalidadHastaQueQuepa() {
        // 1600×1200 = 1 920 000 px: con 2,5 B/px (calidad ≥ 80) pasa de 4 MB; con 2,0 B/px (75) son 3 840 000 B.
        val motor = MotorFalso(Dimensiones(4000, 3000), bytesPorPixel = { q -> if (q >= 80) 2.5 else 2.0 })
        val (p, _) = preparar(motor)
        assertEquals(listOf(90, 85, 80, 75), motor.calidades)
        assertEquals(3_840_000L, p.bytes)
        assertTrue(p.bytes <= LimitesSubida.BYTES_MAX)
    }

    @Test
    fun preparar_siNiConCalidad50Cabe_reduceElLado() {
        // A 1600×1200 nunca cabe (3 B/px = 5,76 MB); a 1200×900 (1 080 000 px) sí: 3,24 MB.
        val motor = MotorFalso(Dimensiones(4000, 3000), bytesPorPixel = { 3.0 })
        val (p, _) = preparar(motor)
        assertEquals(1200, p.ancho)
        assertEquals(900, p.alto)
        assertEquals(LimitesSubida.CALIDADES.size + 1, motor.calidades.size) // 7 a 1600 px y la primera a 1200
        assertEquals(motor.cargadas, motor.liberadas) // ninguna imagen sin liberar
    }

    @Test
    fun preparar_ilegible_lanzaFotoIlegible() {
        assertThrows(FotoIlegibleException::class.java) { preparar(MotorFalso(null)) }
        assertThrows(FotoIlegibleException::class.java) {
            preparar(MotorFalso(Dimensiones(4000, 3000), decodifica = false))
        }
    }

    @Test
    fun preparar_imposibleDeComprimir_lanzaYBorraLaCopia() {
        val motor = MotorFalso(Dimensiones(4000, 3000), bytesPorPixel = { 100.0 })
        val original = tmp.newFile("o.jpg")
        val destino = File(tmp.root, "subida/0001.jpg")
        assertThrows(FotoIlegibleException::class.java) { Recodificador(motor).preparar(original, destino) }
        assertFalse(destino.exists())
        assertEquals(motor.cargadas, motor.liberadas)
    }

    @Test
    fun preparar_barrido_nuncaPasaDe1600NiDe4MB() {
        val tamanos = listOf(320 to 240, 1600 to 1200, 1601 to 1, 3264 to 2448, 4000 to 3000, 4032 to 3024, 4624 to 3472, 8000 to 6000, 9248 to 6936)
        for ((w, h) in tamanos) for (o in 1..8) for (bpp in listOf(0.2, 1.5, 2.3)) {
            val motor = MotorFalso(Dimensiones(w, h), orientacionExif = o, bytesPorPixel = { q -> bpp * q / 90.0 })
            val (p, _) = preparar(motor)
            assertTrue("$w×$h o=$o: ${p.ancho}×${p.alto}", maxOf(p.ancho, p.alto) <= LimitesSubida.LADO_MAX_PX)
            assertTrue("$w×$h o=$o: ${p.bytes} B", p.bytes <= LimitesSubida.BYTES_MAX)
        }
    }

    // ---- límites de la localización (FE-3.2) ------------------------------------------------------------------

    @Test
    fun localizacion_12MP_da1024x768ConCalidad85() {
        val motor = MotorFalso(Dimensiones(4000, 3000))
        val original = File.createTempFile("original", ".jpg", tmp.root)
        val destino = File(tmp.root, "escaneo/envio_1.jpg")
        val p = Recodificador(motor, LimitesRecodificacion.LOCALIZACION).preparar(original, destino)
        assertEquals(FotoPreparada((1024L * 768 * 0.3).toLong(), 1024, 768), p)
        assertEquals(listOf(85), motor.calidades)
        assertEquals(listOf(2), motor.muestreos) // 4000 / 2 = 2000 ≥ 1024 > 1000
        assertTrue(destino.isFile)
    }

    @Test
    fun localizacion_barrido_nuncaPasaDe1024NiDe1_5MB() {
        val tamanos = listOf(640 to 480, 1024 to 768, 3264 to 2448, 4000 to 3000, 8000 to 6000)
        for ((w, h) in tamanos) for (o in listOf(1, 6)) for (bpp in listOf(0.3, 1.8, 2.5)) {
            val motor = MotorFalso(Dimensiones(w, h), orientacionExif = o, bytesPorPixel = { q -> bpp * q / 85.0 })
            val original = File.createTempFile("original", ".jpg", tmp.root)
            val p = Recodificador(motor, LimitesRecodificacion.LOCALIZACION)
                .preparar(original, File.createTempFile("envio", ".jpg", tmp.root))
            assertTrue("$w×$h o=$o: ${p.ancho}×${p.alto}", maxOf(p.ancho, p.alto) <= 1024)
            assertTrue("$w×$h o=$o: ${p.bytes} B", p.bytes <= 1_572_864L)
        }
        assertEquals(LimitesRecodificacion.SUBIDA.ladoMaxPx, LimitesSubida.LADO_MAX_PX) // la subida no cambia
    }

    // ---- rumbo del contrato -----------------------------------------------------------------------------------

    @Test
    fun rumboContrato_normalizaA0_360ConUnDecimal() {
        assertEquals(0.0, SubidaRecorrido.rumboContrato(359.99), 0.0) // 360,0 tras redondear → 0
        assertEquals(0.0, SubidaRecorrido.rumboContrato(360.0), 0.0)
        assertEquals(350.0, SubidaRecorrido.rumboContrato(-10.0), 0.0)
        assertEquals(90.0, SubidaRecorrido.rumboContrato(90.04), 0.0)
        assertEquals(37.5, SubidaRecorrido.rumboContrato(37.5), 0.0)
        assertEquals(359.9, SubidaRecorrido.rumboContrato(359.94), 1e-9)
    }
}
