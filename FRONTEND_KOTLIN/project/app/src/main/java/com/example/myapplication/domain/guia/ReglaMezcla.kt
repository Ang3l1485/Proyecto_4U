package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.model.ResultadoFrame
import com.example.myapplication.domain.ruta.Ruta
import com.example.myapplication.domain.usecase.DetectarAlertasCercanas
import com.example.myapplication.domain.usecase.ParametrosAlertas
import com.example.myapplication.domain.usecase.SeguimientoAlertas

/** Por qué se descartó la posición de una foto. */
enum class MotivoDescarte(val clave: String) {
    SIN_COINCIDENCIAS("sin_coincidencias"),
    NIVEL_BAJO("nivel_bajo"),
    INCOHERENTE("incoherente"),
}

/** Qué hacer con la respuesta de `POST /v1/localize/frame`. */
sealed interface DecisionFrame {
    /** Reemplazar la posición por ([lat], [lng]); [limiteM]: el límite de coherencia que cumplió. */
    data class Aceptar(val lat: Double, val lng: Double, val limiteM: Double) : DecisionFrame

    data class Descartar(val motivo: MotivoDescarte, val limiteM: Double) : DecisionFrame
}

/**
 * Regla simple de mezcla de pasos y fotos (decisión del usuario del 2026-10-27; `ReglaMezclaTest`): los pasos mueven la
 * posición entre fotos y una foto confiable **y** coherente con lo caminado la reemplaza; si no, se descarta (una foto
 * equivocada no hace saltar la posición).
 */
object ReglaMezcla {

    /** Salto máximo admitido (m) tras [caminadoM] metros desde la última posición aceptada. */
    fun limiteCoherenciaM(caminadoM: Double, p: ParametrosGuia = ParametrosGuia()): Double =
        p.coherenciaBaseM + p.coherenciaPorMetro * caminadoM.coerceAtLeast(0.0)

    /** `radio_m` que se pide: el límite + [ParametrosGuia.margenRadioM], dentro de [radioMinM, radioMaxM]. */
    fun radioM(caminadoM: Double, p: ParametrosGuia = ParametrosGuia()): Double =
        (limiteCoherenciaM(caminadoM, p) + p.margenRadioM).coerceIn(p.radioMinM, p.radioMaxM)

    /**
     * [resultado]: la respuesta; [caminadoM]: metros caminados desde la última posición aceptada hasta el momento de la
     * foto; ([previaLat], [previaLng]): la `posicion_previa` enviada; ([actualLat], [actualLng]): la posición estimada
     * **ahora** (la persona siguió caminando mientras llegaba la respuesta).
     *
     * Al aceptar, la corrección se aplica como un desplazamiento: actual + (foto − previa); así no se pierden los pasos
     * dados durante la petición.
     */
    fun decidir(
        resultado: ResultadoFrame,
        caminadoM: Double,
        previaLat: Double,
        previaLng: Double,
        actualLat: Double,
        actualLng: Double,
        p: ParametrosGuia = ParametrosGuia(),
    ): DecisionFrame {
        val limite = limiteCoherenciaM(caminadoM, p)
        val u = resultado as? ResultadoFrame.Ubicado
            ?: return DecisionFrame.Descartar(MotivoDescarte.SIN_COINCIDENCIAS, limite)
        if (u.nivel !in p.nivelesAceptados) return DecisionFrame.Descartar(MotivoDescarte.NIVEL_BAJO, limite)
        if (u.distanciaPreviaM > limite) return DecisionFrame.Descartar(MotivoDescarte.INCOHERENTE, limite)
        return DecisionFrame.Aceptar(actualLat + (u.lat - previaLat), actualLng + (u.lng - previaLng), limite)
    }
}

/**
 * Cuándo tomar la foto de corrección (FE-5.3; `ReglaMezclaTest`): cada [ParametrosGuia.metrosEntreFotos] caminados
 * desde la anterior, o antes si la posición es dudosa (a más de [ParametrosGuia.dudosaM] de la ruta) y se caminó al
 * menos [ParametrosGuia.minMetrosEntreFotos]. Nunca con otra foto en curso.
 */
class DisparadorFoto(private val p: ParametrosGuia = ParametrosGuia(), inicioM: Double = 0.0) {
    private var ultimaM = inicioM

    fun debeTomar(caminadoM: Double, desvioM: Double, ocupado: Boolean): Boolean {
        if (ocupado) return false
        val desde = caminadoM - ultimaM
        return desde >= p.metrosEntreFotos || (desvioM >= p.dudosaM && desde >= p.minMetrosEntreFotos)
    }

    /** La foto se pidió con [caminadoM] metros caminados (cuenta aunque luego falle o se descarte). */
    fun tomada(caminadoM: Double) {
        ultimaM = caminadoM
    }
}

/**
 * Desvío: [ParametrosGuia.lecturasDesvio] lecturas seguidas a más de [ParametrosGuia.desvioM] de la ruta
 * (`GuiaNavegacionTest`). Una lectura cerca de la ruta reinicia la cuenta.
 */
class DetectorDesvio(private val p: ParametrosGuia = ParametrosGuia()) {
    var seguidas: Int = 0
        private set

    /** `true` cuando toca recalcular (y reinicia la cuenta). */
    fun lectura(desvioM: Double): Boolean {
        seguidas = if (desvioM > p.desvioM) seguidas + 1 else 0
        if (seguidas >= p.lecturasDesvio) {
            seguidas = 0
            return true
        }
        return false
    }

    fun reiniciar() {
        seguidas = 0
    }
}

/** Una alerta que hay que decir: [texto] (`DetectarAlertasCercanas.texto`) y si es de prioridad [alta]. */
data class AvisoAlerta(val texto: String, val alta: Boolean)

/**
 * Alertas cercanas durante la guía (FE-5.3): la guía lo llama en cada posición estimada (PDR o foto) con la incertidumbre
 * de esa posición y dice lo que devuelve: la primera, si es [AvisoAlerta.alta], cortando lo que se esté diciendo; las
 * demás, en cola. La implementación de la app es [AlertasEnRuta].
 */
fun interface AvisadorAlertasRuta {
    fun avisos(lat: Double, lng: Double, incertidumbreM: Double, ruta: Ruta): List<AvisoAlerta>
}

/** Sin alertas (pruebas, o si no se pudo leer la caché). */
object SinAvisosDeAlertas : AvisadorAlertasRuta {
    override fun avisos(lat: Double, lng: Double, incertidumbreM: Double, ruta: Ruta): List<AvisoAlerta> = emptyList()
}

/**
 * Alertas públicas de FE-3.6 en la guía (§4.12 «Para FE-5.3»; `AlertasEnRutaTest`): **una** [SeguimientoAlertas] por
 * guía (una vez por aproximación, con 5 m de margen de salida y 2 min antes de repetir) sobre la caché que da [alertas],
 * con `incluir` = la alerta está cerca de la ruta: su centro a ≤ `radio` + [ParametrosGuia.alertaRutaM] de la polilínea
 * de la ruta vigente ([TrazadoRuta]); así no se anuncian las de un camino paralelo aunque la incertidumbre crezca
 * (decisión abierta 3, propuesta de FE-5.3). [registrar] recibe la línea `DetectarAlertasCercanas.lineaAnunciada`
 * («Alerta anunciada (navegacion): …») de cada una.
 */
class AlertasEnRuta(
    private val alertas: () -> List<Alerta>,
    private val p: ParametrosGuia = ParametrosGuia(),
    private val ahoraMs: () -> Long = { System.currentTimeMillis() },
    private val registrar: (String) -> Unit = {},
) : AvisadorAlertasRuta {
    val seguimiento = SeguimientoAlertas(ParametrosAlertas(margenSalidaM = 5.0, esperaRepetirMs = 120_000L))
    private var trazado: TrazadoRuta? = null

    /** ¿La alerta [a] está cerca de la ruta de [t]? */
    fun cercaDeLaRuta(a: Alerta, t: TrazadoRuta): Boolean = t.proyectar(a.lat, a.lng).desvioM <= a.radio + p.alertaRutaM

    override fun avisos(lat: Double, lng: Double, incertidumbreM: Double, ruta: Ruta): List<AvisoAlerta> {
        val t = trazado?.takeIf { it.ruta === ruta } ?: TrazadoRuta(ruta).also { trazado = it }
        val cercanas = seguimiento.actualizar(alertas(), lat, lng, incertidumbreM, ahoraMs()) { cercaDeLaRuta(it, t) }
        return cercanas.map { a ->
            registrar(DetectarAlertasCercanas.lineaAnunciada(DONDE, a, incertidumbreM))
            AvisoAlerta(DetectarAlertasCercanas.texto(a.alerta), a.alta)
        }
    }

    companion object {
        /** El `donde` de la línea «Alerta anunciada (…)» (lo lee `validate36.py`, `PATRON_ANUNCIADA`). */
        const val DONDE = "navegacion"
    }
}
