package com.example.myapplication.sensors

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext

/** ¿Tiene el teléfono sensor de vector de rotación? (necesario para medir el giro). */
fun tieneSensorRotacion(ctx: Context): Boolean =
    (ctx.getSystemService(Context.SENSOR_SERVICE) as SensorManager)
        .getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR) != null

/**
 * Escucha el sensor de rotación mientras [activo] sea true y entrega acimut y cabeceo en grados.
 *
 * - **acimut**: hacia dónde apunta la cámara trasera (0° = norte magnético, crece hacia la derecha).
 * - **cabeceo**: inclinación respecto a la vertical (≈0° con el celular derecho).
 *
 * El listener se registra al activarse y se libera solo al salir de la composición.
 * Los callbacks llegan en el hilo principal.
 */
@Composable
fun EscucharOrientacion(
    activo: Boolean,
    onOrientacion: (acimutGrados: Float, cabeceoGrados: Float) -> Unit,
) {
    val ctx = LocalContext.current
    // Evita capturar un callback viejo si el padre se recompone con otra lambda.
    val callback by rememberUpdatedState(onOrientacion)

    DisposableEffect(activo) {
        if (!activo) return@DisposableEffect onDispose { }

        val sm = ctx.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val sensor = sm.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
            ?: return@DisposableEffect onDispose { }

        // Buffers reutilizados para no crear arreglos en cada evento (~50 Hz).
        val r = FloatArray(9)   // matriz de rotación original
        val r2 = FloatArray(9)  // matriz remapeada al celular en vertical
        val o = FloatArray(3)   // [acimut, cabeceo, alabeo] en radianes

        val listener = object : SensorEventListener {
            override fun onSensorChanged(e: SensorEvent) {
                SensorManager.getRotationMatrixFromVector(r, e.values)
                // Celular en vertical con la cámara apuntando al frente:
                // se intercambian los ejes para que "acimut" sea hacia donde mira la cámara.
                SensorManager.remapCoordinateSystem(r, SensorManager.AXIS_X, SensorManager.AXIS_Z, r2)
                SensorManager.getOrientation(r2, o)
                callback(
                    Math.toDegrees(o[0].toDouble()).toFloat(),
                    Math.toDegrees(o[1].toDouble()).toFloat(),
                )
            }

            override fun onAccuracyChanged(s: Sensor?, accuracy: Int) = Unit
        }
        sm.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_GAME)
        onDispose { sm.unregisterListener(listener) }
    }
}