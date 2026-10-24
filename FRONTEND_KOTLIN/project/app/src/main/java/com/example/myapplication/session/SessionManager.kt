package com.example.myapplication.session

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario

/**
 * Guarda la sesión cifrada (AES-256, llave en Android Keystore).
 * Dependencia: androidx.security:security-crypto
 */
class SessionManager(context: Context) {

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(context.applicationContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context.applicationContext,
            ARCHIVO,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun guardar(sesion: Sesion) {
        prefs.edit()
            .putString(K_TOKEN, sesion.token)
            .putString(K_ID, sesion.usuario.id)
            .putString(K_NOMBRE, sesion.usuario.nombre)
            .putString(K_CORREO, sesion.usuario.correo)
            .putString(K_ROL, sesion.usuario.rol.name)
            .apply()
    }

    fun obtener(): Sesion? {
        val token = prefs.getString(K_TOKEN, null) ?: return null
        val rol = prefs.getString(K_ROL, null)
            ?.let { runCatching { Rol.valueOf(it) }.getOrNull() } ?: return null
        return Sesion(
            token = token,
            usuario = Usuario(
                id = prefs.getString(K_ID, "").orEmpty(),
                nombre = prefs.getString(K_NOMBRE, "").orEmpty(),
                correo = prefs.getString(K_CORREO, "").orEmpty(),
                rol = rol,
            ),
        )
    }

    fun esAdmin(): Boolean = obtener()?.usuario?.rol == Rol.ADMIN

    /** Cerrar sesión: borra token y datos del usuario. */
    fun cerrarSesion() = prefs.edit().clear().apply()

    private companion object {
        const val ARCHIVO = "campus_session"
        const val K_TOKEN = "token"
        const val K_ID = "id"
        const val K_NOMBRE = "nombre"
        const val K_CORREO = "correo"
        const val K_ROL = "rol"
    }
}