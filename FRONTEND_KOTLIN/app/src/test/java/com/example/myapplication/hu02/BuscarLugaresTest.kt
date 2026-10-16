package com.example.myapplication.hu02

import com.example.myapplication.data.repository.LUGARES_DE_PRUEBA
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.usecase.BuscarLugares
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * HU-02 / Selección de destino (vista 6.4, "Ir a un lugar").
 *
 * Prueba la coincidencia aproximada entre lo que dice la persona y los lugares del campus
 * (`BuscarLugares.mejores`) y el buscador de la lista (`BuscarLugares.filtrar`).
 * Reglas tomadas de ARCHITECTURE_front.md §11.7: umbral 0,70 · empate a 0,04 · máximo 3 opciones.
 *
 * Es lógica pura (sin Android): corre en JVM.
 */
class BuscarLugaresTest {

    private val lugares = LUGARES_DE_PRUEBA

    private fun ids(consulta: String, entre: List<LugarDestino> = lugares): List<String> =
        BuscarLugares.mejores(consulta, entre).map { it.id }

    private fun lugar(id: String, nombre: String, alias: List<String> = emptyList()) = LugarDestino(
        id = id,
        nombre = nombre,
        categoria = CategoriaLugar.BLOQUE,
        lat = 0.0,
        lng = 0.0,
        alias = alias,
    )

    // ------------------------------------------------------------------ mejores(): camino feliz

    @Test
    fun frase_natural_con_muletillas_encuentra_la_biblioteca() {
        assertEquals(listOf("biblioteca-central"), ids("quiero ir a la biblioteca"))
    }

    @Test
    fun nombre_completo_exacto_devuelve_un_solo_lugar() {
        assertEquals(listOf("cafeteria-principal"), ids("Cafetería Principal"))
    }

    @Test
    fun un_alias_corto_encuentra_el_lugar() {
        assertEquals(listOf("cafeteria-principal"), ids("cafe"))
        assertEquals(listOf("bloque-trillizos"), ids("los trillizos"))
        assertEquals(listOf("entrada-principal"), ids("porteria"))
    }

    @Test
    fun una_sola_palabra_del_nombre_es_suficiente() {
        // "central" es la segunda palabra de "Biblioteca Central".
        assertEquals(listOf("biblioteca-central"), ids("central"))
    }

    // ------------------------------------------------------------------ mejores(): alternos

    @Test
    fun ignora_mayusculas_y_tildes() {
        assertEquals(listOf("banos-bloque-a"), ids("BAÑOS"))
        assertEquals(listOf("entrada-principal"), ids("llévame a la ENTRADA"))
    }

    @Test
    fun tolera_un_error_de_reconocimiento_de_voz() {
        // "bibliotka" está a 2 letras de "biblioteca".
        assertEquals(listOf("biblioteca-central"), ids("bibliotka"))
    }

    @Test
    fun un_prefijo_de_tres_letras_ya_encuentra_el_lugar() {
        assertEquals(listOf("auditorio-principal"), ids("aud"))
    }

    @Test
    fun un_prefijo_de_dos_letras_no_cuenta() {
        assertTrue(ids("au").isEmpty())
    }

    @Test
    fun una_palabra_compartida_devuelve_un_empate_de_tres_opciones() {
        val encontrados = ids("principal")
        assertEquals(3, encontrados.size)
        assertEquals(
            setOf("cafeteria-principal", "auditorio-principal", "entrada-principal"),
            encontrados.toSet(),
        )
    }

    @Test
    fun el_empate_se_limita_a_tres_opciones_aunque_haya_mas() {
        val cuatro = listOf(
            lugar("a", "Sala"), lugar("b", "Sala"), lugar("c", "Sala"), lugar("d", "Sala"),
        )
        // Se descartan los de más "por orden de la lista" (§11.7).
        assertEquals(listOf("a", "b", "c"), ids("sala", cuatro))
    }

    @Test
    fun una_coincidencia_exacta_desplaza_a_un_nombre_parecido() {
        val parecidos = listOf(lugar("exacto", "Laboratorio"), lugar("parecido", "Laboratorios"))
        // 1,0 contra 0,855: la diferencia supera el margen de empate (0,04).
        assertEquals(listOf("exacto"), ids("laboratorio", parecidos))
    }

    @Test
    fun un_lugar_inexistente_no_devuelve_coincidencias() {
        assertTrue(ids("estadio de futbol").isEmpty())
    }

    @Test
    fun una_consulta_vacia_o_con_solo_espacios_no_devuelve_nada() {
        assertTrue(ids("").isEmpty())
        assertTrue(ids("   ").isEmpty())
    }

    @Test
    fun una_consulta_con_solo_muletillas_no_devuelve_ningun_lugar() {
        assertTrue(ids("quiero ir a").isEmpty())
    }

    @Test
    fun sin_lugares_cargados_no_hay_coincidencias() {
        assertTrue(BuscarLugares.mejores("biblioteca", emptyList()).isEmpty())
    }

    @Test
    fun limpiar_quita_tildes_signos_y_espacios_sobrantes() {
        assertEquals(listOf("banos", "cafe"), BuscarLugares.limpiar("  Baños-Café!! "))
        assertTrue(BuscarLugares.limpiar("   ").isEmpty())
    }

    // ------------------------------------------------------------------ filtrar(): buscador

    @Test
    fun filtrar_con_texto_vacio_devuelve_toda_la_lista() {
        assertEquals(lugares, BuscarLugares.filtrar(lugares, ""))
        assertEquals(lugares, BuscarLugares.filtrar(lugares, "   "))
    }

    @Test
    fun filtrar_acepta_una_parte_del_nombre() {
        assertEquals(
            listOf("biblioteca-central"),
            BuscarLugares.filtrar(lugares, "biblio").map { it.id },
        )
    }

    @Test
    fun filtrar_exige_que_aparezca_cada_palabra_escrita() {
        assertEquals(
            listOf("cafeteria-principal"),
            BuscarLugares.filtrar(lugares, "cafe principal").map { it.id },
        )
    }

    @Test
    fun filtrar_busca_en_la_categoria_y_normaliza_la_enie() {
        // "Baño" es la etiqueta (singular) de la categoría BANO.
        assertEquals(
            listOf("banos-bloque-a"),
            BuscarLugares.filtrar(lugares, "Baño").map { it.id },
        )
    }

    @Test
    fun filtrar_conserva_el_orden_original_de_la_lista() {
        assertEquals(
            listOf("cafeteria-principal", "auditorio-principal", "entrada-principal"),
            BuscarLugares.filtrar(lugares, "principal").map { it.id },
        )
    }

    @Test
    fun filtrar_sin_resultados_devuelve_lista_vacia() {
        assertTrue(BuscarLugares.filtrar(lugares, "xyz").isEmpty())
    }
}
