package com.example.myapplication.ui.inicio

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import com.example.myapplication.logs.AppLog
import java.text.Normalizer
import java.util.Locale
import java.util.UUID

enum class Comando { UBICARME, IR_A_LUGAR, VER_MAPA, NINGUNO }

/** Interpreta lo que dijo la persona: "uno", "dos", "mapa" (FE-3.1) y sinónimos. */
object ComandoParser {
    private fun normalizar(texto: String): String =
        Normalizer.normalize(texto.lowercase(Locale.ROOT), Normalizer.Form.NFD)
            .replace("\\p{Mn}+".toRegex(), "")

    /** Palabras completas: desde FE-3.1 se separan también por signos («uno,» cuenta como «uno»). */
    private val separador = "[^\\p{L}\\p{N}]+".toRegex()

    fun parse(texto: String): Comando {
        val t = normalizar(texto)
        val palabras = t.split(separador).filter { it.isNotEmpty() }

        val ubicar = "uno" in palabras || "1" in palabras ||
            "ubic" in t || "donde estoy" in t || "donde estamos" in t
        val ir = "dos" in palabras || "2" in palabras ||
            "ir a" in t || "llevar" in t || "lugar" in t || "destino" in t || "llegar" in t
        // FE-3.1: la palabra completa «mapa» o «mapas» («ver el mapa», «abre el mapa»).
        val mapa = "mapa" in palabras || "mapas" in palabras

        val coinciden = listOf(ubicar, ir, mapa).count { it }
        return when {
            coinciden != 1 -> Comando.NINGUNO
            ubicar -> Comando.UBICARME
            ir -> Comando.IR_A_LUGAR
            else -> Comando.VER_MAPA
        }
    }
}

/**
 * Envuelve TextToSpeech y SpeechRecognizer. Usar siempre desde el hilo principal.
 *
 * [reloj] (0.19.0) mide la espera mínima de cada escucha ([EsperaEscucha]); milisegundos de un reloj monótono.
 */
class VoiceController(
    private val context: Context,
    private val reloj: () -> Long = { SystemClock.elapsedRealtime() },
) {

    private val main = Handler(Looper.getMainLooper())
    private var tts: TextToSpeech? = null
    private var ttsListo = false
    private val pendientes = mutableListOf<() -> Unit>()

    /** La escucha en curso (o la última terminada, hasta soltar su reconocedor). */
    private var escucha: Escucha? = null
    private val locale = Locale("es", "CO")

    init {
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = locale
                ttsListo = true
                val lista = pendientes.toList()
                pendientes.clear()
                lista.forEach { it() }
            }
        }
    }

    /** Dice [texto] cortando lo que se esté diciendo (`QUEUE_FLUSH`). Solo el último `speak` tiene [alTerminar]. */
    fun speak(texto: String, alTerminar: () -> Unit = {}) = decir(texto, encolar = false, alTerminar)

    /**
     * FE-3.6 (alertas de prioridad normal): dice [texto] cuando termine lo que se esté diciendo (`QUEUE_ADD`), sin
     * cortarlo. Si el TTS aún no está listo, se suma a lo pendiente (un [speak] lo reemplaza). Como [speak], solo el
     * último tiene [alTerminar].
     */
    fun speakEncolado(texto: String, alTerminar: () -> Unit = {}) = decir(texto, encolar = true, alTerminar)

    private fun decir(texto: String, encolar: Boolean, alTerminar: () -> Unit) {
        val modo = if (encolar) TextToSpeech.QUEUE_ADD else TextToSpeech.QUEUE_FLUSH
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
            tts?.speak(texto, modo, null, id)
            Unit
        }
        when {
            ttsListo -> accion()
            encolar -> pendientes += accion
            else -> { pendientes.clear(); pendientes += accion }
        }
    }

    /**
     * [onResult] recibe hasta 3 hipótesis unidas por espacio; con [soloMejor] (FE-3.3, dictado de 7.9), solo la primera
     * (la más probable). El valor por defecto deja el comportamiento de siempre (Inicio, Destino, Escaneo, Resultado).
     *
     * Desde 0.19.0 (decisión del usuario del 2026-10-28) escucha **al menos** `ESPERA_MINIMA_ESCUCHA_MS` (3 s): si el
     * reconocedor termina sin texto antes, vuelve a escuchar en silencio ([EsperaEscucha]) y solo después llama a
     * [onFail]. Nunca abre el micrófono mientras el TTS habla (`isSpeaking`). [stopListening], [stopAll],
     * [release] o otro `listen` cortan la escucha y sus reintentos (sin llamar a nada).
     */
    fun listen(onResult: (String) -> Unit, onFail: () -> Unit, soloMejor: Boolean = false) {
        stopListening()
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            AppLog.w(TAG, "Escucha: reconocimiento de voz no disponible")
            onFail()
            return
        }
        val e = Escucha(onResult, onFail, soloMejor, EsperaEscucha(reloj))
        escucha = e
        AppLog.i(TAG, "Escucha iniciada")
        e.intentar()
    }

    fun stopListening() {
        escucha?.soltar()
        escucha = null
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

    /**
     * Una llamada a [listen]: uno o varios intentos del reconocedor (uno nuevo por intento, como hacía cada `listen`)
     * hasta tener texto o cumplir la espera mínima. Un callback de un reconocedor que ya no es el vigente se ignora.
     */
    private inner class Escucha(
        private val onResult: (String) -> Unit,
        private val onFail: () -> Unit,
        private val soloMejor: Boolean,
        private val espera: EsperaEscucha,
    ) {
        /** `false` al terminar (texto o «no entendí») o al cortarla: desde entonces no llama a nada. */
        private var activa = true
        private var reconocedor: SpeechRecognizer? = null
        private val reintento = Runnable { intentar() }

        fun intentar() {
            if (!activa) return
            soltarReconocedor()
            if (tts?.isSpeaking == true) {
                sinTexto(FinSinTexto.VOZ_HABLANDO, null)
                return
            }
            val r = SpeechRecognizer.createSpeechRecognizer(context)
            reconocedor = r
            r.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    if (!activa || reconocedor !== r) return
                    val frases = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        .orEmpty()
                    if (frases.isEmpty()) {
                        sinTexto(FinSinTexto.RESULTADO_VACIO, null)
                    } else {
                        activa = false
                        AppLog.i(TAG, "Escucha terminada: texto a los ${espera.transcurridoMs()} ms (${espera.reintentos} reintentos)")
                        onResult(if (soloMejor) frases.first() else frases.joinToString(" "))
                    }
                }
                override fun onError(error: Int) {
                    if (!activa || reconocedor !== r) return
                    sinTexto(finDeError(error), error)
                }
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

        /** Un intento terminó sin texto: reintento en silencio (dentro de la espera mínima) o «no entendí». */
        private fun sinTexto(fin: FinSinTexto, codigo: Int?) {
            val ms = espera.transcurridoMs()
            val motivo = if (codigo == null) fin.clave else "${fin.clave}, error $codigo"
            if (espera.reintentar(fin)) {
                AppLog.i(TAG, "Escucha sin texto ($motivo) a los $ms ms: reintento ${espera.reintentos} en silencio")
                // El reconocedor viejo se suelta en `intentar`, fuera de su propio callback.
                main.postDelayed(reintento, EsperaEscucha.PAUSA_REINTENTO_ESCUCHA_MS)
            } else {
                activa = false
                AppLog.i(TAG, "Escucha terminada: no entendí a los $ms ms (${espera.reintentos} reintentos; $motivo)")
                onFail()
            }
        }

        /** Corta la escucha (si sigue activa) y suelta su reconocedor. No llama a [onResult] ni a [onFail]. */
        fun soltar() {
            if (activa) {
                activa = false
                AppLog.i(TAG, "Escucha cortada a los ${espera.transcurridoMs()} ms")
            }
            main.removeCallbacks(reintento)
            soltarReconocedor()
        }

        private fun soltarReconocedor() {
            reconocedor?.run {
                cancel()
                destroy()
            }
            reconocedor = null
        }
    }

    private companion object {
        /** Tag de `AppLog` de la escucha (0.19.0; §3.2). */
        const val TAG = "Escucha"

        fun finDeError(error: Int): FinSinTexto = when (error) {
            SpeechRecognizer.ERROR_NO_MATCH -> FinSinTexto.SIN_COINCIDENCIA
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> FinSinTexto.TIEMPO_AGOTADO
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> FinSinTexto.OCUPADO
            SpeechRecognizer.ERROR_CLIENT -> FinSinTexto.CLIENTE
            else -> FinSinTexto.OTRO
        }
    }
}