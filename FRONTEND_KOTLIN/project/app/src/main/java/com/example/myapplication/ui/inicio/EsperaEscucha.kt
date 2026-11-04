package com.example.myapplication.ui.inicio

/**
 * Cómo terminó un intento del reconocedor sin texto, o por qué todavía no se abrió el micrófono (0.19.0, decisión del
 * usuario del 2026-10-28). [clave] es lo que sale en `app.log` (tag `Escucha`). Solo los [reintentable] se vuelven a
 * escuchar en silencio dentro de la espera mínima; los demás (sin permiso de micrófono, red, audio, idioma…) fallan ya,
 * porque reintentarlos no cambia nada.
 */
enum class FinSinTexto(val clave: String, val reintentable: Boolean) {
    /** `SpeechRecognizer.ERROR_NO_MATCH`. */
    SIN_COINCIDENCIA("sin_coincidencia", true),

    /** `SpeechRecognizer.ERROR_SPEECH_TIMEOUT`. */
    TIEMPO_AGOTADO("tiempo_agotado", true),

    /** `onResults` sin ninguna frase. */
    RESULTADO_VACIO("resultado_vacio", true),

    /** `SpeechRecognizer.ERROR_RECOGNIZER_BUSY`: el reconocedor anterior aún no se soltó. */
    OCUPADO("ocupado", true),

    /** `SpeechRecognizer.ERROR_CLIENT`: fallo transitorio del lado de la app al empezar. */
    CLIENTE("cliente", true),

    /**
     * `TextToSpeech.isSpeaking` del `VoiceController` es `true` (lo responde el motor de TTS, quizá también por TalkBack):
     * no se abre el micrófono (captaría esa voz).
     */
    VOZ_HABLANDO("voz_hablando", true),

    /** Cualquier otro error del reconocedor. */
    OTRO("otro", false),
}

/**
 * Espera mínima de una escucha por voz (0.19.0; `EsperaEscuchaTest`). Una instancia por llamada a
 * `VoiceController.listen`: el reloj empieza al crearla. Si un intento termina sin texto **antes** de
 * [ESPERA_MINIMA_ESCUCHA_MS], [reintentar] dice que hay que volver a escuchar en silencio (tras
 * [PAUSA_REINTENTO_ESCUCHA_MS]); solo después cuenta como «no entendí». Como mucho [MAX_REINTENTOS_ESCUCHA] reintentos
 * (los que caben en la espera), así que no hay bucle infinito aunque el reconocedor falle al instante.
 *
 * [reloj] da milisegundos de un reloj monótono (en la app, `SystemClock.elapsedRealtime`); en las pruebas, uno falso.
 */
class EsperaEscucha(private val reloj: () -> Long) {
    private val inicioMs = reloj()

    /** Reintentos ya concedidos en esta escucha. */
    var reintentos: Int = 0
        private set

    fun transcurridoMs(): Long = reloj() - inicioMs

    /** `true` → volver a escuchar en silencio (y cuenta el reintento); `false` → la escucha termina en «no entendí». */
    fun reintentar(fin: FinSinTexto): Boolean {
        val si = debeReintentar(fin, transcurridoMs(), reintentos)
        if (si) reintentos++
        return si
    }

    companion object {
        /** Lo mínimo que se escucha antes de decir «no entendí» (decisión del usuario del 2026-10-28). */
        const val ESPERA_MINIMA_ESCUCHA_MS = 3_000L

        /** Pausa antes de cada reintento: deja que el reconocedor anterior se suelte (evita `ERROR_RECOGNIZER_BUSY`). */
        const val PAUSA_REINTENTO_ESCUCHA_MS = 300L

        /** Tope de reintentos: los que caben en la espera (`ESPERA_MINIMA_ESCUCHA_MS / PAUSA_REINTENTO_ESCUCHA_MS`). */
        const val MAX_REINTENTOS_ESCUCHA = 10

        /** La regla, sin estado: reintentable, antes de la espera mínima y sin pasar el tope. */
        fun debeReintentar(fin: FinSinTexto, transcurridoMs: Long, reintentosHechos: Int): Boolean =
            fin.reintentable &&
                transcurridoMs < ESPERA_MINIMA_ESCUCHA_MS &&
                reintentosHechos < MAX_REINTENTOS_ESCUCHA
    }
}
