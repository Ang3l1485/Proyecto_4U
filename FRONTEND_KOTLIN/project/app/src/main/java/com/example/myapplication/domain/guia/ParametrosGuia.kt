package com.example.myapplication.domain.guia

import com.example.myapplication.domain.model.NivelConfianza

/**
 * Parámetros de la guía por voz (FE-5.3). Son valores **de partida**, a ajustar el día de campo (PRIORITY-2 §4.4):
 * cuándo se avisa antes de cada maniobra, cuándo se da por desviada a la persona, cada cuánto se toma una foto y cuándo
 * se acepta la posición de una foto (regla simple de mezcla, decisión del usuario del 2026-10-27).
 *
 * Avisos (sobre los metros caminados por la ruta, comparados con `Instruccion.desdeM`):
 * - [avisoPrevioM]: a esta distancia de una maniobra se dice «En N metros, gira a la derecha.» (una vez).
 * - [enManiobraM]: a esta distancia (o menos) se dice la instrucción completa («Gira a la derecha y sigue recto…»).
 * - [llegadaM]: a esta distancia (o menos) del final de la ruta se da por llegada (vista 6.6).
 *
 * Desvío y recálculo:
 * - [desvioM]: más lejos que esto de la ruta (en línea recta) la lectura cuenta como desviada.
 * - [lecturasDesvio]: tantas lecturas desviadas **seguidas** (una por paso) recalculan la ruta y lo avisan.
 *
 * Fotos (`POST /v1/localize/frame`):
 * - [metrosEntreFotos]: una foto cada tantos metros caminados desde la anterior (decisión abierta 4, propuesta).
 * - [dudosaM] y [minMetrosEntreFotos]: antes, si la posición se aleja de la ruta más de [dudosaM] y se caminó al menos
 *   [minMetrosEntreFotos] desde la última foto (posición dudosa: puede ser un desvío o un error de los pasos).
 * - [radioMinM], [radioMaxM], [margenRadioM]: el `radio_m` que se pide = el límite de coherencia + [margenRadioM],
 *   entre [radioMinM] (40, el valor por defecto del backend) y [radioMaxM] (100, el máximo que admite).
 *
 * Aceptar una foto (todo a la vez):
 * - resultado `ok` con un nivel de [nivelesAceptados] (`alta` o `media`);
 * - `distancia_previa_m` ≤ [coherenciaBaseM] + [coherenciaPorMetro] × metros caminados desde la última posición aceptada
 *   (al empezar, la de «Ubicarme»): el error de los pasos crece con lo caminado; un salto mayor se descarta (40 m tras
 *   5 m de pasos: límite 10,5 m).
 * - [descartarBorrosas]: una foto oscura o borrosa (`CalidadImagen`) no se envía.
 *
 * Alertas (FE-3.6 en la guía) y posición:
 * - [alertaRutaM]: una alerta cuenta en la guía si su centro está a ≤ su `radio` + esto de la ruta (decisión abierta 3,
 *   propuesta de FE-5.3: solo las de la ruta, no las de un camino paralelo).
 * - [incertidumbreInicialM]: la incertidumbre de la posición de partida si no se conoce (la de prueba); con «Ubicarme»
 *   es su `radio_m`, y tras una foto aceptada, el de la foto. Se le suma la deriva de los pasos (`Deriva`, 4 %).
 */
data class ParametrosGuia(
    val avisoPrevioM: Double = 10.0,
    val enManiobraM: Double = 3.0,
    val llegadaM: Double = 3.0,
    val desvioM: Double = 15.0,
    val lecturasDesvio: Int = 4,
    val metrosEntreFotos: Double = 10.0,
    val dudosaM: Double = 8.0,
    val minMetrosEntreFotos: Double = 3.0,
    val coherenciaBaseM: Double = 8.0,
    val coherenciaPorMetro: Double = 0.5,
    val radioMinM: Double = 40.0,
    val radioMaxM: Double = 100.0,
    val margenRadioM: Double = 10.0,
    val nivelesAceptados: Set<NivelConfianza> = setOf(NivelConfianza.ALTA, NivelConfianza.MEDIA),
    val descartarBorrosas: Boolean = true,
    val alertaRutaM: Double = 10.0,
    val incertidumbreInicialM: Double = 5.0,
)

/**
 * Cómo llevar el teléfono durante la guía: lo dice la app al empezar (6.5). **Decisión del usuario del 2026-10-28**
 * (PRIORITY-2 §6, pendiente 1, resuelta: «claramente»): en la mano, frente al pecho, con la cámara hacia adelante (la
 * foto de corrección necesita que la cámara mire hacia donde se camina). Si cambia, se cambia solo este texto.
 */
const val COMO_LLEVAR_EL_TELEFONO =
    "Lleva el teléfono en la mano, frente al pecho, con la cámara hacia adelante."
