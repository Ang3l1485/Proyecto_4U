package com.example.myapplication.domain.ruta

import com.example.myapplication.domain.model.LugarDestino
import com.google.gson.JsonArray
import com.google.gson.JsonObject

/**
 * Una ruta calculada desde la posición de la persona hasta el punto del grafo más cercano al destino.
 *
 * - [destino]: el nombre que se dice al llegar.
 * - [inicio]: el punto proyectado de la persona sobre la arista más cercana (nodo virtual de partida).
 * - [fin]: el punto proyectado **de las coordenadas del destino** sobre la arista más cercana (nodo virtual de llegada:
 *   la meta de la ruta).
 * - [metrosAlCamino]: distancia en línea recta de la persona a [inicio]; [fueraDelCamino] = mayor que
 *   [ParametrosRuta.fueraDelCaminoM] (la primera instrucción es [TipoInstruccion.IR_AL_CAMINO]).
 * - [metrosAlDestino]: distancia en línea recta de [fin] al destino; [destinoLejos] = mayor que
 *   [ParametrosRuta.fueraDelCaminoM] (la llegada dice cuánto falta y hacia dónde).
 * - [metros]: la distancia **por el camino** = metros del grafo de [inicio] a [fin] (+ [metrosAlCamino] si
 *   [fueraDelCamino]); **no** incluye [metrosAlDestino].
 * - [puntos]: polilínea para dibujar, desde la posición de la persona hasta [fin] (sin puntos repetidos).
 * - [instrucciones]: la primera ([primera]) es la que dice la vista 6.3; la última es la llegada.
 */
data class Ruta(
    val destino: String,
    val inicio: PuntoEnArista,
    val fin: PuntoEnArista,
    val metrosAlCamino: Double,
    val fueraDelCamino: Boolean,
    val metrosAlDestino: Double,
    val destinoLejos: Boolean,
    val metros: Double,
    val puntos: List<PuntoRuta>,
    val instrucciones: List<Instruccion>,
) {
    val primera: Instruccion get() = instrucciones.first()

    /**
     * JSON para el mapa (`window.onNativeRuta`, ARCHITECTURE §5.9): `{"destino": "…", "metros": 85.2,
     * "primera": "…", "puntos": [[lat, lng], …]}`.
     */
    fun json(): String {
        val o = JsonObject()
        o.addProperty("destino", destino)
        o.addProperty("metros", Math.round(metros * 10.0) / 10.0)
        o.addProperty("primera", primera.texto)
        val arr = JsonArray()
        for (p in puntos) {
            val par = JsonArray()
            par.add(p.lat)
            par.add(p.lng)
            arr.add(par)
        }
        o.add("puntos", arr)
        return o.toString()
    }
}

/**
 * [Encontrada]; [DestinoFueraDelGrafo]: el destino no tiene coordenadas válidas (o, con un destino por texto, no se
 * pudo resolver); [SinCamino]: no hay aristas usables o no se llega (aristas bloqueadas).
 */
sealed interface ResultadoRuta {
    data class Encontrada(val ruta: Ruta) : ResultadoRuta
    data object DestinoFueraDelGrafo : ResultadoRuta
    data object SinCamino : ResultadoRuta
}

/**
 * Fachada de FE-5.1 sobre un [Grafo] válido: proyección, ruta más corta e instrucciones (ARCHITECTURE §5.7, «Grafo y
 * rutas»; `PlanificadorTest`). Sin estado mutable: se puede llamar en cada paso.
 *
 * **La meta sale de las coordenadas del destino** (decisión del usuario del 2026-10-28: «cuando una persona quiera ir a
 * X, coge las coordenadas del lugar X (propias de la app) y asígnale el lugar más cercano dentro del grafo»): se proyectan
 * sobre la arista usable más cercana, como el inicio, y ese punto es la meta. Así cualquier lugar del backend tiene ruta;
 * el `lugar` de los nodos del grafo es solo informativo (lo usan los destinos de prueba por nombre del mapa).
 */
class Planificador(val grafo: Grafo, val parametros: ParametrosRuta = ParametrosRuta()) {

    /** El primer nodo cuyo `lugar` (informativo) casa, normalizado, con [nombre]; `null` si ninguno. */
    fun nodoConLugar(nombre: String): Nodo? {
        val clave = EmparejarLugares.normalizar(nombre)
        if (clave.isEmpty()) return null
        return grafo.nodos.firstOrNull { n -> n.lugar?.let { EmparejarLugares.normalizar(it) == clave } == true }
    }

    /** Ruta al lugar del backend [destino] por **sus coordenadas**; dice su `nombre` al llegar. */
    fun calcular(lat: Double, lng: Double, destino: LugarDestino, rumbo: Double?): ResultadoRuta =
        calcular(lat, lng, destino.lat, destino.lng, destino.nombre, rumbo)

    /** La ruta a [destino] o `null` (sin coordenadas válidas o sin camino). */
    fun rutaA(destino: LugarDestino, lat: Double, lng: Double, rumbo: Double?): Ruta? =
        (calcular(lat, lng, destino, rumbo) as? ResultadoRuta.Encontrada)?.ruta

    /**
     * Destino **por texto** (los destinos de prueba del mapa, `PruebaMapa`): el primero de [nombres] que sea `"lat,lng"`
     * da las coordenadas; si no, el primero que case con el `lugar` (informativo) de un nodo da las de ese nodo. Ninguno →
     * [ResultadoRuta.DestinoFueraDelGrafo].
     */
    fun calcular(lat: Double, lng: Double, nombres: Collection<String>, nombreDestino: String, rumbo: Double?): ResultadoRuta {
        val punto = nombres.firstNotNullOfOrNull { coordenadas(it) }
            ?: nombres.firstNotNullOfOrNull { nodoConLugar(it) }?.let { it.lat to it.lng }
            ?: return ResultadoRuta.DestinoFueraDelGrafo
        return calcular(lat, lng, punto.first, punto.second, nombreDestino, rumbo)
    }

    /**
     * Ruta desde ([lat], [lng]) hasta el punto del grafo más cercano a ([destinoLat], [destinoLng]). [rumbo]: hacia dónde
     * mira la persona (norte verdadero) o `null` (la primera instrucción no da dirección).
     */
    fun calcular(
        lat: Double,
        lng: Double,
        destinoLat: Double,
        destinoLng: Double,
        nombreDestino: String,
        rumbo: Double?,
    ): ResultadoRuta {
        if (!valida(destinoLat, destinoLng)) return ResultadoRuta.DestinoFueraDelGrafo
        val inicio = Proyeccion.masCercana(grafo, lat, lng) ?: return ResultadoRuta.SinCamino
        val fin = Proyeccion.masCercana(grafo, destinoLat, destinoLng) ?: return ResultadoRuta.SinCamino
        val camino = CalculoRuta.masCorta(grafo, inicio, fin) ?: return ResultadoRuta.SinCamino
        val fuera = inicio.distanciaM > parametros.fueraDelCaminoM
        val lejos = fin.distanciaM > parametros.fueraDelCaminoM

        val porCamino = mutableListOf(PuntoRuta(inicio.lat, inicio.lng, 0.0))
        if (camino.nodos.isEmpty()) {
            porCamino += PuntoRuta(fin.lat, fin.lng, camino.metros)
        } else {
            camino.nodos.forEachIndexed { i, n ->
                val m = if (i == 0) {
                    if (n.id == inicio.arista.a) inicio.metrosHastaA else inicio.metrosHastaB
                } else {
                    metrosEntre(camino.nodos[i - 1].id, n.id)
                }
                porCamino += PuntoRuta(n.lat, n.lng, m)
            }
            val ultimo = camino.nodos.last().id
            porCamino += PuntoRuta(fin.lat, fin.lng, if (ultimo == fin.arista.a) fin.metrosHastaA else fin.metrosHastaB)
        }
        val camino1 = sinRepetidos(porCamino)
        val dibujo = sinRepetidos(
            listOf(PuntoRuta(lat, lng, 0.0), PuntoRuta(inicio.lat, inicio.lng, inicio.distanciaM)) + porCamino.drop(1),
        )
        val instrucciones = Instrucciones.generar(
            puntos = if (fuera) dibujo else camino1,
            rumboActual = rumbo,
            alCamino = fuera && dibujo.size >= 2,
            destino = nombreDestino,
            p = parametros,
            llegada = if (lejos) Llegada(destinoLat, destinoLng, fin.distanciaM) else null,
        )
        return ResultadoRuta.Encontrada(
            Ruta(
                destino = nombreDestino,
                inicio = inicio,
                fin = fin,
                metrosAlCamino = inicio.distanciaM,
                fueraDelCamino = fuera,
                metrosAlDestino = fin.distanciaM,
                destinoLejos = lejos,
                metros = camino.metros + if (fuera) inicio.distanciaM else 0.0,
                puntos = dibujo,
                instrucciones = instrucciones,
            ),
        )
    }

    private fun valida(lat: Double, lng: Double) =
        lat.isFinite() && lng.isFinite() && lat in -90.0..90.0 && lng in -180.0..180.0

    private fun coordenadas(texto: String): Pair<Double, Double>? {
        val partes = texto.split(',').map { it.trim() }
        if (partes.size != 2) return null
        val la = partes[0].toDoubleOrNull() ?: return null
        val ln = partes[1].toDoubleOrNull() ?: return null
        return (la to ln).takeIf { valida(la, ln) }
    }

    private fun metrosEntre(a: String, b: String): Double =
        grafo.adyacencia[a].orEmpty().filter { it.otro(a) == b }.minOfOrNull { it.metros } ?: 0.0

    /**
     * Quita los puntos a menos de [ParametrosRuta.puntoRepetidoM] del último que quedó (por sus metros), salvo el primero.
     * Los metros de un punto quitado no se pierden: pasan al siguiente que queda o, si era el final, al último; así la
     * suma de los metros de las instrucciones es siempre la de [Camino.metros].
     */
    private fun sinRepetidos(puntos: List<PuntoRuta>): List<PuntoRuta> {
        val r = mutableListOf<PuntoRuta>()
        var pendiente = 0.0
        for (p in puntos) {
            if (r.isEmpty()) {
                r += p
                continue
            }
            val m = pendiente + p.metrosDesdeAnterior
            if (m >= parametros.puntoRepetidoM) {
                r += p.copy(metrosDesdeAnterior = m)
                pendiente = 0.0
            } else {
                pendiente = m
            }
        }
        if (pendiente > 0.0 && r.size > 1) {
            val ultimo = r.removeAt(r.lastIndex)
            r += ultimo.copy(metrosDesdeAnterior = ultimo.metrosDesdeAnterior + pendiente)
        }
        return r
    }
}
