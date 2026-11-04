package com.example.myapplication.domain.guia

import com.example.myapplication.domain.ruta.Giro
import com.example.myapplication.domain.ruta.Instruccion
import com.example.myapplication.domain.ruta.Instrucciones
import com.example.myapplication.domain.ruta.TipoInstruccion

/** Lo que hay que decir al avanzar por la ruta. */
sealed interface Anuncio {
    val texto: String

    /** «En N metros, gira a la derecha.» (una vez por maniobra, a [ParametrosGuia.avisoPrevioM]). */
    data class Previo(val indice: Int, override val texto: String) : Anuncio

    /** La instrucción completa al llegar a la maniobra (a [ParametrosGuia.enManiobraM] o menos). */
    data class Maniobra(val indice: Int, override val texto: String) : Anuncio

    /** Fin de la ruta (a [ParametrosGuia.llegadaM] o menos): el texto de la instrucción de llegada. */
    data class Llegada(override val texto: String) : Anuncio
}

/**
 * Cuándo anunciar cada maniobra (FE-5.3; `AnunciadorTest`). La instrucción 0 (la salida) la dice la guía al empezar;
 * desde la 1, cada una se anuncia como mucho dos veces: un aviso previo a [ParametrosGuia.avisoPrevioM] y la
 * instrucción completa al llegar. Si la posición salta por encima de varias maniobras (una foto la corrige), solo se
 * dice la última alcanzada. Tras decir una maniobra, el aviso previo de la siguiente se omite si ya está a menos de
 * [ParametrosGuia.avisoPrevioM] (la instrucción dicha ya da sus metros). Retroceder no repite nada.
 */
class Anunciador(
    private val instrucciones: List<Instruccion>,
    private val destino: String,
    private val p: ParametrosGuia = ParametrosGuia(),
) {
    /** Índice de la próxima maniobra por anunciar (la 0 se dice al empezar). */
    var siguiente: Int = 1
        private set

    /** Índice de la última instrucción dicha (0 al empezar). */
    var ultimaDicha: Int = 0
        private set

    private val previosDichos = mutableSetOf<Int>()

    val llegado: Boolean get() = siguiente >= instrucciones.size

    fun alAvanzar(avanceM: Double): List<Anuncio> {
        var alcanzada: Anuncio? = null
        while (siguiente < instrucciones.size) {
            val ins = instrucciones[siguiente]
            val falta = ins.desdeM - avanceM
            val umbral = if (ins.tipo == TipoInstruccion.LLEGADA) p.llegadaM else p.enManiobraM
            if (falta > umbral) break
            alcanzada = if (ins.tipo == TipoInstruccion.LLEGADA) Anuncio.Llegada(ins.texto) else Anuncio.Maniobra(siguiente, ins.texto)
            ultimaDicha = siguiente
            siguiente++
        }
        if (alcanzada != null) {
            // La instrucción completa ya dice los metros hasta la siguiente: sin aviso previo si está cerca.
            if (siguiente < instrucciones.size && instrucciones[siguiente].desdeM - avanceM <= p.avisoPrevioM) {
                previosDichos += siguiente
            }
            return listOf(alcanzada)
        }
        if (siguiente < instrucciones.size && siguiente !in previosDichos) {
            val ins = instrucciones[siguiente]
            val falta = ins.desdeM - avanceM
            if (falta <= p.avisoPrevioM) {
                previosDichos += siguiente
                return listOf(Anuncio.Previo(siguiente, TextosGuia.previo(ins, falta, destino)))
            }
        }
        return emptyList()
    }

    /** «Repetir instrucción»: cuánto falta hasta la próxima maniobra y qué hacer allí (o la llegada). */
    fun repetir(avanceM: Double): String {
        if (siguiente >= instrucciones.size) return instrucciones.last().texto
        val ins = instrucciones[siguiente]
        return TextosGuia.proxima(ins, ins.desdeM - avanceM, destino)
    }
}

/** Textos de la guía hablada (FE-5.3). Los de las instrucciones salen de `Instrucciones` (FE-5.1). */
object TextosGuia {
    const val RECALCULANDO = "Te alejaste de la ruta. Recalculando."
    const val SIN_RECALCULO = "Te alejaste de la ruta y no encontré otro camino. Vuelve hacia atrás."
    const val SIN_CONEXION = "Sin conexión: sigo con tus pasos; la precisión puede bajar."
    const val SERVICIO_NO_DISPONIBLE =
        "El servicio de fotos no está disponible: sigo con tus pasos; la precisión puede bajar."
    const val SIN_UBICACION = "No tengo tu ubicación. Vuelve a ubicarte con la vuelta de 360 grados."
    const val SIN_RUTA = "No encontré un camino hasta tu destino."
    const val RUTAS_DESACTIVADAS = "Las rutas están desactivadas: el grafo de caminos no es válido."
    const val TERMINADA = "Guía terminada."

    /** Al empezar: cómo llevar el teléfono, el destino y la primera instrucción. */
    fun inicio(destino: String, metros: Double, primera: String): String =
        "$COMO_LLEVAR_EL_TELEFONO Vamos a $destino, a ${Instrucciones.metrosTexto(metros)} por el camino. $primera"

    /** Tras recalcular: el aviso y la nueva primera instrucción. */
    fun recalculada(primera: String): String = "$RECALCULANDO $primera"

    /** «gira a la derecha», «date la vuelta», «llegas a X»…: lo que se hace en la maniobra, en minúscula. */
    fun accion(ins: Instruccion, destino: String): String = when (ins.tipo) {
        TipoInstruccion.LLEGADA -> "llegas a $destino"
        else -> when (ins.giro) {
            Giro.RECTO, null -> "llegas al camino; sigue recto"
            Giro.LEVE -> "gira levemente a la ${ins.lado.texto}"
            Giro.NORMAL -> "gira a la ${ins.lado.texto}"
            Giro.CERRADO -> "gira cerrado a la ${ins.lado.texto}"
            Giro.VUELTA -> "date la vuelta"
        }
    }

    /** Aviso previo: «En 10 metros, gira a la derecha.». */
    fun previo(ins: Instruccion, faltaM: Double, destino: String): String =
        "En ${Instrucciones.metrosTexto(faltaM)}, ${accion(ins, destino)}."

    /** «Repetir instrucción»: «Sigue 12 metros; después, gira a la derecha.». */
    fun proxima(ins: Instruccion, faltaM: Double, destino: String): String =
        "Sigue ${Instrucciones.metrosTexto(faltaM)}; después, ${accion(ins, destino)}."
}
