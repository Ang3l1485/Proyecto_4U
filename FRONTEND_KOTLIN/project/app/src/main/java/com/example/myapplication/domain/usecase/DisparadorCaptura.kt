package com.example.myapplication.domain.usecase

/**
 * Lógica pura (sin Android) que decide cuándo tomar la siguiente foto automática en la
 * recolección (7.4) y estima la calidad del seguimiento. Se puede probar con tests unitarios.
 */

/** Intervalo de captura automática (ajuste rápido de 7.4). */
sealed interface ModoCaptura {
    /** Una foto cada `metros` recorridos. */
    data class PorDistancia(val metros: Double) : ModoCaptura

    /** Una foto cada `segundos`. */
    data class PorTiempo(val segundos: Int) : ModoCaptura

    /** Texto para la interfaz: "Cada 5 m" / "Cada 3 s". */
    val etiqueta: String
        get() = when (this) {
            is PorDistancia -> "Cada ${formatear(metros)} m"
            is PorTiempo -> "Cada $segundos s"
        }

    companion object {
        val POR_DEFECTO: ModoCaptura = PorDistancia(5.0)

        /** Opciones del selector de 7.4. */
        val OPCIONES: List<ModoCaptura> = listOf(
            PorDistancia(3.0),
            PorDistancia(5.0),
            PorDistancia(10.0),
            PorTiempo(3),
            PorTiempo(5),
        )

        private fun formatear(v: Double): String =
            if (v % 1.0 == 0.0) v.toInt().toString() else v.toString()
    }
}

/**
 * Decide si toca tomar una foto. No tiene reloj propio: quien lo usa le pasa la distancia
 * acumulada (`PdrEstado.distanciaMetros`) y la hora, y le avisa con [alCapturar] cuando la foto
 * **sí se guardó**.
 *
 * Cuidado: si la captura falla y no se llama a [alCapturar], [debeCapturar] seguirá devolviendo
 * `true` en el siguiente tick. Quien lo use debe poner su propia pausa tras un fallo (como hace
 * `EscaneoViewModel.onFotoFallida`).
 */
class DisparadorCaptura(modoInicial: ModoCaptura = ModoCaptura.POR_DEFECTO) {

    var modo: ModoCaptura = modoInicial
        private set

    private var ultimaDistanciaM: Double? = null
    private var ultimoTiempoMs: Long? = null

    /** La primera foto se toma de inmediato (el punto de partida también cuenta como cobertura). */
    fun debeCapturar(distanciaTotalM: Double, ahoraMs: Long): Boolean {
        val d0 = ultimaDistanciaM
        val t0 = ultimoTiempoMs
        if (d0 == null || t0 == null) return true
        return when (val m = modo) {
            is ModoCaptura.PorDistancia -> distanciaTotalM - d0 >= m.metros
            is ModoCaptura.PorTiempo -> ahoraMs - t0 >= m.segundos * 1000L
        }
    }

    /** Registrar que una foto se guardó correctamente. */
    fun alCapturar(distanciaTotalM: Double, ahoraMs: Long) {
        ultimaDistanciaM = distanciaTotalM
        ultimoTiempoMs = ahoraMs
    }

    /** Cambiar el intervalo no dispara una foto inmediata: cuenta desde la última. */
    fun cambiarModo(nuevo: ModoCaptura) {
        modo = nuevo
    }

    /** Tras una pausa, el tiempo en pausa no debe contar para el modo por tiempo. */
    fun alReanudar(ahoraMs: Long) {
        if (ultimoTiempoMs != null) ultimoTiempoMs = ahoraMs
    }

    fun reiniciar() {
        ultimaDistanciaM = null
        ultimoTiempoMs = null
    }
}

enum class NivelCalidad(val etiqueta: String) {
    ALTA("Alta"),
    MEDIA("Media"),
    BAJA("Baja"),
}

/** Estimación del error acumulado del PDR (indicador "Calidad del seguimiento" de 7.4). */
data class EstimacionDeriva(
    /** Error acumulado estimado desde el último ancla, en metros. */
    val derivaM: Double,
    /** Precisión mostrada como "± N m". */
    val precisionM: Double,
    val nivel: NivelCalidad,
)

/**
 * Heurística provisional: el PDR usa longitud de paso fija y brújula con deriva (decisión
 * abierta 16), así que se supone un error del 4 % de la distancia recorrida desde la última vez
 * que el admin fijó su posición a mano. Reemplazar por una medida real cuando exista la
 * corrección visual (`domain/fusion/`).
 */
object Deriva {
    const val FACTOR = 0.04
    const val UMBRAL_MEDIA_M = 15.0
    const val UMBRAL_BAJA_M = 30.0

    /** @param distanciaDesdeAnclaM metros recorridos desde la última posición fijada manualmente. */
    fun estimar(distanciaDesdeAnclaM: Double): EstimacionDeriva {
        val deriva = (distanciaDesdeAnclaM * FACTOR).coerceAtLeast(0.0)
        val nivel = when {
            deriva < UMBRAL_MEDIA_M -> NivelCalidad.ALTA
            deriva < UMBRAL_BAJA_M -> NivelCalidad.MEDIA
            else -> NivelCalidad.BAJA
        }
        return EstimacionDeriva(
            derivaM = deriva,
            precisionM = (deriva * 0.25).coerceAtLeast(1.0),
            nivel = nivel,
        )
    }
}