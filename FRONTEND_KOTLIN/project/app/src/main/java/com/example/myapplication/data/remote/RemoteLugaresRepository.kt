package com.example.myapplication.data.remote

import com.example.myapplication.data.repository.LugaresRepository
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.logs.AppLog

/**
 * [LugaresRepository] real (FE-3.1): `GET /v1/places` (backend §5.3). Ruta pública: no lleva `Authorization` ni pasa
 * por la sesión.
 *
 * - [posicion] da la posición vigente de la persona (`lat`, `lng`) o `null`. Con posición se envían `lat` y `lng` y cada
 *   lugar trae `distanciaMetros` (el `distancia_m` del backend redondeado, [MapeoDatosApi.lugarDestino]) y la lista
 *   llega ordenada por distancia; sin posición, `distanciaMetros = null` y la lista llega ordenada por nombre. Hoy nadie
 *   pasa posición en el flujo público (la ubicación es de FE-3.2): el valor por defecto es `{ null }`.
 * - Un lugar con una categoría que la app no conoce se descarta ([MapeoDatosApi.lugarDestino] da `null`) y queda una
 *   línea en [registrar]; un `id` repetido se descarta también (la lista de 6.4 usa `key = { it.id }` y Compose falla
 *   con claves repetidas; el backend da UUID únicos, así que no debería pasar).
 * - Errores (los de [llamar]): sin red, *timeout* o `5xx` de API Gateway → `SinConexionException` (una `IOException`:
 *   Destino muestra «Sin conexión»); `422`, `503 BASE_NO_DISPONIBLE` u otro código → [ApiException]; un `200` sin `items`
 *   o con un lugar sin `id`, `nombre`, `lat` o `lng` → [RespuestaInesperadaException].
 * - `imagenUrl` es el `imagen_url` del backend (URL prefirmada de 1 h o `null`; hoy siempre `null`, backend §5.3): la
 *   lista muestra el ícono de la categoría si es `null` o si la foto no carga (`FilaLugar`).
 */
class RemoteLugaresRepository(
    private val api: CampusApi = ClienteApi.api,
    private val posicion: () -> Pair<Double, Double>? = { null },
    private val registrar: (String) -> Unit = { AppLog.w(TAG, it) },
) : LugaresRepository {

    override suspend fun obtenerLugares(): List<LugarDestino> {
        val p = posicion()
        val dto = llamar { api.lugares(lat = p?.first, lng = p?.second) }
        val items = dto.items ?: throw RespuestaInesperadaException("GET /v1/places: la respuesta no trae «items»")
        val lugares = items.mapNotNull { MapeoDatosApi.lugarDestino(it) }
        val descartados = items.size - lugares.size
        if (descartados > 0) {
            val categorias = items.mapNotNull { it.categoria }
                .filter { MapeoDatosApi.enumDe<CategoriaLugar>(it) == null }
                .distinct()
            registrar("GET /v1/places: $descartados lugar(es) descartado(s) por categoría desconocida $categorias")
        }
        val unicos = lugares.distinctBy { it.id }
        if (unicos.size < lugares.size) {
            registrar("GET /v1/places: ${lugares.size - unicos.size} lugar(es) con id repetido descartado(s)")
        }
        return unicos
    }

    companion object {
        /** Tag de `AppLog` de este repositorio. */
        const val TAG = "Lugares"
    }
}
