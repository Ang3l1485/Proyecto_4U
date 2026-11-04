package com.example.myapplication.session

import android.content.Context
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion

/**
 * Sesión del admin (ARCHITECTURE §5.3). Guarda en un [AlmacenSesion]: en la app, [AlmacenSesionCifrado]
 * (`EncryptedSharedPreferences`, llave en Android Keystore); en las pruebas de la JVM, uno en memoria.
 *
 * Desde FE-1.2 la sesión lleva `expira_en`: [obtener] trata una sesión vencida como «sin sesión» (y la borra) sin
 * llamar al backend. [reloj] da la hora en milisegundos Unix (se sustituye en las pruebas).
 */
class SessionManager(
    private val almacen: AlmacenSesion,
    private val reloj: () -> Long = { System.currentTimeMillis() },
) {

    /** La de la app: almacén cifrado (archivo `campus_session`). Usa `applicationContext`. */
    constructor(context: Context) : this(AlmacenSesionCifrado(context))

    fun guardar(sesion: Sesion) = almacen.escribir(sesion)

    /**
     * La sesión vigente, o `null` si no hay, si el rol guardado no es válido o si su `expira_en` ya pasó (en ese caso
     * además la borra). Nunca llama al backend.
     */
    fun obtener(): Sesion? {
        val sesion = almacen.leer() ?: return null
        if (sesion.vencida(reloj())) {
            almacen.borrar()
            return null
        }
        return sesion
    }

    fun esAdmin(): Boolean = obtener()?.usuario?.rol == Rol.ADMIN

    /** Cerrar sesión: borra token, datos del usuario y `expira_en`. */
    fun cerrarSesion() = almacen.borrar()
}
