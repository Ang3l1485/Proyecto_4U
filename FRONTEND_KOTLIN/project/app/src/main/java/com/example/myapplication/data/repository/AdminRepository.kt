package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.ResumenAdmin

interface AdminRepository {
    /**
     * Totales del dataset, lugares, alertas activas y último video: backend (`GET /v1/admin/stats`).
     * Fotos pendientes de subir: cola local (`data/local`), no viene del backend.
     * La implementación real es `RemoteAdminRepository` (FE-2.2; errores en su KDoc): sin conexión lanza una
     * `java.io.IOException` (`SinConexionException`).
     */
    suspend fun obtenerResumen(): ResumenAdmin
}

/** Datos fijos para desarrollo (sin uso en la app desde FE-2.2, que usa `RemoteAdminRepository`). */
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