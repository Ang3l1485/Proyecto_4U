package com.example.myapplication.data.local

import java.io.File

/**
 * Ayudas de las pruebas de `data/local/`: crea recorridos con el formato de `files/recoleccion/rec_NNNN/` (el que
 * escribe `RecoleccionRepositoryLocal`, ARCHITECTURE §5.6), con fotos JPG falsas (bytes cualesquiera).
 */
object ManifestPrueba {

    /**
     * Escribe `raiz/<id>/manifest.json` y `photos/NNNN.jpg` para las fotos 1..[fotos].
     * @param subidas ids (número) con `sync = subida`.
     * @param preparadas ids con `upload` (y su copia en `subida/`).
     * @param extra claves de video añadidas tal cual al JSON (p. ej. `"remote_video_id": "v1"`).
     */
    fun crear(
        raiz: File,
        id: String = "rec_0001",
        fotos: Int = 3,
        estado: String = "finalizado",
        subidas: Set<Int> = emptySet(),
        preparadas: Set<Int> = emptySet(),
        extra: Map<String, String> = emptyMap(),
        nombre: String = "Entrada norte",
    ): File {
        val carpeta = File(raiz, id)
        File(carpeta, "photos").mkdirs()
        val listaFotos = (1..fotos).joinToString(",") { n ->
            val fid = "%04d".format(n)
            File(carpeta, "photos/$fid.jpg").writeBytes(ByteArray(100 + n) { (it % 251).toByte() })
            val upload = if (n in preparadas) {
                val copia = File(carpeta, "subida/$fid.jpg")
                copia.parentFile?.mkdirs()
                copia.writeBytes(ByteArray(50 + n))
                ""","upload":{"bytes":${50 + n},"width":1600,"height":1200}"""
            } else {
                ""
            }
            val sync = if (n in subidas) "subida" else "pendiente"
            """{"id":"$fid","file":"photos/$fid.jpg","lat":${6.2 + n * 0.0001},"lng":-75.578,""" +
                """"captured_at":"2026-10-25T15:0${n % 10}:00-05:00","sync":"$sync","heading":${(n * 37) % 360}.5$upload}"""
        }
        val claves = extra.entries.joinToString("") { (k, v) -> ""","$k":$v""" }
        val json = """{"video_id":"$id","name":"$nombre","created_at":"2026-10-25T15:00:00-05:00",""" +
            """"estado":"$estado","start_lat":6.2,"start_lng":-75.578,"start_heading":359.99,""" +
            """"ended_at":"2026-10-25T15:08:32-05:00","duration_s":512,"distance_m":340.5,"steps":470,""" +
            """"progress":{"lat":6.2,"lng":-75.578,"track":[[6.2,-75.578],[6.2001,-75.5781]],"saved_at":"2026-10-25T15:08:00-05:00"},""" +
            """"photos":[$listaFotos]$claves}"""
        File(carpeta, "manifest.json").writeText(json)
        return carpeta
    }
}
