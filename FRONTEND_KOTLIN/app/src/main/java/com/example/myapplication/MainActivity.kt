package com.example.myapplication

import android.Manifest
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
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.myapplication.ui.inicio.InicioScreen
import com.example.myapplication.ui.destino.SeleccionDestinoScreen
import com.example.myapplication.ui.ubicacion.EscaneoScreen
import com.example.myapplication.ui.auth.LoginScreen
import com.example.myapplication.ui.admin.panel.PanelAdminScreen
import com.example.myapplication.ui.admin.mapa.EditorMapaScreen
import com.example.myapplication.ui.admin.imagenes.GaleriaScreen
import com.example.myapplication.ui.admin.videos.VideoDetalleScreen
import com.example.myapplication.ui.admin.videos.VideosScreen
import com.example.myapplication.map.MapaPublicoScreen
import com.example.myapplication.ui.admin.recoleccion.UbicacionManualScreen
import com.example.myapplication.ui.admin.recoleccion.RecoleccionScreen
import com.example.myapplication.ui.admin.calibracion.CalibracionScreen
import com.example.myapplication.domain.model.SesionDeRecoleccion
import com.example.myapplication.domain.model.Modulo
import com.example.myapplication.session.SessionManager
import com.example.myapplication.ui.admin.usuarios.UsuariosScreen


class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme {
                AppNav()
            }
        }
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
fun AppNav() {
    val nav = rememberNavController()

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
                    onUbicarme = { nav.navigate("ubicarme") },
                    onIrALugar = { nav.navigate("destino") },
                    onAccesoAdministrador = { nav.navigate("login") },
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
                    onCompletado = {
                        // TODO: navegar al resultado del escaneo
                        // nav.navigate("resultado")
                        nav.popBackStack()
                    },
                )
            }
        }

        // 6.4 Selección de destino
        composable("destino") {
            SeleccionDestinoScreen(
                onVolver = { nav.popBackStack() },
                onDestinoConfirmado = { _ ->
                    // TODO: guardar el destino elegido y, tras el escaneo 360° (si no hay ubicación
                    // vigente), abrir NavegacionScreen (6.5). Por ahora solo lanza el escaneo.
                    nav.navigate("ubicarme")
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
                onUsuarios = { nav.navigate("admin/usuarios") },
                onAjustes = { nav.navigate("ajustes") },
                onVolverModoPublico = { nav.popBackStack("inicio", inclusive = false) },
                onSesionCerrada = { nav.popBackStack("inicio", inclusive = false) },
                onSinSesion = {
                    nav.navigate("login") { popUpTo("admin/panel") { inclusive = true } }
                },
            )
        }

        // ── Vistas implementadas ──
        // Cada ruta admin se registra con rutaAdmin(): sin permiso del módulo vuelve al panel.

        rutaAdmin("admin/mapa", Modulo.MAPA, nav) {
            EditorMapaScreen(
                onVolver = { nav.popBackStack() },
                onVerLista = { /* vista 17 aún no existe */ },
                posicionAdmin = { null }
            )
        }

        rutaAdmin("admin/imagenes", Modulo.IMAGENES, nav) {
            GaleriaScreen(
                onVolver = { nav.popBackStack() },
                onAbrirImagen = { _, _ -> }, // placeholder: aún no existe la vista 7.12
            )
        }

        // 7.13 Lista de videos
        rutaAdmin("admin/videos", Modulo.VIDEOS, nav) {
            VideosScreen(
                onVolver = { nav.popBackStack() },
                onAbrirVideo = { id -> nav.navigate("admin/videos/$id") },
            )
        }

        // 7.14 Detalle de video
        rutaAdmin("admin/videos/{videoId}", Modulo.VIDEOS, nav) { entrada ->
            val videoId = entrada.arguments?.getString("videoId") ?: return@rutaAdmin
            VideoDetalleScreen(
                videoId = videoId,
                onVolver = { nav.popBackStack() },
                onAbrirImagen = { _, _ -> }, // placeholder: aún no existe la vista 7.12
            )
        }

        // HU-017 Gestión de usuarios
        rutaAdmin("admin/usuarios", Modulo.USUARIOS, nav) {
            UsuariosScreen(
                onVolver = { nav.popBackStack() },
                // El panel revalida el rol al mostrarse y oculta las tarjetas sin permiso.
                onSinAcceso = { volverAlPanel(nav) },
            )
        }

        // 7.3 Ubicación manual inicial
        rutaAdmin("admin/ubicacion-manual", Modulo.RECOLECCION, nav) {
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
                    onCalibrar = { nav.navigate("admin/calibracion") },   // ← esta línea
                )
            }
        }

        // 7.3b Calibración de la longitud de paso
        rutaAdmin("admin/calibracion", Modulo.RECOLECCION, nav) {
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
        rutaAdmin("admin/recoleccion", Modulo.RECOLECCION, nav) {
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
                        nav.navigate("admin/recoleccion/resumen") {
                            // saca 7.3 y 7.4 de la pila: el video ya terminó
                            popUpTo("admin/ubicacion-manual") { inclusive = true }
                        }
                    },
                    // Video sin fotos: se borró. Vuelve al panel.
                    onDescartado = { nav.popBackStack("admin/panel", inclusive = false) },
                    // Solo con error (p. ej. SIN_INICIO si Android restauró la pila tras matar el proceso).
                    onVolver = { nav.popBackStack() },
                    onAjustes = { nav.navigate("ajustes") },
                )
            }
        }

        // ── Placeholders para que los botones no cierren la app ──
        // (navegar a una ruta que no está registrada cierra la app con un error)
        // 7.5 Resumen de video: falta ResumenVideoScreen (leerá SesionDeRecoleccion.resumen).
        rutaAdmin("admin/recoleccion/resumen", Modulo.RECOLECCION, nav) { /* placeholder */ }
        rutaAdmin("admin/lugares", Modulo.MAPA, nav) { /* placeholder */ }
        rutaAdmin("admin/estadisticas", Modulo.RECOLECCION, nav) { /* placeholder */ }
        composable("ajustes") { /* placeholder */ }
    }
}

/**
 * Registra una ruta de administración protegida por [PoliticaAcceso][com.example.myapplication.domain.usecase.PoliticaAcceso]:
 * solo se compone si la sesión puede acceder a [modulo]; si no, vuelve al panel.
 */
private fun NavGraphBuilder.rutaAdmin(
    ruta: String,
    modulo: Modulo,
    nav: NavHostController,
    contenido: @Composable (NavBackStackEntry) -> Unit,
) {
    composable(ruta) { entrada ->
        val context = LocalContext.current
        val permitido = remember { SessionManager(context.applicationContext).puedeAcceder(modulo) }
        if (permitido) contenido(entrada)
        else LaunchedEffect(Unit) { volverAlPanel(nav) }
    }
}

/** Vuelve al panel; si no está en la pila (p. ej. pila restaurada), lo abre y él valida la sesión. */
private fun volverAlPanel(nav: NavHostController) {
    if (!nav.popBackStack("admin/panel", inclusive = false)) {
        nav.navigate("admin/panel") { popUpTo("inicio") }
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