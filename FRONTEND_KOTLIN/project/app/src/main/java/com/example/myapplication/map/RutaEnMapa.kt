package com.example.myapplication.map

import com.example.myapplication.domain.ruta.Planificador
import com.example.myapplication.domain.ruta.ResultadoRuta
import kotlin.math.roundToInt

/**
 * Datos de prueba del mapa público (FE-5.1, ADR-FE-38). **Solo** los escribe `MainActivity` en el APK de depuración, en
 * un arranque nuevo y con la ruta de prueba `mapa` (`--es ruta mapa`): [destino] (`--es destino_prueba <texto>`:
 * `"<lat>,<lng>"` o el `lugar` informativo de un nodo del grafo, comparado normalizado, así `bloque35` vale por «Bloque
 * 35»; `Planificador.calcular(…, nombres, …)`) y [posicion]
 * (`--es posicion_prueba <lat>,<lng>`). El mapa usa [posicion] una vez como punto de partida (como un toque) y
 * [destino] en lugar del de `SesionDeNavegacion`; al salir del mapa se borran. El flujo real nunca los escribe.
 */
object PruebaMapa {
    @Volatile
    var destino: String? = null

    @Volatile
    var posicion: Pair<Double, Double>? = null

    /** `"6.201434,-75.578427"` → (lat, lng); `null` si no son dos números en rango. */
    fun leerPosicion(texto: String?): Pair<Double, Double>? {
        val partes = texto?.split(',')?.map { it.trim() } ?: return null
        if (partes.size != 2) return null
        val lat = partes[0].toDoubleOrNull() ?: return null
        val lng = partes[1].toDoubleOrNull() ?: return null
        if (lat !in -90.0..90.0 || lng !in -180.0..180.0) return null
        return lat to lng
    }

    fun fijar(destino: String?, posicion: String?) {
        this.destino = destino?.trim()?.takeIf { it.isNotEmpty() }
        this.posicion = leerPosicion(posicion)
    }

    fun limpiar() {
        destino = null
        posicion = null
    }
}

/** Lo que muestra el aviso de ruta del mapa público: [titulo] y, si hay ruta, la primera instrucción en [detalle]. */
data class AvisoRuta(val titulo: String, val detalle: String? = null)

/**
 * Textos del aviso de ruta del mapa público (FE-5.1; `RutaEnMapaTest`). Lógica pura.
 */
object TextosRutaMapa {

    const val RUTAS_DESACTIVADAS = "Rutas desactivadas: el grafo de caminos no es válido."

    /** «Ruta a Bloque 35: 60 m por el camino». */
    fun titulo(destino: String, metros: Double): String = "Ruta a $destino: ${metros.roundToInt()} m por el camino"

    /**
     * [destino]: el nombre que se muestra, o `null` sin destino (sin aviso); [rutasActivas]: hay grafo válido;
     * [hayPosicion]: el mapa ya tiene punto de partida; [resultado]: la ruta calculada (si hubo posición).
     */
    fun aviso(destino: String?, rutasActivas: Boolean, hayPosicion: Boolean, resultado: ResultadoRuta?): AvisoRuta? {
        if (destino == null) return null
        if (!rutasActivas) return AvisoRuta(RUTAS_DESACTIVADAS)
        if (!hayPosicion || resultado == null) {
            return AvisoRuta("Destino: $destino. Toca el mapa para fijar tu posición y ver la ruta.")
        }
        return when (resultado) {
            is ResultadoRuta.Encontrada -> AvisoRuta(titulo(destino, resultado.ruta.metros), resultado.ruta.primera.texto)
            ResultadoRuta.DestinoFueraDelGrafo -> AvisoRuta("No tengo un camino hasta $destino: no está en el grafo.")
            ResultadoRuta.SinCamino -> AvisoRuta("No encontré un camino hasta $destino.")
        }
    }

    /**
     * Nombre que se muestra para un destino de prueba: el `lugar` del primer nodo del grafo que casa, [DESTINO_DE_PRUEBA] si son
     * coordenadas, o el texto tal cual.
     */
    fun nombrePrueba(planificador: Planificador?, destino: String): String {
        planificador?.nodoConLugar(destino)?.lugar?.let { return it }
        return if (PruebaMapa.leerPosicion(destino) != null) DESTINO_DE_PRUEBA else destino
    }

    const val DESTINO_DE_PRUEBA = "Destino de prueba"
}
