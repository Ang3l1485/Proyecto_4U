package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino

interface LugaresRepository {
    /**
     * Lugares del campus con su distancia a la posición actual: backend (GET /places).
     * @throws java.io.IOException si no hay conexión.
     */
    suspend fun obtenerLugares(): List<LugarDestino>
}

/** Datos de ejemplo. Las coordenadas son aproximadas y solo sirven mientras no exista el backend. */
val LUGARES_DE_PRUEBA: List<LugarDestino> = listOf(
    LugarDestino(
        id = "biblioteca-central", nombre = "Biblioteca Central",
        categoria = CategoriaLugar.BIBLIOTECA, lat = 6.2008, lng = -75.5783,
        alias = listOf("biblioteca", "la biblioteca"), distanciaMetros = 85,
    ),
    LugarDestino(
        id = "cafeteria-principal", nombre = "Cafetería Principal",
        categoria = CategoriaLugar.CAFETERIA, lat = 6.2005, lng = -75.5787,
        alias = listOf("cafeteria", "cafe", "la cafeteria"), distanciaMetros = 120,
    ),
    LugarDestino(
        id = "banos-bloque-a", nombre = "Baños Bloque A",
        categoria = CategoriaLugar.BANO, lat = 6.2010, lng = -75.5790,
        alias = listOf("banos", "bano", "los banos"), distanciaMetros = 150,
    ),
    LugarDestino(
        id = "bloque-trillizos", nombre = "Bloque de los Trillizos",
        categoria = CategoriaLugar.BLOQUE, lat = 6.2002, lng = -75.5779,
        alias = listOf("trillizos", "los trillizos"), distanciaMetros = 200,
    ),
    LugarDestino(
        id = "auditorio-principal", nombre = "Auditorio Principal",
        categoria = CategoriaLugar.AUDITORIO, lat = 6.2013, lng = -75.5775,
        alias = listOf("auditorio"), distanciaMetros = 260,
    ),
    LugarDestino(
        id = "entrada-principal", nombre = "Entrada Principal",
        categoria = CategoriaLugar.ENTRADA, lat = 6.1998, lng = -75.5791,
        alias = listOf("entrada", "porteria"), distanciaMetros = 310,
    ),
)

/** TODO: reemplazar por la implementación real (Retrofit/Ktor con `ApiConfig.kt`, GET /places). */
class LugaresRepositoryStub : LugaresRepository {
    override suspend fun obtenerLugares(): List<LugarDestino> {
        kotlinx.coroutines.delay(300)
        return LUGARES_DE_PRUEBA
    }
}
