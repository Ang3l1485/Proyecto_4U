package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.AdminRepository
import com.example.myapplication.domain.model.ResumenAdmin

/**
 * [AdminRepository] real (FE-2.2): el «Resumen rápido» del Panel (7.2) junta dos orígenes en una sola llamada.
 *
 * - `GET /v1/admin/stats` (backend §5.5, BE-2.3): `total_fotos`, `total_lugares`, `alertas_activas` y `ultimo_video`
 *   (número y `creado_en` en milisegundos), con [MapeoDatosApi.resumenAdmin]. Ruta protegida: con `ClienteApi.api` la
 *   lleva `SesionInterceptor` (sin sesión no sale; un `401` de sesión cierra la sesión y `AppNav` vuelve a Login).
 * - [fotosPendientes]: la cola local de subida (en la app, `AlmacenRecorridos.contarFotosPendientes()`, §5.10). Se
 *   llama **después** de que responde el backend (el dato local es el más reciente posible) y solo si respondió un
 *   `200` que cumple el contrato.
 *
 * Errores (los de [llamar]; no se llama a [fotosPendientes]): sin red, *timeout* o `5xx` de API Gateway →
 * `SinConexionException`; sin sesión, vencida o `401 TOKEN_*` → [ApiException] con `FalloApi.SesionVencida`; otro
 * código → [ApiException]; un `200` sin alguno de los tres totales o con `ultimo_video` sin `numero` →
 * [RespuestaInesperadaException]. Una excepción de [fotosPendientes] se propaga tal cual.
 */
class RemoteAdminRepository(
    private val api: CampusApi = ClienteApi.api,
    private val fotosPendientes: suspend () -> Int,
) : AdminRepository {

    override suspend fun obtenerResumen(): ResumenAdmin {
        val dto = llamar { api.estadisticas() }
        // Primero se valida la respuesta (lanza si no cumple el contrato) y después se cuenta la cola local.
        val delBackend = MapeoDatosApi.resumenAdmin(dto, fotosPendientes = 0)
        return delBackend.copy(fotosPendientes = fotosPendientes())
    }
}
