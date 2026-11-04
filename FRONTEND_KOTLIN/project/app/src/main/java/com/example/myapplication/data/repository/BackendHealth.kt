package com.example.myapplication.data.repository

/** ¿Responde el backend? Lo usa el indicador de conexión de Inicio (vista 6.1). */
interface BackendHealth {
    /** `true` solo si el backend respondió que está bien; cualquier fallo es `false` (no lanza). */
    suspend fun estaEnLinea(): Boolean
}
