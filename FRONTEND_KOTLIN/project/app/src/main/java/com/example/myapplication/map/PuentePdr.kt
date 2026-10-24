package com.example.myapplication.map

import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import com.example.myapplication.sensors.PdrTracker

/**
 * Puente `AndroidBridge` del mapa público (index.html + app.js). Web → Kotlin.
 *
 * Los métodos de `@JavascriptInterface` se ejecutan en un hilo del WebView, no en el principal,
 * así que cada uno reenvía al hilo principal, que es donde vive [PdrTracker].
 * Kotlin → Web está en `MapaPublicoScreen.kt` (`onNativePosition`, `onNativeHeading`, ...).
 */
class PuentePdr(private val tracker: PdrTracker) {
    private val principal = Handler(Looper.getMainLooper())

    /** Empieza a leer sensores (pasos, rumbo, aceleración). */
    @JavascriptInterface
    fun startSensors() { principal.post { tracker.iniciar() } }

    @JavascriptInterface
    fun stopSensors() { principal.post { tracker.detener() } }

    /** Punto de partida elegido en el mapa (toque o GPS). */
    @JavascriptInterface
    fun setPosition(lat: Double, lng: Double) { principal.post { tracker.fijarPosicion(lat, lng) } }

    /** Rumbo de la rueda manual (solo cuando el teléfono no tiene brújula). */
    @JavascriptInterface
    fun setManualHeading(grados: Double) { principal.post { tracker.fijarRumboManual(grados.toFloat()) } }

    /** Vuelve al punto de partida con pasos en cero. */
    @JavascriptInterface
    fun reset() { principal.post { tracker.reiniciar() } }
}