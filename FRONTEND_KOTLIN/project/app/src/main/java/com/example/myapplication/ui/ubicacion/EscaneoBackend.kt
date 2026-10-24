package com.example.myapplication.ui.ubicacion

import kotlinx.coroutines.delay
import java.io.File
import java.io.IOException

/**
 * Contrato con el backend de ubicación.
 * TODO: sustituir [EscaneoBackendStub] por la llamada real (OkHttp/Retrofit + ApiConfig),
 *       enviando también el heading de cada foto (ver ARCHITECTURE.md §2.1).
 *
 * Debe lanzar [IOException] si falla la red.
 */
interface EscaneoBackend {
    @Throws(IOException::class)
    suspend fun analizar(fotos: List<File>)
}

/** Implementación de relleno: simula 2.5 s de análisis. Solo para desarrollo. */
object EscaneoBackendStub : EscaneoBackend {
    override suspend fun analizar(fotos: List<File>) {
        delay(2500)
    }
}