package com.example.myapplication.domain.guia

/**
 * Datos de prueba de la guía (6.5), **solo en el APK de depuración** (FE-5.3; como `PruebaMapa` de FE-5.1, ADR-FE-38):
 * los escribe `MainActivity` al arrancar con `--es ruta guia` y los extras `destino_prueba`, `posicion_prueba` y
 * `simular_pasos`; los lee `NavegacionViewModel` y los borra al salir. El flujo real nunca los escribe.
 *
 * - [destino]: el `lugar` de un nodo del grafo (comparado normalizado: `bloque35`) o `"lat,lng"`.
 * - [posicion]: la posición inicial en lugar de la de «Ubicarme».
 * - [simulacion]: si no es `null`, los pasos los simula [SimuladorPasos] (sin sensores) a lo largo de la ruta.
 */
object PruebaGuia {
    @Volatile
    var destino: String? = null

    @Volatile
    var posicion: Pair<Double, Double>? = null

    @Volatile
    var simulacion: Simulacion? = null

    val activa: Boolean get() = destino != null && posicion != null

    /** Un paso de [pasoM] metros cada [intervaloMs] milisegundos. */
    data class Simulacion(val pasoM: Double, val intervaloMs: Long)

    /** `"0.7,500"` → 0,7 m cada 500 ms; `"si"`, `"1"` o `"true"` → los valores por defecto; otra cosa → `null`. */
    fun leerSimulacion(texto: String?): Simulacion? {
        val t = texto?.trim()?.lowercase() ?: return null
        if (t in setOf("si", "sí", "1", "true")) return Simulacion(PASO_DEFECTO_M, INTERVALO_DEFECTO_MS)
        val partes = t.split(',').map { it.trim() }
        if (partes.size != 2) return null
        val paso = partes[0].toDoubleOrNull()?.takeIf { it > 0.0 && it <= 5.0 } ?: return null
        val intervalo = partes[1].toLongOrNull()?.takeIf { it in 50L..10_000L } ?: return null
        return Simulacion(paso, intervalo)
    }

    /** [posicion] en `"lat,lng"` (con punto decimal); `null` si no son dos números en rango. */
    fun leerPosicion(texto: String?): Pair<Double, Double>? {
        val partes = texto?.split(',')?.map { it.trim() } ?: return null
        if (partes.size != 2) return null
        val lat = partes[0].toDoubleOrNull() ?: return null
        val lng = partes[1].toDoubleOrNull() ?: return null
        if (lat !in -90.0..90.0 || lng !in -180.0..180.0) return null
        return lat to lng
    }

    fun fijar(destino: String?, posicion: String?, simular: String?) {
        this.destino = destino?.trim()?.takeIf { it.isNotEmpty() }
        this.posicion = leerPosicion(posicion)
        this.simulacion = leerSimulacion(simular)
    }

    fun limpiar() {
        destino = null
        posicion = null
        simulacion = null
    }

    const val PASO_DEFECTO_M = 0.7
    const val INTERVALO_DEFECTO_MS = 500L
}

/**
 * Pasos simulados a lo largo de una ruta (modo de simulación de 6.5; `GuiaNavegacionTest`): cada [siguiente] avanza
 * [pasoM] metros por el trazado y devuelve la posición y los metros caminados. No sigue las correcciones de las fotos
 * (camina siempre por la ruta) y, si la guía recalcula, sigue por el trazado nuevo con [cambiarRuta].
 */
class SimuladorPasos(private var trazado: TrazadoRuta, private val pasoM: Double) {
    var caminadoM: Double = 0.0
        private set
    private var avance = 0.0

    data class Paso(val lat: Double, val lng: Double, val caminadoM: Double)

    fun siguiente(): Paso {
        avance += pasoM
        caminadoM += pasoM
        val (lat, lng) = trazado.puntoEn(avance)
        return Paso(lat, lng, caminadoM)
    }

    fun cambiarRuta(nuevo: TrazadoRuta) {
        trazado = nuevo
        avance = 0.0
    }
}
