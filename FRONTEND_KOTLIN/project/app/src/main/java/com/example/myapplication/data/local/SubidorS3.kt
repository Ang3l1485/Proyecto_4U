package com.example.myapplication.data.local

import com.example.myapplication.ApiConfig
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * `PUT` de una foto a su URL prefirmada de S3 (FE-2.1, ARCHITECTURE §5.10; contrato en backend §5.4). Usa un
 * `OkHttpClient` **propio, sin interceptores**: ni `X-Request-Id` ni `Authorization` (el contrato pide enviar
 * exactamente los encabezados recibidos; `Content-Type` forma parte de la firma). Nunca registra la URL (la firma va en
 * la *query*): quien llama solo anota el id de la foto, el código y la duración.
 */
class SubidorS3(private val cliente: OkHttpClient = crearCliente()) {

    /**
     * Sube [archivo] con exactamente [encabezados] (`Content-Type` va como tipo del cuerpo, sin `charset`). Devuelve el
     * código HTTP (S3: `200`; `403` = URL vencida o firma que no coincide). Sin respuesta (red, *timeout*) →
     * [IOException]. Bloqueante: llamarlo en `Dispatchers.IO`.
     */
    @Throws(IOException::class)
    fun subir(url: String, encabezados: Map<String, String>, archivo: File): Int {
        val tipo = encabezados.entries.firstOrNull { it.key.equals(CONTENT_TYPE, ignoreCase = true) }?.value
        val peticion = Request.Builder()
            .url(url)
            .put(archivo.asRequestBody(tipo?.toMediaTypeOrNull()))
            .apply { encabezados.forEach { (k, v) -> if (!k.equals(CONTENT_TYPE, ignoreCase = true)) header(k, v) } }
            .build()
        cliente.newCall(peticion).execute().use { return it.code }
    }

    companion object {
        private const val CONTENT_TYPE = "Content-Type"

        /** Tiempos de [ApiConfig]; escritura de 60 s (una foto re-codificada pesa ~0,5 MB; con mala señal tarda). */
        fun crearCliente(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(ApiConfig.TIMEOUT_CONEXION_S, TimeUnit.SECONDS)
            .readTimeout(ApiConfig.TIMEOUT_LECTURA_S, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_ESCRITURA_PUT_S, TimeUnit.SECONDS)
            .build()

        const val TIMEOUT_ESCRITURA_PUT_S = 60L
    }
}
