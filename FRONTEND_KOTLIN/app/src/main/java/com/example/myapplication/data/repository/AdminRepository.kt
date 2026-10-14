package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.ResumenAdmin

interface AdminRepository {
    /**
     * Totales del dataset, lugares y alertas activas: backend (GET /admin/stats).
     * Fotos pendientes de subir: cola local (data/local), no viene del backend.
     * @throws java.io.IOException si no hay conexión.
     */
    suspend fun obtenerResumen(): ResumenAdmin
}

/** TODO: reemplazar por la implementación real (Retrofit/Ktor + cola local de subida). */
class AdminRepositoryStub : AdminRepository {
    override suspend fun obtenerResumen(): ResumenAdmin {
        kotlinx.coroutines.delay(600)
        return ResumenAdmin(
            totalFotos = 2842,
            totalLugares = 48,
            alertasActivas = 3,
            ultimoVideoNumero = 12,
            ultimoVideoFecha = System.currentTimeMillis(),
            fotosPendientes = 27,
        )
    }
}