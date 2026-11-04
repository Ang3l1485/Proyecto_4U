package com.example.myapplication.camera

import android.content.Context
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import com.example.myapplication.logs.AppLog
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private const val TAG = "Camara"

fun crearImageCapture(): ImageCapture =
    ImageCapture.Builder()
        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
        .build()

/**
 * Crea la carpeta de un nuevo escaneo: files/camera/photos/<yyyy-MM-dd_HH-mm-ss>/
 * y borra los escaneos más antiguos, dejando solo los últimos [mantener].
 */
fun crearCarpetaEscaneo(ctx: Context, mantener: Int = 20): File {
    val raiz = File(ctx.filesDir, "camera/photos").apply { mkdirs() }
    val nombre = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US).format(Date())
    val carpeta = File(raiz, nombre).apply { mkdirs() }

    // Los nombres de carpeta ordenan cronológicamente; se borran los más viejos.
    raiz.listFiles { f -> f.isDirectory }
        ?.sortedBy { it.name }
        ?.dropLast(mantener)
        ?.forEach { it.deleteRecursively() }

    AppLog.i(TAG, "Carpeta de escaneo creada: ${carpeta.absolutePath}")
    return carpeta
}

/**
 * Toma una foto y la guarda dentro de [carpeta] como <prefijo>_<n>.jpg (n = 1, 2, 3…).
 *
 * @param onGuardada se invoca (hilo principal) con el archivo JPG ya escrito.
 * @param onFallo    se invoca (hilo principal) si CameraX no pudo capturar.
 */
fun ImageCapture.tomarFoto(
    ctx: Context,
    carpeta: File,
    prefijo: String = "foto",
    onGuardada: (File) -> Unit,
    onFallo: () -> Unit,
) {
    carpeta.mkdirs()

    // Reserva el nombre antes de capturar, para que dos fotos nunca se pisen.
    var n = 1
    var archivo = File(carpeta, "${prefijo}_$n.jpg")
    while (!archivo.createNewFile()) {
        n++
        archivo = File(carpeta, "${prefijo}_$n.jpg")
    }
    AppLog.i(TAG, "Solicitando foto -> ${carpeta.name}/${archivo.name}")

    try {
        takePicture(
            ImageCapture.OutputFileOptions.Builder(archivo).build(),
            ContextCompat.getMainExecutor(ctx),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    AppLog.i(TAG, "Foto guardada: ${archivo.absolutePath} (${archivo.length() / 1024} KB)")
                    onGuardada(archivo)
                }

                override fun onError(exception: ImageCaptureException) {
                    AppLog.e(TAG, "Fallo al capturar (código ${exception.imageCaptureError})", exception)
                    archivo.delete() // quita el archivo vacío reservado
                    onFallo()
                }
            },
        )
    } catch (e: Exception) {
        AppLog.e(TAG, "takePicture lanzó excepción (¿cámara aún no enlazada?)", e)
        archivo.delete()
        onFallo()
    }
}

fun liberarCamara(ctx: Context) {
    runCatching { ProcessCameraProvider.getInstance(ctx).get().unbindAll() }
        .onFailure { AppLog.w(TAG, "No se pudo liberar la cámara", it) }
}