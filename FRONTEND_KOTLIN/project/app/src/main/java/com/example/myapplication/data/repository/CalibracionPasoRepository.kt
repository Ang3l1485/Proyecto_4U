package com.example.myapplication.data.repository

import android.content.Context
import com.example.myapplication.domain.usecase.CalibracionPaso
import com.example.myapplication.domain.usecase.ResultadoCalibracion
import com.example.myapplication.sensors.PdrEngine

/**
 * Guarda en el dispositivo la longitud de paso calibrada (`SharedPreferences`, sin cifrar: no es
 * un dato sensible). Si no hay calibración válida, devuelve el valor genérico de [PdrEngine].
 *
 * Crear una instancia es barato: no abre nada hasta la primera lectura.
 */
class CalibracionPasoRepository(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences(ARCHIVO, Context.MODE_PRIVATE)

    /** Longitud calibrada (m), o `null` si nunca se calibró o el valor guardado no es plausible. */
    fun guardada(): Double? {
        val v = prefs.getString(K_LONGITUD, null)?.toDoubleOrNull() ?: return null
        return v.takeIf { it in CalibracionPaso.MIN_PASO_M..CalibracionPaso.MAX_PASO_M }
    }

    /** Lo que debe usar el PDR: la calibrada, o el valor genérico por defecto. */
    fun longitudPasoM(): Double = guardada() ?: PdrEngine.LONGITUD_PASO_DEFECTO_M

    fun guardar(medicion: ResultadoCalibracion.Valido, ahoraMs: Long = System.currentTimeMillis()) {
        prefs.edit()
            .putString(K_LONGITUD, medicion.longitudPasoM.toString())
            .putInt(K_PASOS, medicion.pasos)
            .putString(K_DISTANCIA, medicion.distanciaM.toString())
            .putLong(K_FECHA_MS, ahoraMs)
            .apply()
    }

    /** Vuelve al valor genérico. */
    fun restablecer() {
        prefs.edit().clear().apply()
    }

    private companion object {
        const val ARCHIVO = "campus_calibracion"
        const val K_LONGITUD = "longitud_paso_m"
        const val K_PASOS = "pasos"
        const val K_DISTANCIA = "distancia_m"
        const val K_FECHA_MS = "fecha_ms"
    }
}