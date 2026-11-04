package com.example.myapplication.data.repository

import com.example.myapplication.domain.model.DatosLugar
import com.example.myapplication.domain.model.LugarAdmin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * Lugares de la administración (FE-3.4: vistas 7.6 y 7.7). Implementación real:
 * `RemoteLugaresAdminRepository` (`/v1/admin/places`, backend §5.5; ARCHITECTURE §5.10, «Lugares de administración»).
 * Rutas protegidas: sin sesión o con la sesión rechazada lanzan `ApiException(FalloApi.SesionVencida)` y `AppNav` vuelve
 * a Login. Sin red, `SinConexionException` (una `IOException`); otro error del backend, `ApiException` (un nombre
 * repetido es `FalloApi.Validacion(409, "NOMBRE_DUPLICADO", …)`); un `2xx` fuera de contrato,
 * `RespuestaInesperadaException`.
 */
interface LugaresAdminRepository {
    /** Todos los lugares (`GET /v1/admin/places` sin filtros), ordenados por nombre como los da el backend. */
    suspend fun listar(): List<LugarAdmin>

    /** El lugar de ese id, o `null` si ya no existe. El backend no tiene `GET` por id: sale de [listar]. */
    suspend fun obtener(id: String): LugarAdmin?

    /** `POST /v1/admin/places` → el lugar guardado (`201`). */
    suspend fun crear(datos: DatosLugar): LugarAdmin

    /** `PUT /v1/admin/places/{id}` → el lugar guardado (`200`). Reemplaza todos los campos de [datos]. */
    suspend fun reemplazar(id: String, datos: DatosLugar): LugarAdmin

    /** `DELETE /v1/admin/places/{id}` (`204`, también si ya no existía). Sus fotos quedan sin lugar. */
    suspend fun borrar(id: String)
}

/**
 * Contador de cambios de un tipo de dato del backend (FE-3.4). Quien escribe llama a [avisar] tras un cambio confirmado;
 * quien muestra el dato compara [version] con la que tenía al cargar y recarga si cambió. El número no significa nada
 * (como `VideoRepository.cambios()`). Abierta para que las pruebas usen su propia instancia.
 */
open class ContadorCambios {
    private val _version = MutableStateFlow(0)
    val version: StateFlow<Int> = _version.asStateFlow()

    fun avisar() {
        _version.update { it + 1 }
    }
}

/**
 * Cambios de lugares del proceso: los avisa `RemoteLugaresAdminRepository` tras crear, reemplazar o borrar. Lo miran la
 * lista 7.6 (recarga) y el Panel (recarga el «Resumen rápido» al volver: «Lugares registrados»). Solo memoria.
 */
object CambiosLugares : ContadorCambios()
