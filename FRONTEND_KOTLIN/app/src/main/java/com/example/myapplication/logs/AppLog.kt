package com.example.myapplication.logs

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object AppLog {
    private const val MAX_BYTES = 1_000_000L // rota a ~1 MB
    private var archivo: File? = null
    private val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)

    @Volatile var sesion: String = "-"

    fun init(context: Context) {
        val dir = File(context.filesDir, "logs").apply { mkdirs() }
        archivo = File(dir, "app.log")
    }

    fun nuevaSesion(prefijo: String): String {
        sesion = "$prefijo-${System.currentTimeMillis() % 100000}"
        return sesion
    }

    fun d(tag: String, msg: String) = log(Log.DEBUG, "D", tag, msg, null)
    fun i(tag: String, msg: String) = log(Log.INFO, "I", tag, msg, null)
    fun w(tag: String, msg: String, t: Throwable? = null) = log(Log.WARN, "W", tag, msg, t)
    fun e(tag: String, msg: String, t: Throwable? = null) = log(Log.ERROR, "E", tag, msg, t)

    private fun log(prioridad: Int, nivel: String, tag: String, msg: String, t: Throwable?) {
        val texto = if (t != null) "$msg\n${Log.getStackTraceString(t)}" else msg
        Log.println(prioridad, tag, "[$sesion] $texto")
        escribir("${fmt.format(Date())} $nivel/$tag [${Thread.currentThread().name}] [$sesion] $texto\n")
    }

    @Synchronized
    private fun escribir(linea: String) {
        val f = archivo ?: return
        try {
            if (f.length() > MAX_BYTES) f.renameTo(File(f.parentFile, "app.log.1"))
            f.appendText(linea)
        } catch (_: Exception) { /* nunca romper la app por un log */ }
    }
}