package com.example.myapplication

import android.app.Application
import android.os.Build
import com.example.myapplication.data.local.Subidas
import com.example.myapplication.data.remote.AlertasPublicas
import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.logs.AppLog
import com.example.myapplication.session.EventosSesion
import com.example.myapplication.session.SessionManager
import com.example.myapplication.session.VigilanteSesion

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
        val sesion = SessionManager(this)
        runCatching { sesion.cerrarSesion() }
            .onFailure { AppLog.e("App", "No se pudo limpiar la sesión", it) }

        // FE-1.2: sesión de las rutas /v1/admin y /v1/collect (token, expira_en y 401 de sesión → Login).
        ClienteApi.vigilante = VigilanteSesion(
            session = sesion,
            onSinSesion = EventosSesion::emitir,
            registrar = { AppLog.w(TAG_SESION, it) },
        )

        // FE-2.1: cola de subida de recorridos (una por proceso). No sube nada aquí: no hay sesión en un arranque en
        // frío; se retoma al abrir el Panel o la vista 7.5 (ARCHITECTURE §5.10).
        Subidas.iniciar(this, sesion)

        // FE-3.6: caché de alertas públicas (files/alertas/publicas.json) y sus disparadores: al pasar a primer plano,
        // cada 5 min en primer plano y al volver la conexión (ARCHITECTURE §5.10, «Alertas sin conexión»).
        AlertasPublicas.iniciar(this)
    }

    private companion object {
        const val TAG_SESION = "Sesion"
    }
}
