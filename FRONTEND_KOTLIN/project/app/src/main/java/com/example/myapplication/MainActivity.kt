package com.example.myapplication

import android.Manifest
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.example.myapplication.ui.inicio.InicioScreen
import com.example.myapplication.ui.destino.SeleccionDestinoScreen
import com.example.myapplication.ui.ubicacion.EscaneoScreen
import com.example.myapplication.ui.ubicacion.PruebaUbicacion
import com.example.myapplication.ui.ubicacion.ResultadoUbicacionScreen
import com.example.myapplication.ui.auth.LoginScreen
import com.example.myapplication.ui.admin.panel.PanelAdminScreen
import com.example.myapplication.ui.admin.mapa.AlertasScreen
import com.example.myapplication.ui.admin.mapa.EditorMapaScreen
import com.example.myapplication.ui.admin.mapa.PedidoEditor
import com.example.myapplication.ui.admin.mapa.PedidosEditorMapa
import com.example.myapplication.domain.model.PosicionAdmin
import com.example.myapplication.ui.admin.imagenes.GaleriaScreen
import com.example.myapplication.ui.admin.videos.VideoDetalleScreen
import com.example.myapplication.ui.admin.videos.VideosScreen
import com.example.myapplication.map.MapaPublicoScreen
import com.example.myapplication.map.PruebaMapa
import com.example.myapplication.domain.guia.PruebaGuia
import com.example.myapplication.ui.navegacion.LlegadaScreen
import com.example.myapplication.ui.navegacion.NavegacionScreen
import com.example.myapplication.ui.admin.recoleccion.UbicacionManualScreen
import com.example.myapplication.ui.admin.recoleccion.RecoleccionScreen
import com.example.myapplication.ui.admin.recoleccion.ResumenVideoScreen
import com.example.myapplication.ui.admin.calibracion.CalibracionScreen
import com.example.myapplication.ui.admin.lugares.LugarFormScreen
import com.example.myapplication.ui.admin.lugares.LugaresScreen
import com.example.myapplication.domain.model.SesionDeNavegacion
import com.example.myapplication.domain.model.SesionDeRecoleccion
import com.example.myapplication.session.EventosSesion


class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // FE-2.3: solo en el APK de depuración y en un arranque nuevo (no al restaurar ni al rotar),
        // `am start -n com.example.myapplication/.MainActivity --es ruta mapa` abre una ruta de prueba.
        val rutaPrueba = if (savedInstanceState == null) rutaDePrueba(intent) else null
        // FE-5.1 (ADR-FE-38): con la ruta de prueba `mapa`, un destino y una posición de prueba para la ruta por el grafo
        // (`--es destino_prueba bloque35 --es posicion_prueba 6.201434,-75.578427`). Solo aquí: el flujo real no los usa.
        if (rutaPrueba == "mapa") {
            PruebaMapa.fijar(intent?.getStringExtra(EXTRA_DESTINO_PRUEBA), intent?.getStringExtra(EXTRA_POSICION_PRUEBA))
        }
        // FE-3.6 (ADR-FE-42): con una ruta de prueba (`resultado` o `mapa`), una ubicación de prueba de «Ubicarme»
        // (`--es ubicacion_prueba 6.201434,-75.578427`) registrada como si fuera la respuesta del escaneo. Solo aquí.
        if (rutaPrueba != null) {
            PruebaUbicacion.resultado(intent?.getStringExtra(EXTRA_UBICACION_PRUEBA))?.let {
                SesionDeNavegacion.registrar(it, rumboAlTerminar = null)
            }
        }
        // FE-5.3: con la ruta de prueba `navegacion` (6.5), el mismo destino y posición de prueba y, opcional, el modo de
        // simulación (`--es simular_pasos 0.7,500`: un paso de 0,7 m cada 500 ms, sin sensores). Solo aquí.
        if (rutaPrueba == "navegacion") {
            PruebaGuia.fijar(
                intent?.getStringExtra(EXTRA_DESTINO_PRUEBA),
                intent?.getStringExtra(EXTRA_POSICION_PRUEBA),
                intent?.getStringExtra(EXTRA_SIMULAR_PASOS),
            )
        }
        setContent {
            MaterialTheme {
                AppNav(rutaInicial = rutaPrueba)
            }
        }
    }

    private fun rutaDePrueba(intent: Intent?): String? {
        val depurable = applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        return intent?.getStringExtra(EXTRA_RUTA)?.takeIf { depurable && it in RUTAS_DE_PRUEBA }
    }

    companion object {
        /** Extra del `Intent` con la ruta de prueba (solo APK de depuración). */
        const val EXTRA_RUTA = "ruta"

        /** Rutas que se pueden abrir así; cualquier otra se ignora (navegar a una no registrada cierra la app). */
        val RUTAS_DE_PRUEBA = setOf("mapa", "resultado", "navegacion")

        /** FE-5.1: destino de prueba del mapa (el `lugar` de una entrada del grafo; se compara normalizado). */
        const val EXTRA_DESTINO_PRUEBA = "destino_prueba"

        /** FE-5.1: posición de prueba del mapa, `"<lat>,<lng>"` con punto decimal. */
        const val EXTRA_POSICION_PRUEBA = "posicion_prueba"

        /** FE-3.6: ubicación de prueba de «Ubicarme» (rutas `resultado` y `mapa`), `"<lat>,<lng>"` con punto decimal. */
        const val EXTRA_UBICACION_PRUEBA = "ubicacion_prueba"

        /** FE-5.3: modo de simulación de la guía, `"<paso m>,<intervalo ms>"` (o `si` = 0,7 m cada 500 ms). */
        const val EXTRA_SIMULAR_PASOS = "simular_pasos"
    }
}

/** Permisos de tiempo de ejecución de la app. */
object Permisos {
    val CAMARA = Manifest.permission.CAMERA
    val MICROFONO = Manifest.permission.RECORD_AUDIO

    /** Todos los que se piden al abrir Inicio por primera vez. */
    val INICIALES: Array<String> = buildList {
        add(CAMARA)
        add(MICROFONO)
        // ACTIVITY_RECOGNITION solo existe como permiso de ejecución desde Android 10
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            add(Manifest.permission.ACTIVITY_RECOGNITION)
        }
    }.toTypedArray()

    /**
     * Solo actividad física (contador de pasos), para la calibración de la longitud de paso.
     * Vacío antes de Android 10: ahí no es un permiso de ejecución y `PedirPermisos` pasa directo.
     */
    val ACTIVIDAD: Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            arrayOf(Manifest.permission.ACTIVITY_RECOGNITION)
        } else {
            emptyArray()
        }
}

@Composable
fun AppNav(rutaInicial: String? = null) {
    val nav = rememberNavController()

    // FE-2.3: ruta de prueba pedida al arrancar (MainActivity.EXTRA_RUTA). Queda encima de `inicio`: Atrás vuelve a Inicio.
    LaunchedEffect(nav, rutaInicial) {
        if (rutaInicial != null) nav.navigate(rutaInicial)
    }

    // FE-1.2: una ruta protegida se quedó sin sesión (401 TOKEN_* / NO_AUTENTICADO, o expira_en pasado). Si se está
    // en una pantalla admin, vuelve a Login sin cerrar la app (pila: inicio → login). En el flujo público no navega.
    LaunchedEffect(nav) {
        EventosSesion.sinSesion.collect {
            val actual = nav.currentDestination?.route.orEmpty()
            if (actual.startsWith("admin/")) {
                nav.navigate("login") {
                    popUpTo("inicio")
                    launchSingleTop = true
                }
            }
        }
    }

    // Regla: cada ruta se registra UNA sola vez. Si se repite, la última reemplaza a la anterior
    // (un placeholder vacío puede tapar la pantalla real).
    NavHost(navController = nav, startDestination = "inicio") {

        composable("inicio") {
            // Un solo diálogo con cámara + micrófono + actividad física.
            // Inicio se muestra aunque el usuario niegue alguno (queda la opción táctil).
            var permisosPedidos by rememberSaveable { mutableStateOf(false) }

            if (!permisosPedidos) {
                PedirPermisos(
                    permisos = Permisos.INICIALES,
                    onResultado = { permisosPedidos = true },
                )
            } else {
                InicioScreen(
                    // FE-3.2: «uno» es solo ubicarse: sin destino (el Resultado no habla de un destino viejo).
                    onUbicarme = {
                        SesionDeNavegacion.quitarDestino()
                        nav.navigate("ubicarme")
                    },
                    onIrALugar = { nav.navigate("destino") },
                    onAccesoAdministrador = { nav.navigate("login") },
                    // FE-3.1: voz «mapa» o acción de TalkBack «Ver mapa». Queda encima de `inicio`: Atrás vuelve.
                    onVerMapa = { nav.navigate("mapa") { launchSingleTop = true } },
                )
            }
        }

        composable("ubicarme") {
            // La cámara es indispensable: si ya estaba concedida pasa directo;
            // si no, se vuelve a pedir. Si la niega, vuelve a Inicio.
            var camaraLista by rememberSaveable { mutableStateOf(false) }

            if (!camaraLista) {
                PedirPermisos(
                    permisos = arrayOf(Permisos.CAMARA),
                    onResultado = { concedido ->
                        if (concedido) camaraLista = true
                        else nav.popBackStack()
                    },
                )
            } else {
                EscaneoScreen(
                    onCancelar = { nav.popBackStack() },
                    // FE-3.2: guarda el resultado (decisión abierta 15) y abre el Resultado (6.3) en lugar del
                    // escaneo: Atrás desde 6.3 vuelve a Inicio, no a la cámara.
                    onCompletado = { resultado, rumboAlTerminar ->
                        SesionDeNavegacion.registrar(resultado, rumboAlTerminar)
                        nav.navigate("resultado") { popUpTo("ubicarme") { inclusive = true } }
                    },
                    onAjustes = { nav.navigate("ajustes") },
                )
            }
        }

        // 6.3 Resultado de ubicación (FE-3.2). Lee la ubicación y el destino de SesionDeNavegacion.
        composable("resultado") {
            ResultadoUbicacionScreen(
                onVolverAUbicarme = { nav.navigate("ubicarme") { popUpTo("resultado") { inclusive = true } } },
                onIrALugar = { nav.navigate("destino") { popUpTo("resultado") { inclusive = true } } },
                onInicio = { nav.popBackStack("inicio", inclusive = false) },
                // FE-3.6: «Caminar con el mapa» (solo con ubicación vigente): el mapa empieza en esta posición y la 6.3
                // sale de la pila (Atrás desde el mapa vuelve a Inicio).
                onVerMapa = { nav.navigate("mapa") { popUpTo("resultado") { inclusive = true } } },
                // FE-5.3: «Guiarme» (o «guíame») → 6.5, encima de la 6.3 (Terminar vuelve a ella).
                onGuiarme = { nav.navigate("navegacion") { launchSingleTop = true } },
            )
        }

        // 6.5 Navegación guiada (FE-5.3). Pide la cámara (fotos de corrección); sin ella guía solo con los pasos.
        composable("navegacion") {
            var permisoPedido by rememberSaveable { mutableStateOf(false) }
            var camaraOk by rememberSaveable { mutableStateOf(false) }
            if (!permisoPedido) {
                PedirPermisos(
                    permisos = arrayOf(Permisos.CAMARA),
                    onResultado = { concedido ->
                        camaraOk = concedido
                        permisoPedido = true
                    },
                )
            } else {
                NavegacionScreen(
                    camaraOk = camaraOk,
                    onTerminar = { nav.popBackStack() },
                    onLlegada = { nav.navigate("llegada") { popUpTo("navegacion") { inclusive = true } } },
                )
            }
        }

        // 6.6 Llegada (FE-5.3). El texto lo deja la guía en LlegadaGuia.
        composable("llegada") {
            LlegadaScreen(
                onIrAOtroLugar = { nav.navigate("destino") { popUpTo("llegada") { inclusive = true } } },
                onInicio = { nav.popBackStack("inicio", inclusive = false) },
            )
        }

        // 6.4 Selección de destino
        composable("destino") {
            SeleccionDestinoScreen(
                onVolver = { nav.popBackStack() },
                onDestinoConfirmado = { lugar ->
                    // FE-3.2: el destino queda en SesionDeNavegacion. Con una ubicación vigente (alta o media y
                    // ≤ 2 min) va directo al Resultado, que dice su distancia y dirección; si no, primero el escaneo.
                    // Destino sale de la pila (al volver no queda su confirmación vieja). La vista 6.5 es de FE-5.1.
                    SesionDeNavegacion.elegirDestino(lugar)
                    val siguiente = if (SesionDeNavegacion.ubicacionVigente() != null) "resultado" else "ubicarme"
                    nav.navigate(siguiente) { popUpTo("destino") { inclusive = true } }
                },
                onAjustes = { nav.navigate("ajustes") },
            )
        }

        composable("login") {
            LoginScreen(
                onLoginExitoso = {
                    nav.navigate("admin/panel") {
                        popUpTo("login") { inclusive = true }
                    }
                },
                onVolver = { nav.popBackStack() },
            )
        }

        composable("admin/panel") {
            PanelAdminScreen(
                onRecolector = { nav.navigate("admin/ubicacion-manual") },
                onLugares = { nav.navigate("admin/lugares") },
                onMapaAlertas = { nav.navigate("admin/mapa") },
                onImagenes = { nav.navigate("admin/imagenes") },
                onVideos = { nav.navigate("admin/videos") },
                onEstadisticas = { nav.navigate("admin/estadisticas") },
                onAjustes = { nav.navigate("ajustes") },
                onVolverModoPublico = { nav.popBackStack("inicio", inclusive = false) },
                onSesionCerrada = { nav.popBackStack("inicio", inclusive = false) },
                onSinSesion = {
                    nav.navigate("login") { popUpTo("admin/panel") { inclusive = true } }
                },
                // FE-2.1: tarjeta de subidas → 7.5 de ese recorrido (retomar una subida, «subir después»).
                onAbrirSubida = { id -> nav.navigate("admin/recoleccion/resumen?video=$id") },
            )
        }

        // ── Vistas implementadas ──

        composable("admin/mapa") {
            EditorMapaScreen(
                onVolver = { nav.popBackStack() },
                // FE-3.3: lista de alertas (7.10), encima del editor.
                onVerLista = { nav.navigate("admin/mapa/alertas") { launchSingleTop = true } },
                // FE-3.3: la última posición del PDR de 7.4 o, si no hay, la de «Ubicarme» (sin GPS).
                posicionAdmin = { PosicionAdmin.ultima() },
            )
        }

        // 7.10 Lista de alertas (FE-3.3). Vuelve al editor (debajo en la pila) con un pedido para su mapa.
        composable("admin/mapa/alertas") {
            AlertasScreen(
                onVolver = { nav.popBackStack() },
                onVerEnMapa = { id ->
                    PedidosEditorMapa.pedir(PedidoEditor.VerAlerta(id))
                    nav.popBackStack()
                },
                onNuevaEnMapa = {
                    PedidosEditorMapa.pedir(PedidoEditor.NuevaAlerta)
                    nav.popBackStack()
                },
            )
        }

        // 7.11 Galería (FE-4.1). `lugar` y `video` (ids, opcionales) la abren filtrada: «Ver fotos» de 7.6 y «Ver en la
        // galería» de 7.7. `navigate("admin/imagenes")` sin argumentos también vale (el Panel). 7.12 no existe aún.
        composable(
            "admin/imagenes?lugar={lugar}&video={video}",
            arguments = listOf(
                navArgument("lugar") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
                navArgument("video") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { entrada ->
            GaleriaScreen(
                onVolver = { nav.popBackStack() },
                lugarId = entrada.arguments?.getString("lugar"),
                videoId = entrada.arguments?.getString("video"),
            )
        }

        // 7.13 Lista de videos (FE-4.1: servidor + recorridos del teléfono sin subir). «Nuevo video» → 7.3.
        composable("admin/videos") {
            VideosScreen(
                onVolver = { nav.popBackStack() },
                onAbrirVideo = { id -> nav.navigate("admin/videos/$id") },
                onNuevoVideo = { nav.navigate("admin/ubicacion-manual") },
            )
        }

        // 7.14 Detalle de video. `videoId` = UUID del backend o `rec_NNNN` de un recorrido del teléfono sin subir.
        // Tras eliminar el video (confirmado por el servidor) la pantalla llama a onVolver: vuelve a 7.13.
        composable("admin/videos/{videoId}") { entrada ->
            val videoId = entrada.arguments?.getString("videoId") ?: return@composable
            VideoDetalleScreen(
                videoId = videoId,
                onVolver = { nav.popBackStack() },
            )
        }

        // 7.3 Ubicación manual inicial
        composable("admin/ubicacion-manual") {
            // ACTIVITY_RECOGNITION es para el contador de pasos; si se niega, el PDR usa el acelerómetro.
            var permisosPedidos by rememberSaveable { mutableStateOf(false) }
            if (!permisosPedidos) {
                PedirPermisos(
                    permisos = Permisos.INICIALES,
                    onResultado = { permisosPedidos = true },
                )
            } else {
                UbicacionManualScreen(
                    onVolver = { nav.popBackStack() },
                    onConfirmar = { inicio ->
                        SesionDeRecoleccion.iniciar(inicio)
                        nav.navigate("admin/recoleccion")
                    },
                    onAjustes = { nav.navigate("ajustes") },
                    onCalibrar = { nav.navigate("admin/calibracion") },
                    // FE-2.3: sin InicioRecoleccion, 7.4 retoma el video `en_curso` más reciente.
                    onRetomar = {
                        SesionDeRecoleccion.limpiar()
                        nav.navigate("admin/recoleccion")
                    },
                )
            }
        }

        // 7.3b Calibración de la longitud de paso
        composable("admin/calibracion") {
            // ACTIVITY_RECOGNITION es para el contador de pasos; si se niega, el PDR usa el acelerómetro
            // y la pantalla lo avisa. Antes de Android 10 la lista está vacía y pasa directo.
            var permisosPedidos by rememberSaveable { mutableStateOf(false) }
            if (!permisosPedidos) {
                PedirPermisos(
                    permisos = Permisos.ACTIVIDAD,
                    onResultado = { permisosPedidos = true },
                )
            } else {
                CalibracionScreen(onVolver = { nav.popBackStack() })
            }
        }

        // 7.4 Recolección en curso
        composable("admin/recoleccion") {
            // La cámara es indispensable (como en «ubicarme»). La actividad física ya se pidió en 7.3;
            // si se negó, el PDR usa el acelerómetro.
            var camaraLista by rememberSaveable { mutableStateOf(false) }

            if (!camaraLista) {
                PedirPermisos(
                    permisos = arrayOf(Permisos.CAMARA),
                    onResultado = { concedido ->
                        if (concedido) camaraLista = true
                        else nav.popBackStack()
                    },
                )
            } else {
                RecoleccionScreen(
                    onFinalizado = { resumen ->
                        SesionDeRecoleccion.finalizar(resumen) // para 7.5; inofensivo si el ViewModel ya lo hizo
                        nav.navigate("admin/recoleccion/resumen?video=${resumen.videoId}") {
                            // saca 7.3 y 7.4 de la pila: el video ya terminó
                            popUpTo("admin/ubicacion-manual") { inclusive = true }
                        }
                    },
                    // Video sin fotos: se borró. Vuelve al panel.
                    onDescartado = { nav.popBackStack("admin/panel", inclusive = false) },
                    // Solo con error: SIN_INICIO (sin InicioRecoleccion ni video `en_curso` que retomar) o NO_SE_PUDO_CREAR.
                    onVolver = { nav.popBackStack() },
                    onAjustes = { nav.navigate("ajustes") },
                )
            }
        }

        // Mapa público (2.6) con seguimiento por pasos. Desde FE-3.1 se abre desde Inicio (voz «mapa» o acción de
        // TalkBack «Ver mapa»); en el APK de depuración también con MainActivity.EXTRA_RUTA (FE-2.3). Atrás vuelve a
        // Inicio. Su PdrTracker sigue el ciclo de vida de esta entrada de la pila, no el del proceso (ADR-FE-22).
        composable("mapa") {
            MapaPublicoScreen()
        }

        // 7.5 Resumen de video (FE-2.1). `video` = rec_NNNN, opcional: sin él, el de SesionDeRecoleccion.resumen
        // (o el recorrido sin subir más reciente). Navegar a "admin/recoleccion/resumen" sin argumento también vale.
        composable(
            "admin/recoleccion/resumen?video={video}",
            arguments = listOf(
                navArgument("video") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { entrada ->
            ResumenVideoScreen(
                videoId = entrada.arguments?.getString("video"),
                onIrAlPanel = {
                    // El Panel está debajo (7.4 → 7.5 saca 7.3 y 7.4; o se llegó desde el Panel).
                    if (!nav.popBackStack("admin/panel", inclusive = false)) {
                        nav.navigate("admin/panel") { popUpTo("inicio") }
                    }
                },
            )
        }

        // 7.6 Lista de lugares (FE-3.4). Se llega desde el Panel («Lugares»).
        composable("admin/lugares") {
            LugaresScreen(
                onVolver = { nav.popBackStack() },
                onNuevo = { nav.navigate("admin/lugares/form") },
                onEditar = { id -> nav.navigate("admin/lugares/form?id=$id") },
                onVerFotos = { id -> nav.navigate("admin/imagenes?lugar=$id") }, // FE-4.1
            )
        }

        // 7.7 Formulario de lugar (FE-3.4). `id` = UUID del lugar, opcional: sin él, lugar nuevo. Tras guardar,
        // eliminar, «Cancelar» o Atrás vuelve a 7.6 (que recarga por CambiosLugares).
        composable(
            "admin/lugares/form?id={id}",
            arguments = listOf(
                navArgument("id") {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { entrada ->
            LugarFormScreen(
                lugarId = entrada.arguments?.getString("id"),
                onListo = { nav.popBackStack() },
                onVerFotos = { id -> nav.navigate("admin/imagenes?lugar=$id") }, // FE-4.1
            )
        }

        // ── Placeholders para que los botones no cierren la app ──
        // (navegar a una ruta que no está registrada cierra la app con un error)
        composable("admin/estadisticas") { /* placeholder */ }
        composable("ajustes") { /* placeholder */ }
    }
}

/**
 * Muestra el diálogo nativo del sistema para pedir los permisos indicados.
 * Si ya están concedidos, llama a onResultado(true) sin mostrar nada.
 */
@Composable
fun PedirPermisos(
    permisos: Array<String>,
    onResultado: (todosConcedidos: Boolean) -> Unit,
) {
    val context = LocalContext.current

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { resultado ->
        onResultado(resultado.values.all { it })
    }

    LaunchedEffect(Unit) {
        val faltantes = permisos.filter {
            ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
        }
        if (faltantes.isEmpty()) {
            onResultado(true)
        } else {
            launcher.launch(faltantes.toTypedArray())
        }
    }
}