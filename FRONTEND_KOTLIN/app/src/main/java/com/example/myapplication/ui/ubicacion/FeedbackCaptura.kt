package com.example.myapplication.ui.ubicacion

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator

/**
 * Confirmación multimodal de cada foto aceptada: vibración corta + pitido.
 * Pensado para usuarios ciegos, que no ven la pantalla.
 *
 * Llamar a [liberar] cuando ya no se use (p. ej. en `onCleared` del ViewModel).
 */
internal class FeedbackCaptura(private val ctx: Context) {

    // Si el dispositivo no puede crear el generador de tonos, simplemente no suena.
    private val tono: ToneGenerator? =
        runCatching { ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80) }.getOrNull()

    @Suppress("DEPRECATION")
    fun confirmar() {
        val v = ctx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            v?.vibrate(VibrationEffect.createOneShot(120, VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            v?.vibrate(120)
        }
        tono?.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
    }

    fun liberar() {
        tono?.release()
    }
}