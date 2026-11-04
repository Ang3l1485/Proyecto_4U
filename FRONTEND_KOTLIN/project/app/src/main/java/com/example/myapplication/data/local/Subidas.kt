package com.example.myapplication.data.local

import android.app.Application
import android.os.Build
import com.example.myapplication.data.remote.ClienteApi
import com.example.myapplication.logs.AppLog
import com.example.myapplication.session.SessionManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import java.io.File

/**
 * Las piezas de la subida, **una por proceso** (FE-2.1). `MyApp.onCreate` llama a [iniciar] después de asignar
 * `ClienteApi.vigilante` (la cola usa `ClienteApi.api`, que lee el vigilante al crearse). Las `Factory` de 7.5, del
 * Panel y del `VideoRepository` compuesto leen [almacen], [subida] y [cola]. No arranca nada al iniciar: en un
 * arranque en frío no hay sesión (`MyApp` la borra); la cola se retoma al abrir el Panel o 7.5.
 */
object Subidas {

    /** Tag de `AppLog` de la cola y de la subida (líneas sin URLs ni tokens). */
    const val TAG = "Subida"

    @Volatile
    private var piezas: Piezas? = null

    private class Piezas(val almacen: AlmacenRecorridos, val subida: SubidaRecorrido, val cola: ColaSubida)

    val almacen: AlmacenRecorridos get() = requerir().almacen
    val subida: SubidaRecorrido get() = requerir().subida
    val cola: ColaSubida get() = requerir().cola

    /** Idempotente. [sesion] es la misma instancia del vigilante (una por proceso, ARCHITECTURE §5.3). */
    @Synchronized
    fun iniciar(app: Application, sesion: SessionManager) {
        if (piezas != null) return
        val registrar: (String) -> Unit = { AppLog.i(TAG, it) }
        val almacen = AlmacenRecorridos(File(app.filesDir, "recoleccion"))
        val version = runCatching { app.packageManager.getPackageInfo(app.packageName, 0).versionName }.getOrNull()
        val subida = SubidaRecorrido(
            almacen = almacen,
            api = ClienteApi.api,
            s3 = SubidorS3(),
            preparador = Recodificador(MotorImagenAndroid()),
            dispositivo = "${Build.MANUFACTURER} ${Build.MODEL} / Android ${Build.VERSION.RELEASE}",
            appVersion = version,
            registrar = registrar,
        )
        val cola = ColaSubida(
            almacen = almacen,
            ejecutor = subida,
            haySesion = { runCatching { sesion.obtener() != null }.getOrDefault(false) },
            alcance = CoroutineScope(SupervisorJob() + Dispatchers.IO),
            registrar = registrar,
        )
        piezas = Piezas(almacen, subida, cola)
    }

    private fun requerir(): Piezas = piezas ?: error("Subidas.iniciar() no se llamó (MyApp.onCreate)")
}
