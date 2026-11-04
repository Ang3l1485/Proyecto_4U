package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarCercano
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.PosicionEstimada
import com.example.myapplication.domain.model.ReferenciaLugar
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.model.UbicacionEstimada
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * FE-3.2, apoyo del criterio C1: lo que dice y muestra la vista 6.3 (ARCHITECTURE §5.7). Cuándo `referencias` incluye
 * el lugar más cercano: backend §5.3 (0.12.1).
 */
class DescribirUbicacionTest {

    private val trillizos = ReferenciaLugar("t", "Bloque de los Trillizos", 35.2, 95.0)
    private val cafeteria = ReferenciaLugar("c", "Cafetería Principal", 80.0, 270.0)

    private fun ubicado(
        nivel: NivelConfianza = NivelConfianza.ALTA,
        cercano: LugarCercano? = LugarCercano("b", "Biblioteca Central", 12.4),
        referencias: List<ReferenciaLugar> = listOf(trillizos, cafeteria),
        correccion: Double? = -6.0,
    ) = UbicacionEstimada(
        ResultadoUbicacion.Ubicado(
            posicion = PosicionEstimada(6.2, -75.58, 8.5),
            confianza = 0.78,
            nivel = nivel,
            correccionRumboGrados = correccion,
            lugarCercano = cercano,
            referencias = referencias,
            fotosUsadas = 5,
            fotosConCoincidencia = 4,
        ),
        obtenidaEnMs = 0L,
        rumboAlTerminar = null,
    )

    @Test
    fun direccion_sectoresDe90YBordes() {
        assertEquals(DireccionRelativa.AL_FRENTE, DescribirUbicacion.direccion(0.0, 0.0))
        assertEquals(DireccionRelativa.A_LA_DERECHA, DescribirUbicacion.direccion(90.0, 0.0))
        assertEquals(DireccionRelativa.DETRAS, DescribirUbicacion.direccion(180.0, 0.0))
        assertEquals(DireccionRelativa.A_LA_IZQUIERDA, DescribirUbicacion.direccion(270.0, 0.0))
        assertEquals(DireccionRelativa.AL_FRENTE, DescribirUbicacion.direccion(45.0, 0.0))
        assertEquals(DireccionRelativa.AL_FRENTE, DescribirUbicacion.direccion(315.0, 0.0))
        assertEquals(DireccionRelativa.DETRAS, DescribirUbicacion.direccion(135.0, 0.0))
        assertEquals(DireccionRelativa.DETRAS, DescribirUbicacion.direccion(225.0, 0.0))
        assertEquals(DireccionRelativa.AL_FRENTE, DescribirUbicacion.direccion(10.0, 350.0)) // cruza el norte
        assertEquals(DireccionRelativa.A_LA_IZQUIERDA, DescribirUbicacion.direccion(260.0, 350.0))
    }

    @Test
    fun rumboInicial_puntosCardinales() {
        assertEquals(0.0, DescribirUbicacion.rumboInicial(6.2, -75.58, 6.201, -75.58), 0.05)
        assertEquals(90.0, DescribirUbicacion.rumboInicial(6.2, -75.58, 6.2, -75.579), 0.05)
        assertEquals(180.0, DescribirUbicacion.rumboInicial(6.2, -75.58, 6.199, -75.58), 0.05)
        assertEquals(270.0, DescribirUbicacion.rumboInicial(6.2, -75.58, 6.2, -75.581), 0.05)
    }

    @Test
    fun metros() {
        assertEquals("a un metro", DescribirUbicacion.metros(0.4))
        assertEquals("a un metro", DescribirUbicacion.metros(1.4))
        assertEquals("a unos 2 metros", DescribirUbicacion.metros(1.6))
        assertEquals("a unos 35 metros", DescribirUbicacion.metros(35.2))
    }

    @Test
    fun alta_conLugarCercanoYReferencias_conRumboCorregido() {
        // Brújula 0° + corrección −6° = 354°: 95° queda a la derecha y 270° a la izquierda.
        val d = DescribirUbicacion.describir(ubicado(), 0.0, null)
        assertEquals("Estás cerca de Biblioteca Central", d.titulo)
        assertEquals("A unos 12 metros", d.subtitulo)
        assertEquals(
            listOf(
                "Bloque de los Trillizos está a tu derecha, a unos 35 metros.",
                "Cafetería Principal está a tu izquierda, a unos 80 metros.",
            ),
            d.detalles,
        )
        assertEquals("Confianza alta", d.confianza)
        assertEquals("Punto estimado: 6.20000, -75.58000", d.coordenadas)
        assertFalse(d.sugerirRepetir)
        assertEquals(
            "Estás cerca de Biblioteca Central, a unos 12 metros. " +
                "Bloque de los Trillizos está a tu derecha, a unos 35 metros. " +
                "Cafetería Principal está a tu izquierda, a unos 80 metros. Confianza alta.",
            d.hablado,
        )
    }

    @Test
    fun laCorreccionDelBackendCambiaElSector() {
        val ref = ReferenciaLugar("x", "Auditorio", 50.0, 50.0)
        val sinCorreccion = DescribirUbicacion.describir(ubicado(referencias = listOf(ref), correccion = null), 0.0, null)
        assertEquals("Auditorio está a tu derecha, a unos 50 metros.", sinCorreccion.detalles.single())
        val conCorreccion = DescribirUbicacion.describir(ubicado(referencias = listOf(ref), correccion = 10.0), 0.0, null)
        assertEquals("Auditorio está al frente, a unos 50 metros.", conCorreccion.detalles.single())
    }

    @Test
    fun sinRumbo_soloDistancias() {
        val d = DescribirUbicacion.describir(ubicado(), null, null)
        assertEquals("Bloque de los Trillizos está a unos 35 metros.", d.detalles.first())
    }

    @Test
    fun baja_loDiceYSugiereRepetir() {
        val d = DescribirUbicacion.describir(ubicado(NivelConfianza.BAJA), 0.0, null)
        assertEquals("Puede que estés cerca de Biblioteca Central", d.titulo)
        assertEquals("Confianza baja", d.confianza)
        assertTrue(d.sugerirRepetir)
        assertEquals(DescribirUbicacion.POCO_SEGURA, d.detalles.last())
        assertTrue(d.hablado.endsWith("Confianza baja. ${DescribirUbicacion.POCO_SEGURA}"))
    }

    @Test
    fun sinLugarCercano_laPrimeraReferenciaEsLaMasCercana() {
        // Backend §5.3: con lugar_cercano = null, referencias empieza por el lugar más cercano (60–150 m).
        val lejos = ReferenciaLugar("a", "Auditorio Principal", 90.0, 0.0)
        val d = DescribirUbicacion.describir(ubicado(cercano = null, referencias = listOf(lejos)), 0.0, null)
        assertEquals(DescribirUbicacion.NINGUN_LUGAR_JUNTO, d.titulo)
        assertNull(d.subtitulo)
        assertEquals(listOf("Auditorio Principal está al frente, a unos 90 metros."), d.detalles)
        assertTrue(d.hablado.startsWith("${DescribirUbicacion.NINGUN_LUGAR_JUNTO}. Auditorio Principal está al frente"))
    }

    @Test
    fun sinLugaresCerca() {
        val d = DescribirUbicacion.describir(ubicado(cercano = null, referencias = emptyList()), 0.0, null)
        assertEquals(DescribirUbicacion.NINGUN_LUGAR_CERCA, d.titulo)
        assertEquals("${DescribirUbicacion.NINGUN_LUGAR_CERCA}. Confianza alta.", d.hablado)
    }

    @Test
    fun conDestino_distanciaYDireccionEnLineaRecta() {
        // 0,001° al norte ≈ 111 m; la persona mira al norte (brújula 0°, sin corrección).
        val destino = LugarDestino("d", "Biblioteca Central", CategoriaLugar.BIBLIOTECA, 6.201, -75.58)
        val d = DescribirUbicacion.describir(ubicado(referencias = emptyList(), correccion = null), 0.0, destino)
        assertEquals(
            listOf("Tu destino, Biblioteca Central, está al frente, a unos 111 metros.", DescribirUbicacion.LLEGARA_NAVEGACION),
            d.detalles,
        )
        assertTrue(d.hablado.endsWith("Confianza alta. Tu destino, Biblioteca Central, está al frente, a unos 111 metros. " +
            DescribirUbicacion.LLEGARA_NAVEGACION))
    }

    @Test
    fun sinCoincidencias_ySinUbicacion() {
        val destino = LugarDestino("d", "Biblioteca Central", CategoriaLugar.BIBLIOTECA, 6.201, -75.58)
        val sc = DescribirUbicacion.describir(
            UbicacionEstimada(ResultadoUbicacion.SinCoincidencias(5), 0L, null),
            0.0,
            destino,
        )
        assertEquals(DescribirUbicacion.SIN_COINCIDENCIAS, sc.titulo)
        assertNull(sc.confianza)
        assertNull(sc.coordenadas)
        assertTrue(sc.sugerirRepetir)
        assertEquals(
            listOf(
                DescribirUbicacion.REPETIR_VUELTA,
                "Para llevarte a Biblioteca Central primero necesito saber dónde estás.",
            ),
            sc.detalles,
        )

        val nada = DescribirUbicacion.describir(null, null, null)
        assertEquals(DescribirUbicacion.SIN_UBICACION, nada.titulo)
        assertTrue(nada.sugerirRepetir)
        assertTrue(nada.hablado.startsWith("${DescribirUbicacion.SIN_UBICACION}."))
    }
}
