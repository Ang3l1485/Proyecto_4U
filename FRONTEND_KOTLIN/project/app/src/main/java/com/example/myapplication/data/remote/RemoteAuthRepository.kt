package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.AuthRepository
import com.example.myapplication.domain.model.Sesion

/**
 * [AuthRepository] real (FE-1.2): `POST /v1/auth/login` (backend §5.3) con `{"identificador", "password"}`.
 *
 * - `200` → [Sesion] con `token`, `usuario` y `expira_en` en milisegundos ([MapeoDatosApi.sesion]); también para un
 *   `user` (el rol lo decide `LoginViewModel`).
 * - `401 CREDENCIALES_INVALIDAS` → `CredencialesInvalidasException`.
 * - Sin red, *timeout* o `5xx` de API Gateway → `SinConexionException` (una `IOException`).
 * - Cualquier otra respuesta (`429`, `422`, `503 SERVICIO_OCUPADO`…) → [ApiException]; un `200` sin token, sin
 *   `expira_en` o con un rol desconocido → [RespuestaInesperadaException]. `LoginViewModel` muestra las dos como
 *   «Algo salió mal».
 *
 * Nunca registra la contraseña ni el token: la única línea es la de `RequestIdInterceptor` (método, ruta, código).
 */
class RemoteAuthRepository(private val api: CampusApi = ClienteApi.api) : AuthRepository {
    override suspend fun login(identificador: String, password: String): Sesion {
        val dto = llamar { api.login(LoginPeticionDto(identificador = identificador, password = password)) }
        return MapeoDatosApi.sesion(dto)
    }
}
