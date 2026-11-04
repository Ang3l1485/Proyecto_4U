package com.example.myapplication.domain.ruta

import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Parámetros de la ruta y de las instrucciones (FE-5.1). Son valores **de partida**: se ajustan en el campo con FE-5.3
 * (ARCHITECTURE §5.7, «Grafo y rutas», tabla de parámetros).
 *
 * - [fueraDelCaminoM]: si la persona está a más de esto de la arista más cercana, la primera instrucción la lleva al
 *   camino (tramo propio); si está más cerca, la ruta empieza en el punto proyectado. Del lado del destino: si el lugar
 *   queda a más de esto del grafo, la llegada dice cuánto falta en línea recta y hacia dónde.
 * - Ángulo entre un tramo y el siguiente (en valor absoluto): < [rectoMaxGrados] es «casi recto» (se junta con el
 *   anterior); < [leveMaxGrados], giro leve; < [normalMaxGrados], giro normal; < [vueltaMinGrados], giro cerrado; desde
 *   [vueltaMinGrados], «date la vuelta».
 * - [puntoRepetidoM]: dos puntos seguidos más cerca que esto se toman como uno (evita tramos de 0 m al proyectar
 *   justo sobre un nodo).
 */
data class ParametrosRuta(
    val fueraDelCaminoM: Double = 15.0,
    val rectoMaxGrados: Double = 20.0,
    val leveMaxGrados: Double = 45.0,
    val normalMaxGrados: Double = 120.0,
    val vueltaMinGrados: Double = 150.0,
    val puntoRepetidoM: Double = 0.5,
)

enum class Giro { RECTO, LEVE, NORMAL, CERRADO, VUELTA }

enum class Lado(val texto: String) { DERECHA("derecha"), IZQUIERDA("izquierda"), NINGUNO("") }

/** [IR_AL_CAMINO] (la persona está lejos del camino), [SALIDA] (primer tramo), [GIRO] (en un cruce), [LLEGADA]. */
enum class TipoInstruccion { IR_AL_CAMINO, SALIDA, GIRO, LLEGADA }

/**
 * Un punto de la polilínea de la ruta, con los metros desde el punto anterior (0 en el primero). Los metros son los
 * declarados en las aristas (o la distancia en línea recta en el tramo hasta el camino), así la suma da la longitud de
 * la ruta.
 */
data class PuntoRuta(val lat: Double, val lng: Double, val metrosDesdeAnterior: Double = 0.0)

/**
 * Una instrucción. [giro] y [lado]: la maniobra al empezar el tramo (en [SALIDA] e [IR_AL_CAMINO], respecto al rumbo de
 * la persona; `null` sin rumbo; en [LLEGADA], `null`). [metros]: largo del tramo que sigue (0 en la llegada). [desdeM]:
 * metros desde el inicio de la ruta hasta el punto de la maniobra ([lat], [lng]), para avisar antes del cruce (FE-5.3).
 * [texto]: la frase que se dice («Gira a la izquierda y sigue recto 25 metros.»).
 */
data class Instruccion(
    val tipo: TipoInstruccion,
    val giro: Giro?,
    val lado: Lado,
    val metros: Double,
    val desdeM: Double,
    val lat: Double,
    val lng: Double,
    val texto: String,
)

/**
 * Lo que falta desde el punto de llegada (en el grafo) hasta el destino cuando este queda lejos del grafo: sus
 * coordenadas y los metros en línea recta. Con ella, la llegada dice «Has llegado al punto del camino más cercano a X.
 * Está a N metros en línea recta, <dirección>.».
 */
data class Llegada(val lat: Double, val lng: Double, val metros: Double)

/**
 * Instrucciones de texto a partir de los ángulos entre tramos (FE-5.1; `InstruccionesTest`). Los tramos casi rectos se
 * juntan («sigue recto 40 metros»); la primera se da respecto al rumbo actual de la persona; la última es «Has llegado a
 * <destino>.».
 */
object Instrucciones {

    /** Clasifica un cambio de rumbo [grados] (en (−180, 180], positivo = a la derecha). */
    fun clasificar(grados: Double, p: ParametrosRuta = ParametrosRuta()): Pair<Giro, Lado> {
        val a = abs(grados)
        val giro = when {
            a < p.rectoMaxGrados -> Giro.RECTO
            a < p.leveMaxGrados -> Giro.LEVE
            a < p.normalMaxGrados -> Giro.NORMAL
            a < p.vueltaMinGrados -> Giro.CERRADO
            else -> Giro.VUELTA
        }
        val lado = when {
            giro == Giro.RECTO || giro == Giro.VUELTA -> Lado.NINGUNO
            grados > 0 -> Lado.DERECHA
            else -> Lado.IZQUIERDA
        }
        return giro to lado
    }

    /** «1 metro» o «N metros» (metros enteros, mínimo 1). */
    fun metrosTexto(m: Double): String {
        val n = m.roundToInt().coerceAtLeast(1)
        return if (n == 1) "1 metro" else "$n metros"
    }

    private class Tramo(val inicio: Int, val rumboInicial: Double, var rumboFinal: Double, var metros: Double, val giro: Double?)

    /**
     * [puntos]: la polilínea (sin puntos repetidos); [rumboActual]: hacia dónde mira la persona (norte verdadero) o
     * `null`; [alCamino]: el primer segmento es el de la persona hasta el camino (no se junta con el siguiente);
     * [destino]: el nombre que se dice al llegar; [llegada]: si el destino queda lejos del grafo, lo que falta desde el
     * último punto (la dirección se da respecto al último tramo o, sin tramos, a [rumboActual]).
     */
    fun generar(
        puntos: List<PuntoRuta>,
        rumboActual: Double?,
        alCamino: Boolean,
        destino: String,
        p: ParametrosRuta = ParametrosRuta(),
        llegada: Llegada? = null,
    ): List<Instruccion> {
        val fin = puntos.lastOrNull() ?: return emptyList()
        val tramos = mutableListOf<Tramo>()
        for (i in 0 until puntos.size - 1) {
            val a = puntos[i]
            val b = puntos[i + 1]
            val largo = b.metrosDesdeAnterior
            val rumbo = Geo.rumbo(a.lat, a.lng, b.lat, b.lng)
            val ultimo = tramos.lastOrNull()
            if (ultimo == null) {
                tramos += Tramo(i, rumbo, rumbo, largo, null)
                continue
            }
            val giro = Geo.diferencia(rumbo, ultimo.rumboFinal)
            val esAcercamiento = alCamino && tramos.size == 1
            if (abs(giro) < p.rectoMaxGrados && !esAcercamiento) {
                ultimo.metros += largo
                ultimo.rumboFinal = rumbo
            } else {
                tramos += Tramo(i, rumbo, rumbo, largo, giro)
            }
        }

        val resultado = mutableListOf<Instruccion>()
        var desde = 0.0
        tramos.forEachIndexed { k, t ->
            val punto = puntos[t.inicio]
            val m = metrosTexto(t.metros)
            if (k == 0) {
                val (giro, lado) = rumboActual?.let { clasificar(Geo.diferencia(t.rumboInicial, it), p) }
                    ?: (null to Lado.NINGUNO)
                val salida = giro?.let { fraseSalida(it, lado) }
                val (tipo, texto) = if (alCamino) {
                    TipoInstruccion.IR_AL_CAMINO to
                        if (salida == null) "Ve hasta el camino más cercano, a $m."
                        else "Ve hasta el camino más cercano: ${salida.replaceFirstChar { it.lowercase() }} $m."
                } else {
                    TipoInstruccion.SALIDA to if (salida == null) "Camina $m por el camino." else "$salida $m."
                }
                resultado += Instruccion(tipo, giro, lado, t.metros, desde, punto.lat, punto.lng, texto)
            } else {
                val (giro, lado) = clasificar(t.giro ?: 0.0, p)
                resultado += Instruccion(
                    TipoInstruccion.GIRO, giro, lado, t.metros, desde, punto.lat, punto.lng,
                    "${fraseGiro(giro, lado)} $m.",
                )
            }
            desde += t.metros
        }
        val textoLlegada = if (llegada == null) {
            "Has llegado a $destino."
        } else {
            val mirando = tramos.lastOrNull()?.rumboFinal ?: rumboActual
            val donde = mirando?.let {
                ", " + direccionRelativa(Geo.diferencia(Geo.rumbo(fin.lat, fin.lng, llegada.lat, llegada.lng), it))
            }.orEmpty()
            "Has llegado al punto del camino más cercano a $destino. Está a ${metrosTexto(llegada.metros)} en línea recta$donde."
        }
        resultado += Instruccion(TipoInstruccion.LLEGADA, null, Lado.NINGUNO, 0.0, desde, fin.lat, fin.lng, textoLlegada)
        return resultado
    }

    /** Sectores de 90° (como `DescribirUbicacion.direccion`): ±45° al frente, más de 135° detrás (bordes al frente y detrás). */
    fun direccionRelativa(grados: Double): String {
        val a = abs(grados)
        return when {
            a <= 45.0 -> "al frente"
            a >= 135.0 -> "detrás de ti"
            grados > 0 -> "a tu derecha"
            else -> "a tu izquierda"
        }
    }

    /** Primera instrucción, respecto a hacia dónde mira la persona («Gira a tu derecha y sigue recto»). */
    private fun fraseSalida(giro: Giro, lado: Lado): String = when (giro) {
        Giro.RECTO -> "Sigue recto"
        Giro.LEVE -> "Gira levemente a tu ${lado.texto} y sigue recto"
        Giro.NORMAL -> "Gira a tu ${lado.texto} y sigue recto"
        Giro.CERRADO -> "Gira cerrado a tu ${lado.texto} y sigue recto"
        Giro.VUELTA -> "Date la vuelta y sigue recto"
    }

    /** Giro en un cruce, respecto al tramo anterior («Gira a la izquierda y sigue recto»). */
    private fun fraseGiro(giro: Giro, lado: Lado): String = when (giro) {
        Giro.RECTO -> "Sigue recto"
        Giro.LEVE -> "Gira levemente a la ${lado.texto} y sigue recto"
        Giro.NORMAL -> "Gira a la ${lado.texto} y sigue recto"
        Giro.CERRADO -> "Gira cerrado a la ${lado.texto} y sigue recto"
        Giro.VUELTA -> "Date la vuelta y sigue recto"
    }
}
