package com.example.myapplication.domain.guia

/**
 * Cola de lo que dice la guía (FE-5.3; `ColaVozTest`). `VoiceController.speak` corta lo anterior (`QUEUE_FLUSH`), así
 * que sin cola un aviso taparía a otro. Un texto normal espera a que termine el actual; uno **prioritario** vacía la cola
 * y se dice ya (corta el actual). Como mucho [maximo] textos en espera (se pierde el más viejo).
 *
 * [hablar] dice un texto y llama a su segundo argumento al terminar (o al fallar), como `VoiceController.speak`. Un
 * `alTerminar` de un texto ya cortado se ignora (token).
 */
class ColaVoz(private val hablar: (String, () -> Unit) -> Unit, private val maximo: Int = 3) {
    private val espera = ArrayDeque<String>()
    private var token = 0
    var hablando: Boolean = false
        private set

    fun decir(texto: String, prioritario: Boolean = false) {
        if (prioritario) {
            espera.clear()
            ya(texto)
        } else if (!hablando) {
            ya(texto)
        } else {
            if (espera.size >= maximo) espera.removeFirst()
            espera.addLast(texto)
        }
    }

    /** Calla y olvida lo pendiente (Terminar, salir de la pantalla). */
    fun vaciar() {
        espera.clear()
        token++
        hablando = false
    }

    val pendientes: List<String> get() = espera.toList()

    private fun ya(texto: String) {
        hablando = true
        val t = ++token
        hablar(texto) {
            if (t == token) {
                hablando = false
                espera.removeFirstOrNull()?.let { ya(it) }
            }
        }
    }
}
