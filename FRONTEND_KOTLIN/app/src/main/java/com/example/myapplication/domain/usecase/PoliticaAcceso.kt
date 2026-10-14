package com.example.myapplication.domain.usecase

import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.domain.model.Rol

/**
 * Matriz de permisos rol → módulos (HU-017). Kotlin puro: se prueba con JUnit sin Android.
 *   - ADMIN        → todos los módulos
 *   - INVESTIGADOR → IMAGENES, VIDEOS
 *   - USER         → ninguno
 */
object PoliticaAcceso {

    private val permisos: Map<Rol, Set<Modulo>> = mapOf(
        Rol.ADMIN to Modulo.entries.toSet(),
        Rol.INVESTIGADOR to setOf(Modulo.IMAGENES, Modulo.VIDEOS),
        Rol.USER to emptySet(),
    )

    fun puedeAcceder(rol: Rol, modulo: Modulo): Boolean =
        modulo in permisos[rol].orEmpty()

    /** El panel de administración se habilita si el rol tiene al menos un módulo (ADMIN, INVESTIGADOR). */
    fun puedeEntrarAlPanel(rol: Rol): Boolean =
        Modulo.entries.any { puedeAcceder(rol, it) }
}
