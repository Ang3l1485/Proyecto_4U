package com.example.myapplication.ui.destino

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.MicOff
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.data.repository.LUGARES_DE_PRUEBA
import com.example.myapplication.domain.model.CategoriaLugar
import com.example.myapplication.domain.model.LugarDestino
import com.example.myapplication.ui.components.BannerEstado
import com.example.myapplication.ui.components.TipoBanner
import com.example.myapplication.ui.theme.CampusColors
import com.example.myapplication.ui.destino.componentes.BarraSuperior
import com.example.myapplication.ui.destino.componentes.BotonVolver
import com.example.myapplication.ui.destino.componentes.CampoBusqueda
import com.example.myapplication.ui.destino.componentes.EncabezadoLista
import com.example.myapplication.ui.destino.componentes.EncabezadoPregunta
import com.example.myapplication.ui.destino.componentes.EstadoVacio
import com.example.myapplication.ui.destino.componentes.FilaCategorias
import com.example.myapplication.ui.destino.componentes.FilaLugar
import com.example.myapplication.ui.destino.componentes.TarjetaConfirmacion
import com.example.myapplication.ui.destino.componentes.TarjetaOpciones
import com.example.myapplication.ui.destino.componentes.TarjetaTextoReconocido
import com.example.myapplication.ui.destino.componentes.ZonaMicrofono

/*
 * Vista 6.4 — Selección de destino.
 *
 * Este archivo solo "conecta" cosas (permiso de micrófono, ciclo de vida, ViewModel, navegación).
 *   - Lógica de voz, búsqueda y confirmación -> SeleccionDestinoViewModel
 *   - Estado y eventos                       -> SeleccionDestinoState
 *   - Piezas visuales                        -> componentes/
 *   - Coincidencia aproximada y sí / no      -> domain/usecase/BuscarLugares
 */

// ============================================================================
// Pantalla con estado (se conecta con Android y con el ViewModel)
// ============================================================================

@Composable
fun SeleccionDestinoScreen(
    onVolver: () -> Unit,
    onDestinoConfirmado: (LugarDestino) -> Unit,
    onAjustes: () -> Unit = {},
    viewModel: SeleccionDestinoViewModel = viewModel(),
) {
    val ctx = LocalContext.current
    val estado by viewModel.estado.collectAsStateWithLifecycle()

    // El permiso ya se pide en Inicio. Si se negó, la vista sigue funcionando solo con toques.
    val microfonoOk = remember {
        ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }
    LaunchedEffect(Unit) { viewModel.alAbrir(microfonoOk) }

    // Eventos de una sola vez: el destino quedó confirmado.
    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                is DestinoEvento.Confirmado -> onDestinoConfirmado(evento.lugar)
            }
        }
    }

    // Al dejar de verse la pantalla, calla y deja de escuchar.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val obs = LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_STOP) viewModel.alPausar()
        }
        lifecycleOwner.lifecycle.addObserver(obs)
        onDispose { lifecycleOwner.lifecycle.removeObserver(obs) }
    }

    // Volver (botón, flecha o atrás del sistema): callar antes de salir.
    val salir = { viewModel.alSalir(); onVolver() }
    BackHandler(onBack = salir)

    val acciones = remember(viewModel) {
        DestinoAcciones(
            onVolver = salir,
            onAjustes = onAjustes,
            onMicrofono = viewModel::alPresionarMicrofono,
            onDescartarTexto = viewModel::descartarTexto,
            onSi = viewModel::alResponderSi,
            onNo = viewModel::alResponderNo,
            onElegirLugar = viewModel::alElegirLugar,
            onCategoria = viewModel::alElegirCategoria,
            onBusqueda = viewModel::alCambiarBusqueda,
            onCambiarOrden = viewModel::alCambiarOrden,
            onLimpiarFiltros = viewModel::limpiarFiltros,
            onReintentar = viewModel::reintentarCarga,
        )
    }

    SeleccionDestinoContent(estado = estado, acciones = acciones)
}

/** Todo lo que la pantalla puede pedirle al ViewModel (así el contenido no conoce al ViewModel). */
class DestinoAcciones(
    val onVolver: () -> Unit,
    val onAjustes: () -> Unit,
    val onMicrofono: () -> Unit,
    val onDescartarTexto: () -> Unit,
    val onSi: () -> Unit,
    val onNo: () -> Unit,
    val onElegirLugar: (LugarDestino) -> Unit,
    val onCategoria: (CategoriaLugar?) -> Unit,
    val onBusqueda: (String) -> Unit,
    val onCambiarOrden: () -> Unit,
    val onLimpiarFiltros: () -> Unit,
    val onReintentar: () -> Unit,
)

// ============================================================================
// Contenido sin lógica (solo dibuja el estado recibido)
// ============================================================================

@Composable
fun SeleccionDestinoContent(
    estado: DestinoUiState,
    acciones: DestinoAcciones,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(CampusColors.Fondo)
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding(),
    ) {
        BarraSuperior(onAtras = acciones.onVolver, onAjustes = acciones.onAjustes)

        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item { EncabezadoPregunta() }

            item {
                ZonaMicrofono(escuchando = estado.escuchando, onClick = acciones.onMicrofono)
            }

            if (estado.sinMicrofono) {
                item {
                    BannerEstado(
                        tipo = TipoBanner.Advertencia,
                        icono = Icons.Outlined.MicOff,
                        titulo = "Sin micrófono",
                        mensaje = "Elige un lugar de la lista o usa el buscador.",
                    )
                }
            }

            estado.textoReconocido?.let { texto ->
                item { TarjetaTextoReconocido(texto = texto, onDescartar = acciones.onDescartarTexto) }
            }

            estado.candidato?.let { lugar ->
                item { TarjetaConfirmacion(lugar = lugar, onSi = acciones.onSi, onNo = acciones.onNo) }
            }

            if (estado.candidato == null && estado.opciones.isNotEmpty()) {
                item { TarjetaOpciones(opciones = estado.opciones, onElegir = acciones.onElegirLugar) }
            }

            item { FilaCategorias(seleccionada = estado.categoria, onElegir = acciones.onCategoria) }

            item { CampoBusqueda(texto = estado.busqueda, onCambio = acciones.onBusqueda) }

            item { EncabezadoLista(orden = estado.orden, onCambiarOrden = acciones.onCambiarOrden) }

            when {
                estado.cargando -> item {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(24.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(color = CampusColors.Acento)
                    }
                }

                estado.error != null -> item {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        BannerEstado(
                            tipo = TipoBanner.Error,
                            icono = Icons.Outlined.WifiOff,
                            titulo = "Sin conexión",
                            mensaje = "No se pudo cargar la lista de lugares.",
                        )
                        EstadoVacio(
                            mensaje = null,
                            accion = "Reintentar",
                            onAccion = acciones.onReintentar,
                        )
                    }
                }

                estado.lugares.isEmpty() -> item {
                    EstadoVacio(
                        mensaje = "No hay lugares con estos filtros",
                        accion = "Limpiar filtros",
                        onAccion = acciones.onLimpiarFiltros,
                    )
                }

                else -> items(estado.lugares, key = { it.id }) { lugar ->
                    FilaLugar(lugar = lugar, onClick = { acciones.onElegirLugar(lugar) })
                }
            }
        }

        BotonVolver(onClick = acciones.onVolver)
    }
}

// ============================================================================
// Preview
// ============================================================================

@Preview(showBackground = true, backgroundColor = 0xFF030615, widthDp = 400, heightDp = 880)
@Composable
private fun PreviewSeleccionDestino() {
    SeleccionDestinoContent(
        estado = DestinoUiState(
            cargando = false,
            escuchando = true,
            textoReconocido = "biblioteca",
            candidato = LUGARES_DE_PRUEBA.first(),
            lugares = LUGARES_DE_PRUEBA.take(4),
        ),
        acciones = DestinoAcciones({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}),
    )
}
