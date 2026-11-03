package com.example.myapplication.session

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Sesion
import com.example.myapplication.domain.model.Usuario

/**
 * Dónde guarda [SessionManager] la sesión. Sin lógica de caducidad: eso lo decide [SessionManager.obtener].
 * Separado para poder probar la sesión en la JVM (FE-1.2, `SesionVencidaTest`) sin `EncryptedSharedPreferences`.
 */
interface AlmacenSesion {
    /** La sesión guardada tal cual, o `null` si no hay token, el rol no es válido o falta `expira_en`. */
    fun leer(): Sesion?
    fun escribir(sesion: Sesion)
    fun borrar()
}

/**
 * `EncryptedSharedPreferences` (archivo `campus_session`, llaves AES256-SIV, valores AES256-GCM, llave maestra en
 * Android Keystore). Se crea de forma perezosa en el primer uso: ese acceso puede tardar y lanzar excepción si el
 * Keystore falla. Claves: `token`, `id`, `nombre`, `correo`, `rol` (nombre del enum) y `expira_en_ms` (Long).
 */
class AlmacenSesionCifrado(context: Context) : AlmacenSesion {

    private val app = context.applicationContext

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(app)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            app,
            ARCHIVO,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    override fun escribir(sesion: Sesion) {
        prefs.edit()
            .putString(K_TOKEN, sesion.token)
            .putString(K_ID, sesion.usuario.id)
            .putString(K_NOMBRE, sesion.usuario.nombre)
            .putString(K_CORREO, sesion.usuario.correo)
            .putString(K_ROL, sesion.usuario.rol.name)
            .putLong(K_EXPIRA, sesion.expiraEnMs)
            .apply()
    }

    override fun leer(): Sesion? {
        val token = prefs.getString(K_TOKEN, null) ?: return null
        val rol = prefs.getString(K_ROL, null)
            ?.let { runCatching { Rol.valueOf(it) }.getOrNull() } ?: return null
        // Una sesión guardada sin expira_en (anterior a FE-1.2) no es válida.
        if (!prefs.contains(K_EXPIRA)) return null
        return Sesion(
            token = token,
            usuario = Usuario(
                id = prefs.getString(K_ID, "").orEmpty(),
                nombre = prefs.getString(K_NOMBRE, "").orEmpty(),
                correo = prefs.getString(K_CORREO, "").orEmpty(),
                rol = rol,
            ),
            expiraEnMs = prefs.getLong(K_EXPIRA, 0L),
        )
    }

    override fun borrar() = prefs.edit().clear().apply()

    private companion object {
        const val ARCHIVO = "campus_session"
        const val K_TOKEN = "token"
        const val K_ID = "id"
        const val K_NOMBRE = "nombre"
        const val K_CORREO = "correo"
        const val K_ROL = "rol"
        const val K_EXPIRA = "expira_en_ms"
    }
}
