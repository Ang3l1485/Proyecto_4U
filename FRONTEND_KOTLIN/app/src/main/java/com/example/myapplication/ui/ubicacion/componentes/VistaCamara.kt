package com.example.myapplication.ui.ubicacion.componentes

import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat

/**
 * Vista previa de la cámara trasera (apoyo visual para quien ve).
 *
 * Además de la vista previa, vincula [imageCapture] a la cámara: sin ese enlace
 * `takePicture` no funcionaría. Solo se enciende cuando [activo] (permiso concedido).
 */
@Composable
internal fun VistaCamara(
    imageCapture: ImageCapture,
    activo: Boolean,
    modifier: Modifier = Modifier,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    Box(modifier.clip(RoundedCornerShape(18.dp)).background(Color.Black)) {
        if (activo) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { c ->
                    PreviewView(c).also { pv ->
                        pv.scaleType = PreviewView.ScaleType.FILL_CENTER
                        val futuro = ProcessCameraProvider.getInstance(c)
                        futuro.addListener({
                            val provider = futuro.get()
                            val preview = Preview.Builder().build()
                                .also { it.setSurfaceProvider(pv.surfaceProvider) }
                            // Se limpia cualquier vínculo previo y se enlaza todo al ciclo de vida.
                            provider.unbindAll()
                            provider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                imageCapture,
                            )
                        }, ContextCompat.getMainExecutor(c))
                    }
                },
            )
        }

        // Etiqueta flotante "Vista de cámara" (esquina superior izquierda).
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(12.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(Color(0xAA0B1220))
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.CameraAlt, null, tint = Color.White, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(10.dp))
            Text("Vista de cámara", color = Color(0xFFD1D5DB), fontSize = 14.sp)
        }
    }
}