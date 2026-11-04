package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.domain.model.NivelConfianza
import com.example.myapplication.domain.model.ResultadoUbicacion
import com.example.myapplication.domain.model.UbicacionEstimada
import com.example.myapplication.domain.ruta.Planificador
import java.util.Locale
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

/** Dónde queda un lugar respecto a hacia dónde mira la persona (sectores de 90°). */
enum class DireccionRelativa(val texto: String) {
    AL_FRENTE("al frente"),
    A_LA_DERECHA("a tu derecha"),
    DETRAS("detrás de ti"),
    A_LA_IZQUIERDA("a tu izquierda"),
}

/**
 * Lo que la vista 6.3 muestra y dice de una ubicación.
 *
 * - [titulo]: texto principal grande («Estás cerca de Biblioteca Central»).
 * - [subtitulo]: la distancia al lugar cercano («A unos 12 metros»), o `null`.
 * - [detalles]: una frase por línea (referencias, destino y avisos), en el orden en que se dicen.
 * - [confianza]: «Confianza alta|media|baja», o `null` sin posición.
 * - [sugerirRepetir]: confianza baja, `sin_coincidencias` o sin ubicación: «Volver a ubicarme» va primero.
 * - [hablado]: todo junto, para `VoiceController.speak`.
 * - [coordenadas]: el punto estimado («Punto estimado: 6.20131, -75.57897»), o `null` sin posición. Solo se muestra
 *   (en letra pequeña, para verificar en el campus); no se dice.
 * - [alertas] (FE-3.6): el mensaje de cada alerta cercana a la posición estimada, en el orden en que se dicen (alta
 *   primero, después la más cercana); vacía sin posición o sin alertas. Se dicen **al final** de [hablado].
 */
data class DescripcionUbicacion(
    val titulo: String,
    val subtitulo: String?,
    val detalles: List<String>,
    val confianza: String?,
    val sugerirRepetir: Boolean,
    val hablado: String,
    val coordenadas: String? = null,
    val alertas: List<String> = emptyList(),
)

/**
 * Textos de la vista 6.3 (FE-3.2; ARCHITECTURE §5.7). Lógica pura: la prueba `DescribirUbicacionTest`.
 *
 * Direcciones relativas: `referencias[].rumbo_grados` es absoluto (backend §5.3); la dirección sale de compararlo con el
 * rumbo **corregido** de la persona = rumbo verdadero de la brújula + `correccion_rumbo_grados` (si viene). Sin rumbo de
 * la brújula se dice solo la distancia. El destino (FE-3.2, decisión del usuario del 2026-10-26: sin vista 6.5 hasta
 * FE-5.1) se describe igual, con la distancia y el rumbo en línea recta desde la posición estimada. Desde FE-5.1, si hay
 * un [Planificador] y el destino está en el grafo, se dice en cambio la distancia **por el camino** y la primera
 * instrucción de la ruta (respecto al rumbo corregido); fuera del grafo (o sin grafo válido), lo de antes.
 */
object DescribirUbicacion {

    const val LLEGARA_NAVEGACION = "La navegación guiada llegará en una próxima versión."

    /** FE-5.3: con ruta por el grafo, la 6.3 ofrece la guía (botón «Guiarme» y comando de voz). */
    const val GUIA_DISPONIBLE = "Toca «Guiarme» o di «guíame» para que te lleve."

    const val SIN_UBICACION = "No tengo una ubicación reciente"
    const val SIN_COINCIDENCIAS = "No reconocí este lugar"
    const val NINGUN_LUGAR_JUNTO = "No estás junto a ningún lugar conocido"
    const val NINGUN_LUGAR_CERCA = "No hay lugares conocidos cerca"
    const val POCO_SEGURA = "La ubicación no es segura: toca «Volver a ubicarme» para dar la vuelta otra vez."
    const val REPETIR_VUELTA = "Toca «Volver a ubicarme» y da la vuelta otra vez, despacio y con el celular vertical."

    /** FE-3.6: lo que se dice antes de los mensajes de las alertas cercanas (una o varias). */
    const val ALERTA_CERCANA = "Alerta cercana:"
    const val ALERTAS_CERCANAS = "Alertas cercanas:"

    /** Sector de [rumboAbsoluto] visto desde [rumboActual]: ±45° al frente, más de 135° detrás (los bordes, al frente y detrás). */
    fun direccion(rumboAbsoluto: Double, rumboActual: Double): DireccionRelativa {
        val d = ConversionRumbo.diferencia(rumboAbsoluto, rumboActual)
        return when {
            abs(d) <= 45.0 -> DireccionRelativa.AL_FRENTE
            abs(d) >= 135.0 -> DireccionRelativa.DETRAS
            d > 0 -> DireccionRelativa.A_LA_DERECHA
            else -> DireccionRelativa.A_LA_IZQUIERDA
        }
    }

    /** Rumbo inicial (círculo máximo) de (lat1, lng1) a (lat2, lng2), en [0, 360) con 0,1°. */
    fun rumboInicial(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val f1 = Math.toRadians(lat1)
        val f2 = Math.toRadians(lat2)
        val dl = Math.toRadians(lng2 - lng1)
        val y = sin(dl) * cos(f2)
        val x = cos(f1) * sin(f2) - sin(f1) * cos(f2) * cos(dl)
        return ConversionRumbo.normalizar(Math.toDegrees(atan2(y, x)))
    }

    /** «a unos 35 metros» (metros enteros; «a un metro» por debajo de 1,5 m). */
    fun metros(distanciaM: Double): String {
        val n = distanciaM.roundToInt()
        return if (n <= 1) "a un metro" else "a unos $n metros"
    }

    /** «Punto estimado: 6.20131, -75.57897» (5 decimales ≈ 1 m, con punto, en el orden latitud, longitud). */
    fun coordenadas(lat: Double, lng: Double): String =
        "Punto estimado: ${"%.5f".format(Locale.ROOT, lat)}, ${"%.5f".format(Locale.ROOT, lng)}"

    /** Rumbo corregido = [rumboBrujula] (verdadero) + [correccion]; `null` sin rumbo de la brújula. */
    fun rumboCorregido(rumboBrujula: Double?, correccion: Double?): Double? =
        rumboBrujula?.let { ConversionRumbo.normalizar(it + (correccion ?: 0.0)) }

    /**
     * [ubicacion] = la de `SesionDeNavegacion` (o `null`); [rumboBrujula] = rumbo **verdadero** sin corregir (el del
     * sensor en 6.3 o, sin lectura, el del final del escaneo); [destino] = el elegido en 6.4, o `null`; [planificador]
     * (FE-5.1) = el del grafo de la app, o `null` (sin rutas: solo la línea recta); [alertas] (FE-3.6) = las cercanas a
     * la posición estimada (`DetectarAlertasCercanas.cercanas`, ya ordenadas), que se dicen al final; sin posición se
     * ignoran.
     */
    fun describir(
        ubicacion: UbicacionEstimada?,
        rumboBrujula: Double?,
        destino: LugarDestino?,
        planificador: Planificador? = null,
        alertas: List<AlertaCercana> = emptyList(),
    ): DescripcionUbicacion {
        val resultado = ubicacion?.resultado
        return when (resultado) {
            null -> sinPosicion(SIN_UBICACION, listOf("Toca «Volver a ubicarme» para dar la vuelta."), destino)
            is ResultadoUbicacion.SinCoincidencias -> sinPosicion(SIN_COINCIDENCIAS, listOf(REPETIR_VUELTA), destino)
            is ResultadoUbicacion.Ubicado -> ubicado(resultado, rumboBrujula, destino, planificador, alertas)
        }
    }

    /** FE-3.6: «Alerta cercana: <mensaje>» o «Alertas cercanas: <m1> <m2>…»; vacío sin alertas. */
    fun habladoAlertas(textos: List<String>): String = when (textos.size) {
        0 -> ""
        1 -> "$ALERTA_CERCANA ${textos.first()}"
        else -> "$ALERTAS_CERCANAS ${textos.joinToString(" ")}"
    }

    private fun sinPosicion(titulo: String, avisos: List<String>, destino: LugarDestino?): DescripcionUbicacion {
        val detalles = avisos + listOfNotNull(
            destino?.let { "Para llevarte a ${it.nombre} primero necesito saber dónde estás." },
        )
        return DescripcionUbicacion(
            titulo = titulo,
            subtitulo = null,
            detalles = detalles,
            confianza = null,
            sugerirRepetir = true,
            hablado = (listOf("$titulo.") + detalles).joinToString(" "),
        )
    }

    private fun ubicado(
        u: ResultadoUbicacion.Ubicado,
        rumboBrujula: Double?,
        destino: LugarDestino?,
        planificador: Planificador?,
        alertas: List<AlertaCercana>,
    ): DescripcionUbicacion {
        val rumbo = rumboCorregido(rumboBrujula, u.correccionRumboGrados)
        val baja = u.nivel == NivelConfianza.BAJA
        val cercano = u.lugarCercano

        val titulo: String
        val subtitulo: String?
        val primera: String
        when {
            cercano != null -> {
                titulo = if (baja) "Puede que estés cerca de ${cercano.nombre}" else "Estás cerca de ${cercano.nombre}"
                subtitulo = metros(cercano.distanciaM).replaceFirstChar { it.uppercase() }
                primera = "$titulo, ${metros(cercano.distanciaM)}."
            }
            u.referencias.isNotEmpty() -> {
                // Backend §5.3: sin `lugar_cercano`, la primera referencia es el lugar más cercano (a más de 60 m).
                titulo = NINGUN_LUGAR_JUNTO
                subtitulo = null
                primera = "$titulo."
            }
            else -> {
                titulo = NINGUN_LUGAR_CERCA
                subtitulo = null
                primera = "$titulo."
            }
        }

        val detalles = mutableListOf<String>()
        for (r in u.referencias) {
            val donde = rumbo?.let { "${direccion(r.rumboGrados, it).texto}, " }.orEmpty()
            detalles += "${r.nombre} está $donde${metros(r.distanciaM)}."
        }
        if (baja) detalles += POCO_SEGURA
        val p = u.posicion
        val ruta = destino?.let { planificador?.rutaA(it, p.lat, p.lng, rumbo) }
        if (destino != null && ruta != null) {
            // FE-5.1: distancia por el camino y primera instrucción (respecto al rumbo corregido).
            detalles += "Tu destino, ${destino.nombre}, está ${metros(ruta.metros)} por el camino."
            detalles += ruta.primera.texto
            // FE-5.1: si el lugar queda lejos del grafo (más de fueraDelCaminoM), el tramo final en línea recta.
            if (ruta.destinoLejos) {
                detalles += "Desde el camino, ${destino.nombre} queda ${metros(ruta.metrosAlDestino)} en línea recta."
            }
            detalles += GUIA_DISPONIBLE
        } else if (destino != null) {
            val d = CalibracionPaso.distanciaEntre(p.lat, p.lng, destino.lat, destino.lng)
            val donde = rumbo?.let {
                "${direccion(rumboInicial(p.lat, p.lng, destino.lat, destino.lng), it).texto}, "
            }.orEmpty()
            detalles += "Tu destino, ${destino.nombre}, está $donde${metros(d)}."
            detalles += LLEGARA_NAVEGACION
        }
        val confianza = "Confianza ${u.nivel.etiqueta}"
        // Orden hablado: dónde está, referencias, confianza, aviso de confianza baja, destino (o ruta, FE-5.1) y, al
        // final, las alertas cercanas (FE-3.6).
        val referencias = detalles.take(u.referencias.size)
        val resto = detalles.drop(u.referencias.size)
        val textosAlertas = alertas.map { DetectarAlertasCercanas.texto(it.alerta) }
        val hablado = (listOf(primera) + referencias + "$confianza." + resto + habladoAlertas(textosAlertas))
            .filter { it.isNotEmpty() }
            .joinToString(" ")
        return DescripcionUbicacion(
            titulo, subtitulo, detalles, confianza, baja, hablado,
            coordenadas = coordenadas(u.posicion.lat, u.posicion.lng),
            alertas = textosAlertas,
        )
    }
}
