package com.example.dataset_app

import android.content.ContentValues
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "com.example.dataset_app/public_dataset"
    private val datasetRoot = "${Environment.DIRECTORY_DOWNLOADS}/DatasetCaptures"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "exportCapture" -> {
                        val id = call.argument<String>("captureId")!!
                        writeDownload("$id.jpg", "$datasetRoot/images", "image/jpeg", call.argument<ByteArray>("imageBytes")!!)
                        writeDownload("$id.json", "$datasetRoot/metadata", "application/json", call.argument<String>("metadataJson")!!.toByteArray())
                        result.success(null)
                    }
                    "exportMetadata" -> {
                        val id = call.argument<String>("captureId")!!
                        writeDownload("$id.json", "$datasetRoot/metadata", "application/json", call.argument<String>("metadataJson")!!.toByteArray())
                        result.success(null)
                    }
                    "deleteCapture" -> {
                        val id = call.argument<String>("captureId")!!
                        deleteDownload("$id.jpg", "$datasetRoot/images")
                        deleteDownload("$id.json", "$datasetRoot/metadata")
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            } catch (error: Exception) {
                result.error("DATASET_EXPORT_ERROR", error.message, null)
            }
        }
    }

    private fun writeDownload(name: String, directory: String, mimeType: String, bytes: ByteArray) {
        require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) { "Android 10 o superior es requerido." }
        deleteDownload(name, directory)
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, mimeType)
            put(MediaStore.Downloads.RELATIVE_PATH, "$directory/")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("No se pudo crear el archivo en Descargas.")
        try {
            contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: error("No se pudo abrir el archivo en Descargas.")
            values.clear()
            values.put(MediaStore.Downloads.IS_PENDING, 0)
            contentResolver.update(uri, values, null, null)
        } catch (error: Exception) {
            contentResolver.delete(uri, null, null)
            throw error
        }
    }

    private fun deleteDownload(name: String, directory: String) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        contentResolver.delete(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            "${MediaStore.Downloads.DISPLAY_NAME} = ? AND ${MediaStore.Downloads.RELATIVE_PATH} = ?",
            arrayOf(name, "$directory/"),
        )
    }
}
