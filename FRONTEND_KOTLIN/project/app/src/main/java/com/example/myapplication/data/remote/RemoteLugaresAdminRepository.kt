package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.CambiosLugares
import com.example.myapplication.data.repository.ContadorCambios
import com.example.myapplication.data.repository.LugaresAdminRepository
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.DatosLugar
import com.example.myapplication.domain.model.LugarAdmin
import com.example.myapplication.logs.AppLog

/**
 * [LugaresAdminRepository] real (FE-3.4): `/v1/admin/places` (backend §5.5, BE-3.1). Rutas protegidas: con
 * `ClienteApi.api` las lleva `SesionInterceptor` (sin sesión no salen y `AppNav` vuelve a Login).
 *
 * - [listar]: `GET /v1/admin/places` sin `q` ni `categoria`; descarta, como `RemoteLugaresRepository`, los de categoría
 *   desconocida y los `id` repetidos, con una línea en [registrar] (sin nombres de lugares).
 * - [crear] / [reemplazar] / [borrar]: tras un `2xx` llaman a [cambios]`.avisar()` (la lista 7.6 y el Panel recargan).
 *   Un error no avisa: un `409 NOMBRE_DUPLICADO` no escribe nada en el backend.
 * - Errores: los de [llamar] (§5.10). `409` y `422` llegan como `ApiException(FalloApi.Validacion)`; un `PUT` a un lugar
 *   borrado, como `ApiException(FalloApi.Desconocido(404, "NO_ENCONTRADO"))`.
 * - No registra nada más que la línea `Api` de cada petición (sin cuerpos: el nombre del lugar no sale en `app.log`).
 */
class RemoteLugaresAdminRepository(
    private val api: CampusApi = ClienteApi.api,
    private val cambios: ContadorCambios = CambiosLugares,
    private val registrar: (String) -> Unit = { AppLog.w(TAG, it) },
) : LugaresAdminRepository {

    override suspend fun listar(): List<LugarAdmin> {
        val dto = llamar { api.lugaresAdmin() }
        val items = dto.items
            ?: throw RespuestaInesperadaException("GET /v1/admin/places: la respuesta no trae «items»")
        val lugares = items.mapNotNull { MapeoDatosApi.lugarAdmin(it) }
        val descartados = items.size - lugares.size
        if (descartados > 0) {
            val categorias = items.mapNotNull { it.categoria }
                .filter { MapeoDatosApi.enumDe<CategoriaLugar>(it) == null }
                .distinct()
            registrar("GET /v1/admin/places: $descartados lugar(es) descartado(s) por categoría desconocida $categorias")
        }
        val unicos = lugares.distinctBy { it.id }
        if (unicos.size < lugares.size) {
            registrar("GET /v1/admin/places: ${lugares.size - unicos.size} lugar(es) con id repetido descartado(s)")
        }
        return unicos
    }

    override suspend fun obtener(id: String): LugarAdmin? = listar().firstOrNull { it.id == id }

    override suspend fun crear(datos: DatosLugar): LugarAdmin {
        val dto = llamar { api.crearLugar(MapeoDatosApi.entradaLugar(datos)) }
        cambios.avisar() // ya está guardado aunque la respuesta no se pueda leer
        return guardado(dto, "POST")
    }

    override suspend fun reemplazar(id: String, datos: DatosLugar): LugarAdmin {
        val dto = llamar { api.reemplazarLugar(id, MapeoDatosApi.entradaLugar(datos)) }
        cambios.avisar()
        return guardado(dto, "PUT")
    }

    override suspend fun borrar(id: String) {
        llamarSinCuerpo { api.borrarLugar(id) }
        cambios.avisar()
    }

    private fun guardado(dto: LugarAdminDto, metodo: String): LugarAdmin =
        MapeoDatosApi.lugarAdmin(dto)
            ?: throw RespuestaInesperadaException("$metodo /v1/admin/places: categoría desconocida ${dto.categoria}")

    companion object {
        /** Tag de `AppLog` (el mismo que `RemoteLugaresRepository`). */
        const val TAG = "Lugares"
    }
}
