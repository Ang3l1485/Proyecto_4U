package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.Alerta
import com.example.myapplication.domain.ruta.Geo
import kotlin.math.roundToInt

/**
 * Una alerta que alcanza a la persona: [distanciaM] = de la posición al punto de la alerta, en línea recta (haversine).
 * [alta]: prioridad `alta` (interrumpe la voz en curso; ARCHITECTURE §2.5).
 */
data class AlertaCercana(val alerta: Alerta, val distanciaM: Double) {
    val alta: Boolean get() = alerta.prioridad == DetectarAlertasCercanas.PRIORIDAD_ALTA
}

/**
 * Qué alertas alcanzan a la persona (FE-3.6, ARCHITECTURE §2.5 y §5.7). Lógica pura, sin estado ni Android:
 * `DetectarAlertasCercanasTest`. Una alerta alcanza si está activa, es vigente en [ahoraMs] (desde nula o pasada, hasta
 * nula o futura, backend §5.3), pasa el filtro `incluir` y su distancia es ≤ `radio + incertidumbre`.
 *
 * La usan la vista 6.3 (todas las cercanas a la posición estimada, una vez), el mapa público y, en FE-5.3, la guía por
 * voz, a través de [SeguimientoAlertas] (una vez por aproximación). Para anunciar solo las cercanas a la ruta (decisión
 * abierta 3) basta con pasar `incluir`.
 */
object DetectarAlertasCercanas {

    const val PRIORIDAD_ALTA = "alta"

    /** Activa y dentro de su vigencia: `vigenciaDesdeMs` nula o ≤ [ahoraMs], y `vigenciaHastaMs` nula o > [ahoraMs]. */
    fun vigente(alerta: Alerta, ahoraMs: Long): Boolean =
        alerta.activa &&
            (alerta.vigenciaDesdeMs?.let { it <= ahoraMs } ?: true) &&
            (alerta.vigenciaHastaMs?.let { it > ahoraMs } ?: true)

    /** Distancia que dispara la alerta: su radio más la incertidumbre de la posición (negativa cuenta como 0). */
    fun umbralM(alerta: Alerta, incertidumbreM: Double): Double = alerta.radio + incertidumbreM.coerceAtLeast(0.0)

    /**
     * Las alertas de [alertas] que alcanzan (lat, lng) con [incertidumbreM] (m), ordenadas: las de prioridad alta
     * primero, después por distancia y, a igualdad, por id. Sin estado: llamar otra vez da lo mismo.
     */
    fun cercanas(
        alertas: List<Alerta>,
        lat: Double,
        lng: Double,
        incertidumbreM: Double,
        ahoraMs: Long,
        incluir: (Alerta) -> Boolean = { true },
    ): List<AlertaCercana> =
        alertas.asSequence()
            .distinctBy { it.id }
            .filter { vigente(it, ahoraMs) && incluir(it) }
            .map { AlertaCercana(it, Geo.distancia(lat, lng, it.lat, it.lng)) }
            .filter { it.distanciaM <= umbralM(it.alerta, incertidumbreM) }
            .sortedWith(ORDEN)
            .toList()

    /** Alta primero, después la más cercana, después por id (orden estable para las pruebas). */
    val ORDEN: Comparator<AlertaCercana> =
        compareBy<AlertaCercana>({ !it.alta }, { it.distanciaM }, { it.alerta.id })

    /** Texto que se dice y se muestra: el mensaje del admin tal cual (§2.5), recortado y con punto final si no lo trae. */
    fun texto(alerta: Alerta): String {
        val m = alerta.mensaje.trim()
        return if (m.isEmpty() || m.last() in ".!?…") m else "$m."
    }

    /**
     * Línea del registro de una alerta anunciada, tag `AlertasPublicas` (la lee `validate36.py`; no cambiar su forma sin
     * cambiar `PATRON_ANUNCIADA`): `Alerta anunciada (<donde>): <id> a <d> m (radio <r> m, incertidumbre <i> m,
     * <prioridad>)`, con metros enteros; [donde] = `resultado` (6.3) o `mapa`. Sin el mensaje.
     */
    fun lineaAnunciada(donde: String, a: AlertaCercana, incertidumbreM: Double): String =
        "Alerta anunciada ($donde): ${a.alerta.id} a ${a.distanciaM.roundToInt()} m (radio ${a.alerta.radio} m, " +
            "incertidumbre ${incertidumbreM.coerceAtLeast(0.0).roundToInt()} m, ${a.alerta.prioridad})"
}

/**
 * Parámetros de [SeguimientoAlertas] (valores de partida, a ajustar en el campo con FE-5.3).
 * - [margenSalidaM]: una aproximación termina cuando la distancia pasa de `radio + incertidumbre + margenSalidaM`
 *   (histéresis: caminar por el borde del radio no la repite).
 * - [esperaRepetirMs]: tras anunciar una alerta, no se vuelve a anunciar antes de este tiempo aunque se salga y se
 *   vuelva a entrar.
 */
data class ParametrosAlertas(
    val margenSalidaM: Double = 5.0,
    val esperaRepetirMs: Long = 120_000L,
)

/**
 * «Una vez por aproximación» (ARCHITECTURE §2.5): recuerda qué alertas ya alcanzan a la persona y en cada posición
 * devuelve solo las que hay que anunciar **ahora** (las que empiezan una aproximación). Lógica pura, sin Android ni
 * hilos (usarla desde un solo hilo); una instancia por pantalla o por recorrido.
 *
 * Reglas, para cada alerta vigente que pasa `incluir`, con `u = radio + incertidumbre`:
 * - `d ≤ u` y no estaba dentro → entra; se anuncia si nunca se anunció o si pasaron `esperaRepetirMs` desde el último
 *   aviso (si no, entra en silencio).
 * - `d > u + margenSalidaM` → sale (la próxima entrada es otra aproximación).
 * - entre `u` y `u + margenSalidaM` → sigue como estaba.
 * Una alerta que deja de estar en la lista, de ser vigente o de pasar `incluir` sale. El resultado va en el orden de
 * [DetectarAlertasCercanas.ORDEN] (alta primero): quien anuncia interrumpe la voz con la primera si es alta y encola
 * las demás.
 */
class SeguimientoAlertas(val parametros: ParametrosAlertas = ParametrosAlertas()) {

    private val dentro = mutableSetOf<String>()
    private val ultimoAviso = mutableMapOf<String, Long>()

    /** Ids de las alertas con una aproximación en curso (para pruebas y registros). */
    val enCurso: Set<String> get() = dentro.toSet()

    fun actualizar(
        alertas: List<Alerta>,
        lat: Double,
        lng: Double,
        incertidumbreM: Double,
        ahoraMs: Long,
        incluir: (Alerta) -> Boolean = { true },
    ): List<AlertaCercana> {
        val vistas = mutableSetOf<String>()
        val anunciar = mutableListOf<AlertaCercana>()
        for (a in alertas.distinctBy { it.id }) {
            if (!DetectarAlertasCercanas.vigente(a, ahoraMs) || !incluir(a)) continue
            vistas += a.id
            val d = Geo.distancia(lat, lng, a.lat, a.lng)
            val u = DetectarAlertasCercanas.umbralM(a, incertidumbreM)
            when {
                d <= u && a.id !in dentro -> {
                    dentro += a.id
                    val ultimo = ultimoAviso[a.id]
                    if (ultimo == null || ahoraMs - ultimo >= parametros.esperaRepetirMs) {
                        ultimoAviso[a.id] = ahoraMs
                        anunciar += AlertaCercana(a, d)
                    }
                }
                d > u + parametros.margenSalidaM -> dentro -= a.id
            }
        }
        dentro.retainAll(vistas)
        return anunciar.sortedWith(DetectarAlertasCercanas.ORDEN)
    }

    /** Olvida las aproximaciones y los avisos (p. ej. al fijar otro punto de partida a mano). */
    fun reiniciar() {
        dentro.clear()
        ultimoAviso.clear()
    }
}
