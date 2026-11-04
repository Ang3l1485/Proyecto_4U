package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.ResultadoFrame
import com.example.myapplication.domain.ruta.Ruta
import com.example.myapplication.domain.usecase.Deriva
import kotlin.math.roundToInt

/** Lo que la guía pide hacer a quien la usa (el ViewModel de 6.5). */
sealed interface SalidaGuia {
    /**
     * Decir [texto]; [prioritario] = cortar lo que se esté diciendo (maniobras, recálculo, alerta alta); [vibrar] = es
     * una alerta (vibrar al decirla, como el mapa).
     */
    data class Hablar(val texto: String, val prioritario: Boolean = false, val vibrar: Boolean = false) : SalidaGuia

    /**
     * Tomar una foto y mandarla a `POST /v1/localize/frame` con `posicion_previa` = ([previaLat], [previaLng]),
     * [rumbo] (norte verdadero o `null`) y `radio_m` = [radioM]. [caminadoM]: metros caminados (PDR) al pedirla.
     * Al terminar, [GuiaNavegacion.alResponderFoto] o [GuiaNavegacion.alFallarFoto] con este mismo pedido.
     */
    data class TomarFoto(
        val previaLat: Double,
        val previaLng: Double,
        val rumbo: Double?,
        val radioM: Double,
        val caminadoM: Double,
    ) : SalidaGuia

    /** La foto se aceptó: mover el PDR a ([lat], [lng]) (`PdrTracker.fijarPosicion`). */
    data class CorregirPosicion(val lat: Double, val lng: Double) : SalidaGuia

    /** Se recalculó la ruta (para registrarlo o dibujarla). */
    data class RutaNueva(val ruta: Ruta) : SalidaGuia

    /** Se llegó: [texto] es la instrucción de llegada (con el tramo en línea recta si el destino queda lejos). */
    data class Llegada(val texto: String) : SalidaGuia
}

/** Por qué falló una foto de corrección (lo que no es una respuesta `200`). */
enum class FalloFrame(val clave: String) {
    SIN_CONEXION("sin_conexion"),
    SERVICIO_NO_DISPONIBLE("servicio_no_disponible"),
    FOTO_NO_VALIDA("foto_no_valida"),
    OTRO("otro"),
}

/** Lo que muestra 6.5 (y lee el validador en pantalla). */
data class EstadoGuia(
    val destino: String,
    val instruccion: String,
    val metrosRestantes: Double,
    val lat: Double,
    val lng: Double,
    val desvioM: Double,
    val fotosPedidas: Int,
    val fotosAceptadas: Int,
    val ultimaFoto: String?,
    val sinConexion: Boolean,
    val recalculos: Int,
    val llegado: Boolean,
)

/**
 * La guía por voz como máquina de estados pura (FE-5.3; `GuiaNavegacionTest`): recibe posiciones (del PDR o del modo de
 * simulación) y respuestas de fotos, y devuelve qué decir y qué hacer ([SalidaGuia]). No conoce Android, el TTS ni la
 * cámara.
 *
 * - **Posición:** la que llega en [alMoverse] (la del PDR, que arranca en la de «Ubicarme»). La **estimada** es su
 *   proyección sobre la ruta si está a ≤ [ParametrosGuia.desvioM]; si no, la misma posición.
 * - **Avisos:** [Anunciador] sobre el avance por la ruta ([TrazadoRuta]).
 * - **Desvío:** [DetectorDesvio]; al recalcular, [calcularRuta] desde la posición (no la estimada) con el rumbo actual.
 * - **Fotos:** [DisparadorFoto]; [ReglaMezcla] decide aceptar o descartar; una aceptada se pega a la ruta (si está a ≤
 *   [ParametrosGuia.desvioM]) y pide [SalidaGuia.CorregirPosicion].
 * - **Sin red / 503:** se avisa una vez cada caso en toda la guía y se sigue con los pasos.
 * - **Alertas:** [avisador] en cada posición estimada, con su incertidumbre = la de la última posición aceptada (la de
 *   «Ubicarme», [incertidumbreInicialM], o el `radio_m` de la foto) + `Deriva` (4 %) de lo caminado desde entonces; la
 *   primera alerta, si es alta, corta; las demás van en cola. Todas vibran.
 */
class GuiaNavegacion(
    private val calcularRuta: (lat: Double, lng: Double, rumbo: Double?) -> Ruta?,
    rutaInicial: Ruta,
    private val p: ParametrosGuia = ParametrosGuia(),
    private val avisador: AvisadorAlertasRuta = SinAvisosDeAlertas,
    caminadoInicialM: Double = 0.0,
    incertidumbreInicialM: Double = p.incertidumbreInicialM,
) {
    var ruta: Ruta = rutaInicial
        private set
    private var trazado = TrazadoRuta(rutaInicial)
    private var anunciador = Anunciador(rutaInicial.instrucciones, rutaInicial.destino, p)
    private val desvio = DetectorDesvio(p)
    private val disparador = DisparadorFoto(p, caminadoInicialM)

    private var avance = 0.0
    private var desvioM = 0.0
    private var lat = rutaInicial.puntos.first().lat
    private var lng = rutaInicial.puntos.first().lng
    private var estLat = lat
    private var estLng = lng
    private var caminado = caminadoInicialM
    private var caminadoAceptada = caminadoInicialM
    private var incertidumbreBase = incertidumbreInicialM
    private var rumbo: Double? = null
    private var instruccion = rutaInicial.primera.texto

    private var fotoEnCurso = false
    private var fotosPedidas = 0
    private var fotosAceptadas = 0
    private var ultimaFoto: String? = null
    private var avisadoSinConexion = false
    private var avisadoServicio = false
    private var sinConexion = false
    private var recalculos = 0
    var llegado = false
        private set

    /** Al empezar: cómo llevar el teléfono, el destino, la primera instrucción (y la llegada si ya está ahí). */
    fun empezar(): List<SalidaGuia> {
        val salida = mutableListOf<SalidaGuia>(
            SalidaGuia.Hablar(TextosGuia.inicio(ruta.destino, ruta.metros, ruta.primera.texto)),
        )
        anunciar(salida)
        return salida
    }

    /** Nueva posición ([lat], [lng]) con [caminadoM] metros caminados en total y [rumbo] (norte verdadero o `null`). */
    fun alMoverse(lat: Double, lng: Double, caminadoM: Double, rumbo: Double?): List<SalidaGuia> {
        if (llegado) return emptyList()
        this.lat = lat
        this.lng = lng
        this.caminado = caminadoM
        this.rumbo = rumbo
        val salida = mutableListOf<SalidaGuia>()
        proyectar(conAnterior = true)
        if (desvio.lectura(desvioM)) recalcular(salida)
        anunciar(salida)
        if (llegado) return salida
        avisador.avisos(estLat, estLng, incertidumbreM(), ruta).forEachIndexed { i, a ->
            salida += SalidaGuia.Hablar(a.texto, prioritario = i == 0 && a.alta, vibrar = true)
        }
        if (disparador.debeTomar(caminado, desvioM, fotoEnCurso)) {
            fotoEnCurso = true
            fotosPedidas++
            disparador.tomada(caminado)
            salida += SalidaGuia.TomarFoto(
                estLat, estLng, rumbo, ReglaMezcla.radioM(caminado - caminadoAceptada, p), caminado,
            )
        }
        return salida
    }

    /** Respuesta `200` de la foto [pedido]: la acepta (y corrige la posición) o la descarta. */
    fun alResponderFoto(pedido: SalidaGuia.TomarFoto, resultado: ResultadoFrame): List<SalidaGuia> {
        fotoEnCurso = false
        sinConexion = false
        if (llegado) return emptyList()
        val d = ReglaMezcla.decidir(
            resultado, pedido.caminadoM - caminadoAceptada, pedido.previaLat, pedido.previaLng, lat, lng, p,
        )
        return when (d) {
            is DecisionFrame.Descartar -> {
                ultimaFoto = "descartada (${d.motivo.clave})"
                emptyList()
            }
            is DecisionFrame.Aceptar -> {
                fotosAceptadas++
                caminadoAceptada = pedido.caminadoM
                (resultado as? ResultadoFrame.Ubicado)?.let { incertidumbreBase = it.radioM }
                val enRuta = trazado.proyectar(d.lat, d.lng, avance)
                val (nLat, nLng) = if (enRuta.desvioM <= p.desvioM) enRuta.lat to enRuta.lng else d.lat to d.lng
                ultimaFoto = "aceptada (${(resultado as? ResultadoFrame.Ubicado)?.distanciaPreviaM?.roundToInt() ?: 0} m)"
                listOf<SalidaGuia>(SalidaGuia.CorregirPosicion(nLat, nLng)) + alMoverse(nLat, nLng, caminado, rumbo)
            }
        }
    }

    /** La foto [pedido] no tuvo respuesta `200` (o no se envió). Sin red y `503` se avisan una vez cada uno. */
    fun alFallarFoto(@Suppress("UNUSED_PARAMETER") pedido: SalidaGuia.TomarFoto, fallo: FalloFrame): List<SalidaGuia> {
        fotoEnCurso = false
        ultimaFoto = "falló (${fallo.clave})"
        if (llegado) return emptyList()
        return when (fallo) {
            FalloFrame.SIN_CONEXION -> {
                sinConexion = true
                if (avisadoSinConexion) emptyList()
                else listOf(SalidaGuia.Hablar(TextosGuia.SIN_CONEXION)).also { avisadoSinConexion = true }
            }
            FalloFrame.SERVICIO_NO_DISPONIBLE ->
                if (avisadoServicio) emptyList()
                else listOf(SalidaGuia.Hablar(TextosGuia.SERVICIO_NO_DISPONIBLE)).also { avisadoServicio = true }
            FalloFrame.FOTO_NO_VALIDA, FalloFrame.OTRO -> emptyList()
        }
    }

    /** Incertidumbre de la posición (m): la de la última aceptada + la deriva de los pasos desde entonces. */
    fun incertidumbreM(): Double = incertidumbreBase + Deriva.estimar((caminado - caminadoAceptada).coerceAtLeast(0.0)).derivaM

    /** «Repetir instrucción». */
    fun repetir(): String = anunciador.repetir(avance)

    fun estado(): EstadoGuia = EstadoGuia(
        destino = ruta.destino,
        instruccion = instruccion,
        metrosRestantes = (trazado.largoM - avance).coerceAtLeast(0.0),
        lat = estLat,
        lng = estLng,
        desvioM = desvioM,
        fotosPedidas = fotosPedidas,
        fotosAceptadas = fotosAceptadas,
        ultimaFoto = ultimaFoto,
        sinConexion = sinConexion,
        recalculos = recalculos,
        llegado = llegado,
    )

    private fun proyectar(conAnterior: Boolean) {
        val pos = trazado.proyectar(lat, lng, if (conAnterior) avance else null)
        avance = pos.avanceM
        desvioM = pos.desvioM
        if (desvioM <= p.desvioM) {
            estLat = pos.lat
            estLng = pos.lng
        } else {
            estLat = lat
            estLng = lng
        }
    }

    private fun recalcular(salida: MutableList<SalidaGuia>) {
        val nueva = calcularRuta(lat, lng, rumbo)
        if (nueva == null) {
            salida += SalidaGuia.Hablar(TextosGuia.SIN_RECALCULO, prioritario = true)
            return
        }
        recalculos++
        ruta = nueva
        trazado = TrazadoRuta(nueva)
        anunciador = Anunciador(nueva.instrucciones, nueva.destino, p)
        desvio.reiniciar()
        avance = 0.0
        proyectar(conAnterior = false)
        instruccion = nueva.primera.texto
        salida += SalidaGuia.RutaNueva(nueva)
        salida += SalidaGuia.Hablar(TextosGuia.recalculada(nueva.primera.texto), prioritario = true)
    }

    private fun anunciar(salida: MutableList<SalidaGuia>) {
        for (a in anunciador.alAvanzar(avance)) {
            when (a) {
                is Anuncio.Llegada -> {
                    llegado = true
                    instruccion = a.texto
                    salida += SalidaGuia.Llegada(a.texto)
                }
                is Anuncio.Maniobra -> {
                    instruccion = a.texto
                    salida += SalidaGuia.Hablar(a.texto, prioritario = true)
                }
                is Anuncio.Previo -> {
                    instruccion = a.texto
                    salida += SalidaGuia.Hablar(a.texto)
                }
            }
        }
    }
}
