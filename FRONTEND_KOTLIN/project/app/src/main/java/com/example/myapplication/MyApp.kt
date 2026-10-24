package com.example.myapplication

import android.app.Application
import android.os.Build
import com.example.myapplication.logs.AppLog
import com.example.myapplication.session.SessionManager

class MyApp : Application() {
    override fun onCreate() {
        super.onCreate()
        AppLog.init(this)
        AppLog.i("App", "Inicio. ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.SDK_INT}")

        val previo = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { hilo, error ->
            AppLog.e("CRASH", "Excepción no capturada en hilo '${hilo.name}'", error)
            previo?.uncaughtException(hilo, error)
        }

        // El admin debe iniciar sesión cada vez que se abre la app desde cero
        runCatching { SessionManager(this).cerrarSesion() }
            .onFailure { AppLog.e("App", "No se pudo limpiar la sesión", it) }
    }
}