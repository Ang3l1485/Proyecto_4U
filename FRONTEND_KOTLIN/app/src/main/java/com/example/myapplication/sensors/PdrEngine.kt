package com.example.myapplication.sensors

import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * Motor de navegación inercial (PDR). Lógica pura, sin Android: se puede probar con tests
 * unitarios y la usan todas las vistas (mapa público, recolección, navegación).
 *
 * Es el ÚNICO sitio donde se calcula la posición a partir de pasos y rumbo.
 * Las coordenadas son latitud / longitud (WGS84).
 */
class PdrEngine(
    val longitudPasoM: Double = LONGITUD_PASO_DEFECTO_M,
    private val ventanaRumbo: Int = 6,
    private val ventanaVelocidadMs: Long = 5_000,
) {
    companion object {
        /** Longitud de paso genérica, mientras el usuario no calibre la suya (CalibracionPasoRepository). */
        const val LONGITUD_PASO_DEFECTO_M = 0.72
    }

    var lat: Double? = null
        private set
    var lng: Double? = null
        private set

    /** Rumbo en grados, 0–360, 0 = norte, sentido horario. */
    var rumbo: Float = 0f
        private set

    var pasos: Int = 0
        private set

    val distanciaMetros: Double get() = pasos * longitudPasoM

    var velocidadMps: Double = 0.0
        private set

    private var inicioLat: Double? = null
    private var inicioLng: Double? = null
    private val lecturasRumbo = ArrayDeque<Float>()
    private val tiemposPasos = ArrayDeque<Long>()

    /** Fija el punto de partida (y la posición actual). No reinicia el contador de pasos. */
    fun fijarPosicion(lat: Double, lng: Double) {
        inicioLat = lat
        inicioLng = lng
        this.lat = lat
        this.lng = lng
    }

    /** Vuelve al punto de partida con pasos y velocidad en cero. */
    fun reiniciar() {
        pasos = 0
        velocidadMps = 0.0
        tiemposPasos.clear()
        lat = inicioLat
        lng = inicioLng
    }

    /**
     * Lectura de la brújula (grados, 0–360, norte real). Se promedian las últimas
     * [ventanaRumbo] lecturas con promedio circular, para que 359° y 1° den 0° y no 180°.
     */
    fun onRumboSensor(grados: Float) {
        if (grados.isNaN()) return
        lecturasRumbo.addLast(((grados % 360f) + 360f) % 360f)
        while (lecturasRumbo.size > ventanaRumbo) lecturasRumbo.removeFirst()

        var sumaSin = 0.0
        var sumaCos = 0.0
        for (g in lecturasRumbo) {
            val rad = g * PI / 180.0
            sumaSin += sin(rad)
            sumaCos += cos(rad)
        }
        var promedio = atan2(sumaSin, sumaCos) * 180.0 / PI
        if (promedio < 0) promedio += 360.0
        rumbo = promedio.toFloat()
    }

    /** Rumbo fijado a mano (rueda de la pantalla, cuando no hay brújula). Sin promedio. */
    fun fijarRumboManual(grados: Float) {
        if (grados.isNaN()) return
        lecturasRumbo.clear()
        rumbo = ((grados % 360f) + 360f) % 360f
    }

    /**
     * Registra un paso en el instante [tMs] (milisegundos, reloj monótono) y avanza la posición
     * [longitudPasoM] metros en dirección [rumbo]. Devuelve `false` si aún no hay posición inicial.
     */
    fun onPaso(tMs: Long): Boolean {
        val la = lat ?: return false
        val ln = lng ?: return false
        pasos++

        val rad = rumbo * PI / 180.0
        val norte = longitudPasoM * cos(rad)
        val este = longitudPasoM * sin(rad)
        lat = la + norte / 111_320.0
        lng = ln + este / (111_320.0 * cos(la * PI / 180.0))

        // Velocidad: pasos de los últimos 5 s. Con n pasos en la ventana, el intervalo cubre n-1.
        tiemposPasos.addLast(tMs)
        while (tiemposPasos.isNotEmpty() && tMs - tiemposPasos.first() >= ventanaVelocidadMs) {
            tiemposPasos.removeFirst()
        }
        velocidadMps = if (tiemposPasos.size > 1) {
            val dt = (tMs - tiemposPasos.first()) / 1000.0
            // dt > 0,5 evita dividir por ~0 si llegan varios pasos juntos
            if (dt > 0.5) (tiemposPasos.size - 1) * longitudPasoM / dt else velocidadMps
        } else 0.0
        return true
    }
}