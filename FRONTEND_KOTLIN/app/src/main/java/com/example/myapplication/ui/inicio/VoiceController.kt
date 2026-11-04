package com.example.myapplication.ui.inicio

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.text.Normalizer
import java.util.Locale
import java.util.UUID

enum class Comando { UBICARME, IR_A_LUGAR, NINGUNO }

/** Interpreta lo que dijo la persona: "uno", "dos" y sinónimos. */
object ComandoParser {
    private fun normalizar(texto: String): String =
        Normalizer.normalize(texto.lowercase(Locale.ROOT), Normalizer.Form.NFD)
            .replace("\\p{Mn}+".toRegex(), "")

    fun parse(texto: String): Comando {
        val t = normalizar(texto)
        val palabras = t.split("\\s+".toRegex())

        val ubicar = "uno" in palabras || "1" in palabras ||
            "ubic" in t || "donde estoy" in t || "donde estamos" in t
        val ir = "dos" in palabras || "2" in palabras ||
            "ir a" in t || "llevar" in t || "lugar" in t || "destino" in t || "llegar" in t

        return when {
            ubicar && !ir -> Comando.UBICARME
            ir && !ubicar -> Comando.IR_A_LUGAR
            else -> Comando.NINGUNO
        }
    }
}

/** Envuelve TextToSpeech y SpeechRecognizer. Usar siempre desde el hilo principal. */
class VoiceController(private val context: Context) {

    private val main = Handler(Looper.getMainLooper())
    private var tts: TextToSpeech? = null
    private var ttsListo = false
    private var pendiente: (() -> Unit)? = null
    private var recognizer: SpeechRecognizer? = null
    private val locale = Locale("es", "CO")

    init {
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = locale
                ttsListo = true
                pendiente?.invoke()
                pendiente = null
            }
        }
    }

    fun speak(texto: String, alTerminar: () -> Unit = {}) {
        val accion = {
            val id = UUID.randomUUID().toString()
            tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = Unit
                override fun onDone(utteranceId: String?) {
                    if (utteranceId == id) main.post(alTerminar)
                }
                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) {
                    if (utteranceId == id) main.post(alTerminar)
                }
            })
            tts?.speak(texto, TextToSpeech.QUEUE_FLUSH, null, id)
            Unit
        }
        if (ttsListo) accion() else pendiente = accion
    }

    fun listen(onResult: (String) -> Unit, onFail: () -> Unit) {
        stopListening()
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            onFail()
            return
        }
        val r = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onResults(results: Bundle?) {
                val frases = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    .orEmpty()
                if (frases.isEmpty()) onFail() else onResult(frases.joinToString(" "))
            }
            override fun onError(error: Int) = onFail()
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-CO")
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }
        r.startListening(intent)
    }

    fun stopListening() {
        recognizer?.run {
            cancel()
            destroy()
        }
        recognizer = null
    }

    fun stopAll() {
        stopListening()
        tts?.stop()
    }

    fun release() {
        stopAll()
        tts?.shutdown()
        tts = null
    }
}