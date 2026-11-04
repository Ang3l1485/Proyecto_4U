package com.example.myapplication

/**
 * URL de la API del backend y tiempos máximos del cliente HTTP (ARCHITECTURE §5.10).
 *
 * [API_BASE_URL] es el output `api_base_url` de Terraform (`INFRASTRUCTURA_TERRAFORM/docs/ARCHITECTURE.md` §5.2),
 * sin barra final. Si la API se recrea, la URL cambia: actualizar este valor (lo comprueba `validate11.py`, C4).
 * El validador lee las dos líneas `const val` de abajo tal cual: no cambiar su forma.
 */
object ApiConfig {
    const val API_BASE_URL = "https://fuzq99kddb.execute-api.us-east-1.amazonaws.com"
    const val BASE_URL = "$API_BASE_URL/v1"

    const val TIMEOUT_CONEXION_S = 10L
    const val TIMEOUT_LECTURA_S = 30L
    const val TIMEOUT_ESCRITURA_S = 30L
}
