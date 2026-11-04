package com.example.myapplication.domain.model

/*
 * Resultado de «Ubicarse» (FE-3.2): lo que devuelve `POST /v1/localize` (contrato: BACKEND_FASTAPI/docs/ARCHITECTURE.md
 * §5.3) ya convertido a modelos de la app por `MapeoDatosApi.resultadoUbicacion` (ARCHITECTURE §5.10). Sin Android.
 */

/** `nivel` de la respuesta (`alta`, `media`, `baja`). La app decide qué decir; con [BAJA] sugiere repetir la vuelta. */
enum class NivelConfianza(val etiqueta: String) {
    ALTA("alta"),
    MEDIA("media"),
    BAJA("baja"),
}

/** `posicion`: WGS84 y la dispersión de las coincidencias alrededor de la posición ([radioM], metros). */
data class PosicionEstimada(val lat: Double, val lng: Double, val radioM: Double)

/** `lugar_cercano`: el lugar más cercano si está a ≤ 60 m (backend §5.3). Sin rumbo: el contrato no lo trae. */
data class LugarCercano(val id: String, val nombre: String, val distanciaM: Double)

/**
 * Un elemento de `referencias`: [rumboGrados] es **absoluto** (desde la posición hacia el lugar; [0, 360), norte
 * verdadero). Cuándo incluye el lugar más cercano: backend §5.3 (si `lugar_cercano` es `null`, la primera referencia
 * es el lugar más cercano; si no, no lo repite).
 */
data class ReferenciaLugar(val id: String, val nombre: String, val distanciaM: Double, val rumboGrados: Double)

/** Respuesta `200` de `POST /v1/localize`: `resultado = ok` ([Ubicado]) o `sin_coincidencias` ([SinCoincidencias]). */
sealed interface ResultadoUbicacion {
    val fotosUsadas: Int

    data class Ubicado(
        val posicion: PosicionEstimada,
        /** [0, 1], truncada a 2 decimales por el backend; [nivel] se decidió con ese mismo valor. */
        val confianza: Double,
        val nivel: NivelConfianza,
        /** (−180, 180] o `null`: se **suma** al rumbo verdadero de la brújula (backend §5.3). */
        val correccionRumboGrados: Double?,
        val lugarCercano: LugarCercano?,
        val referencias: List<ReferenciaLugar>,
        override val fotosUsadas: Int,
        val fotosConCoincidencia: Int,
    ) : ResultadoUbicacion

    data class SinCoincidencias(override val fotosUsadas: Int) : ResultadoUbicacion
}

/**
 * Una ubicación guardada en [SesionDeNavegacion]: el [resultado], cuándo llegó ([obtenidaEnMs], reloj monótono del
 * holder) y el rumbo **verdadero** de la última lectura del escaneo ([rumboAlTerminar], [0, 360), sin la corrección del
 * backend; `null` si no hubo lectura), que sirve de rumbo actual en 6.3 hasta que llegue la primera lectura del sensor.
 */
data class UbicacionEstimada(
    val resultado: ResultadoUbicacion,
    val obtenidaEnMs: Long,
    val rumboAlTerminar: Double?,
) {
    /** El resultado con posición, o `null` con `sin_coincidencias`. */
    val ubicado: ResultadoUbicacion.Ubicado? get() = resultado as? ResultadoUbicacion.Ubicado

    /**
     * Vigente = con posición, nivel alta o media y como mucho [VIGENCIA_MS] desde que llegó (decisión del usuario del
     * 2026-10-26, decisión abierta 15, ADR-FE-24). Sin PDR entre pantallas, una ubicación vieja ya no dice dónde está la
     * persona.
     */
    fun vigente(ahoraMs: Long): Boolean {
        val u = ubicado ?: return false
        val edad = ahoraMs - obtenidaEnMs
        return u.nivel != NivelConfianza.BAJA && edad in 0..VIGENCIA_MS
    }

    companion object {
        /** 2 minutos. */
        const val VIGENCIA_MS = 120_000L
    }
}
