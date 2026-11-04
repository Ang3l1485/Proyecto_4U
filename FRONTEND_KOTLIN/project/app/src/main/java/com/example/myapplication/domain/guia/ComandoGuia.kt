package com.example.myapplication.domain.guia

import java.text.Normalizer
import java.util.Locale

/**
 * Comando de voz de 6.3 para empezar la guía (FE-5.3; `ComandoGuiaTest`): alguna palabra de [PALABRAS] en lo que
 * entendió el reconocimiento (sin tildes ni mayúsculas, palabras separadas por cualquier signo; `VoiceController.listen`
 * une hasta 3 hipótesis). «no» en el texto lo anula («no me guíes»).
 */
object ComandoGuia {
    val PALABRAS = setOf("guiame", "guiarme", "guia", "guiar", "llevame", "vamos", "empezar", "empieza", "comenzar")

    fun esGuiar(texto: String): Boolean {
        val limpio = Normalizer.normalize(texto.lowercase(Locale.ROOT), Normalizer.Form.NFD)
            .replace(Regex("\\p{Mn}+"), "")
        val palabras = limpio.split(Regex("[^a-z0-9ñ]+")).filter { it.isNotEmpty() }.toSet()
        if ("no" in palabras) return false
        return palabras.any { it in PALABRAS }
    }
}
