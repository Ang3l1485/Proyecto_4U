package com.example.myapplication.ui.admin.calibracion

import com.example.myapplication.domain.usecase.ResultadoCalibracion
import com.example.myapplication.sensors.FuentePasos

/** Punto del tramo de calibración (extremo A o B), en WGS84. */
data class PuntoTramo(val lat: Double, val lng: Double)

enum class ExtremoTramo { A, B }

enum class FaseCalibracion {
    /** Falta marcar A y/o B en el mapa. */
    PUNTOS,

    /** A y B marcados: se puede tocar «Inicio». */
    LISTO,

    /** Caminando de A a B: el contador de pasos está corriendo. */
    CAMINANDO,

    /** Se tocó «Fin»: hay un [CalibracionUiState.resultado] (válido o no). */
    RESULTADO,

    /** El resultado válido ya se guardó en el dispositivo. */
    GUARDADA,
}

/** Avisos temporales; el texto lo pone la pantalla. */
enum class AvisoCalibracion { CANCELADA_SEGUNDO_PLANO, VALOR_RESTABLECIDO }

data class CalibracionUiState(
    val fase: FaseCalibracion = FaseCalibracion.PUNTOS,
    val puntoA: PuntoTramo? = null,
    val puntoB: PuntoTramo? = null,
    /** Distancia en línea recta entre A y B (m); `null` mientras falte uno. */
    val distanciaM: Double? = null,
    /** Pasos dados desde «Inicio» (en vivo mientras camina; fijo en el resultado). */
    val pasos: Int = 0,
    val segundos: Int = 0,
    val resultado: ResultadoCalibracion? = null,
    /** Lo que usará el PDR ahora mismo: la calibrada o la genérica. */
    val longitudActualM: Double,
    val calibrada: Boolean,
    val fuentePasos: FuentePasos = FuentePasos.NINGUNA,
    val aviso: AvisoCalibracion? = null,
) {
    val puedeIniciar: Boolean get() = fase == FaseCalibracion.LISTO
    val hayPuntos: Boolean get() = puntoA != null || puntoB != null
    val mapaBloqueado: Boolean get() = fase != FaseCalibracion.PUNTOS && fase != FaseCalibracion.LISTO

    /** `true` si los pasos se cuentan con el acelerómetro y no con el sensor de hardware. */
    val pasosPorAcelerometro: Boolean
        get() = fuentePasos == FuentePasos.ACELEROMETRO_SIN_PERMISO ||
            fuentePasos == FuentePasos.ACELEROMETRO_SIN_SENSOR
}