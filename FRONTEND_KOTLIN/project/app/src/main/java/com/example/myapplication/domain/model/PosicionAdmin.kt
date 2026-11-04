package com.example.myapplication.domain.model

/**
 * Última posición conocida del admin en este proceso (FE-3.3): la que da «Mi posición» del editor de mapa (7.8). La app
 * no usa el GPS (§3.2): la escribe la recolección (7.4) con la posición del PDR; si no hay, se usa la última de
 * «Ubicarme» (`SesionDeNavegacion.ultimaPosicion()`, aunque ya no sea vigente). Solo memoria.
 */
open class PosicionesAdmin(private val respaldo: () -> Pair<Double, Double>? = { null }) {
    @Volatile
    private var ultima: Pair<Double, Double>? = null

    fun registrar(lat: Double, lng: Double) {
        ultima = lat to lng
    }

    /** La de la recolección; si no hay, la de [respaldo]; si tampoco, `null`. */
    fun ultima(): Pair<Double, Double>? = ultima ?: respaldo()
}

/** El del proceso: respaldo en la última ubicación de «Ubicarme». */
object PosicionAdmin : PosicionesAdmin({ SesionDeNavegacion.ultimaPosicion()?.let { it.lat to it.lng } })
