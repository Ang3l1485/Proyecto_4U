package com.example.myapplication.ui.admin.usuarios

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.domain.model.Rol
import com.example.myapplication.domain.model.Usuario
import com.example.myapplication.ui.theme.CampusColors as C

/** Callbacks de las acciones de la pantalla de usuarios. */
data class UsuariosAcciones(
    val onVolver: () -> Unit = {},
    val onReintentar: () -> Unit = {},
    val onCambiarRol: (Usuario) -> Unit = {},
    val onCambiarEstado: (Usuario) -> Unit = {},
    val onConfirmarRol: (Usuario, Rol) -> Unit = { _, _ -> },
    val onConfirmarEstado: (Usuario, Boolean) -> Unit = { _, _ -> },
    val onCerrarDialogo: () -> Unit = {},
    val onMensajeMostrado: () -> Unit = {},
)

/**
 * HU-017 — Gestión de usuarios: lista, cambio de rol y activación/desactivación.
 *
 * @param onSinAcceso se invoca si el admin pierde el permiso USUARIOS (p. ej. se quitó su propio rol).
 */
@Composable
fun UsuariosScreen(
    onVolver: () -> Unit,
    onSinAcceso: () -> Unit,
    viewModel: UsuariosViewModel = viewModel(
        factory = UsuariosViewModel.Factory(LocalContext.current.applicationContext),
    ),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                UsuariosEvento.SinAcceso -> onSinAcceso()
            }
        }
    }

    UsuariosContent(
        state = state,
        acciones = UsuariosAcciones(
            onVolver = onVolver,
            onReintentar = viewModel::cargar,
            onCambiarRol = viewModel::abrirCambioRol,
            onCambiarEstado = viewModel::pedirCambioEstado,
            onConfirmarRol = viewModel::cambiarRol,
            onConfirmarEstado = viewModel::confirmarCambioEstado,
            onCerrarDialogo = viewModel::cerrarDialogo,
            onMensajeMostrado = viewModel::mensajeMostrado,
        ),
    )
}

@Composable
internal fun UsuariosContent(state: UsuariosUiState, acciones: UsuariosAcciones) {
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.mensaje) {
        state.mensaje?.let {
            snackbar.showSnackbar(it)
            acciones.onMensajeMostrado()
        }
    }

    Scaffold(
        containerColor = C.Fondo,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().background(C.Fondo).padding(horizontal = 4.dp, vertical = 4.dp),
            ) {
                IconButton(onClick = acciones.onVolver, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver", tint = C.Acento)
                }
                Text(
                    "Usuarios",
                    color = C.TextoPrincipal,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f).semantics { heading() },
                )
                Box(Modifier.size(48.dp))
            }
        },
    ) { padding ->
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            when {
                state.cargando -> item {
                    Box(
                        Modifier.fillMaxWidth().padding(48.dp).semantics { contentDescription = "Cargando usuarios" },
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(color = C.Acento)
                    }
                }
                state.error != null -> item { Mensaje(state.error, "Reintentar", acciones.onReintentar) }
                state.usuarios.isEmpty() -> item { Mensaje("No hay usuarios registrados.") }
                else -> {
                    item {
                        Text(
                            if (state.usuarios.size == 1) "1 usuario" else "${state.usuarios.size} usuarios",
                            color = C.TextoSecundario,
                            fontSize = 16.sp,
                        )
                    }
                    items(state.usuarios, key = { it.id }) { usuario ->
                        TarjetaUsuario(
                            usuario = usuario,
                            esSesion = usuario.id == state.idSesion,
                            procesando = usuario.id == state.procesando,
                            onCambiarRol = { acciones.onCambiarRol(usuario) },
                            onCambiarEstado = { acciones.onCambiarEstado(usuario) },
                        )
                    }
                }
            }
        }
    }

    when (val dialogo = state.dialogo) {
        is DialogoUsuarios.CambiarRol -> DialogoRol(
            usuario = dialogo.usuario,
            onConfirmar = { rol -> acciones.onConfirmarRol(dialogo.usuario, rol) },
            onCancelar = acciones.onCerrarDialogo,
        )
        is DialogoUsuarios.ConfirmarEstado -> DialogoEstado(
            usuario = dialogo.usuario,
            activar = dialogo.activar,
            onConfirmar = { acciones.onConfirmarEstado(dialogo.usuario, dialogo.activar) },
            onCancelar = acciones.onCerrarDialogo,
        )
        null -> Unit
    }
}

// ───────────────────────────── Tarjeta ─────────────────────────────

@Composable
private fun TarjetaUsuario(
    usuario: Usuario,
    esSesion: Boolean,
    procesando: Boolean,
    onCambiarRol: () -> Unit,
    onCambiarEstado: () -> Unit,
) {
    val forma = RoundedCornerShape(16.dp)
    val estado = if (usuario.activo) "Activo" else "Inactivo"
    val nombre = if (esSesion) "${usuario.nombre} (Tú)" else usuario.nombre

    Column(
        Modifier
            .fillMaxWidth()
            .clip(forma)
            .background(C.Superficie)
            .border(1.dp, C.Borde, forma)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Column(
            Modifier.semantics(mergeDescendants = true) {
                contentDescription = "$nombre, ${usuario.correo}, rol ${usuario.rol.texto()}, $estado"
            },
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(nombre, color = C.TextoPrincipal, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Text(usuario.correo, color = C.TextoSuave, fontSize = 14.sp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(usuario.rol.texto(), color = C.TextoSecundario, fontSize = 14.sp)
                Spacer(Modifier.width(12.dp))
                Box(Modifier.size(10.dp).background(if (usuario.activo) C.Exito else C.TextoSuave, CircleShape))
                Text(estado, color = C.TextoSuave, fontSize = 14.sp, modifier = Modifier.padding(start = 6.dp))
            }
        }

        if (procesando) {
            CircularProgressIndicator(
                color = C.Acento,
                modifier = Modifier.size(32.dp).semantics { contentDescription = "Aplicando cambios a ${usuario.nombre}" },
            )
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(
                    onClick = onCambiarRol,
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 48.dp)
                        .semantics { contentDescription = "Cambiar rol de ${usuario.nombre}" },
                    border = BorderStroke(1.dp, C.Borde),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = C.Acento),
                ) { Text("Cambiar rol") }
                OutlinedButton(
                    onClick = onCambiarEstado,
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 48.dp)
                        .semantics {
                            contentDescription =
                                (if (usuario.activo) "Desactivar a " else "Activar a ") + usuario.nombre
                        },
                    border = BorderStroke(1.dp, if (usuario.activo) C.Peligro else C.Exito),
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = if (usuario.activo) C.Peligro else C.Exito,
                    ),
                ) { Text(if (usuario.activo) "Desactivar" else "Activar") }
            }
        }
    }
}

// ───────────────────────────── Diálogos ─────────────────────────────

@Composable
private fun DialogoRol(usuario: Usuario, onConfirmar: (Rol) -> Unit, onCancelar: () -> Unit) {
    var seleccion by remember(usuario.id) { mutableStateOf(usuario.rol) }
    AlertDialog(
        onDismissRequest = onCancelar,
        containerColor = C.SuperficieAlta,
        title = {
            Text(
                "Cambiar rol de ${usuario.nombre}",
                color = C.TextoPrincipal,
                modifier = Modifier.semantics { heading() },
            )
        },
        text = {
            Column(Modifier.selectableGroup()) {
                Rol.entries.forEach { rol ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .selectable(
                                selected = rol == seleccion,
                                role = Role.RadioButton,
                                onClick = { seleccion = rol },
                            )
                            .semantics(mergeDescendants = true) { contentDescription = "Rol ${rol.texto()}" },
                    ) {
                        RadioButton(
                            selected = rol == seleccion,
                            onClick = null,
                            colors = RadioButtonDefaults.colors(selectedColor = C.Acento, unselectedColor = C.TextoSuave),
                        )
                        Spacer(Modifier.width(12.dp))
                        Text(rol.texto(), color = C.TextoPrincipal, fontSize = 16.sp)
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirmar(seleccion) },
                enabled = seleccion != usuario.rol,
                colors = ButtonDefaults.buttonColors(containerColor = C.Primario),
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "Guardar rol" },
            ) { Text("Guardar") }
        },
        dismissButton = {
            TextButton(
                onClick = onCancelar,
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "Cancelar cambio de rol" },
            ) { Text("Cancelar", color = C.Acento) }
        },
    )
}

@Composable
private fun DialogoEstado(usuario: Usuario, activar: Boolean, onConfirmar: () -> Unit, onCancelar: () -> Unit) {
    val verbo = if (activar) "Activar" else "Desactivar"
    AlertDialog(
        onDismissRequest = onCancelar,
        containerColor = C.SuperficieAlta,
        title = {
            Text("$verbo a ${usuario.nombre}", color = C.TextoPrincipal, modifier = Modifier.semantics { heading() })
        },
        text = {
            Text(
                if (activar) "${usuario.correo} podrá volver a iniciar sesión."
                else "${usuario.correo} no podrá iniciar sesión hasta que se reactive la cuenta.",
                color = C.TextoSuave,
                fontSize = 16.sp,
            )
        },
        confirmButton = {
            Button(
                onClick = onConfirmar,
                colors = ButtonDefaults.buttonColors(containerColor = if (activar) C.Primario else C.Peligro),
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "Confirmar: $verbo a ${usuario.nombre}" },
            ) { Text(verbo) }
        },
        dismissButton = {
            TextButton(
                onClick = onCancelar,
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "Cancelar" },
            ) { Text("Cancelar", color = C.Acento) }
        },
    )
}

@Composable
private fun Mensaje(texto: String, accion: String? = null, onAccion: () -> Unit = {}) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp),
    ) {
        Text(texto, color = C.TextoSuave, fontSize = 16.sp, modifier = Modifier.semantics { contentDescription = texto })
        if (accion != null) {
            Button(
                onClick = onAccion,
                colors = ButtonDefaults.buttonColors(containerColor = C.Primario),
                modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = "$accion carga de usuarios" },
            ) { Text(accion) }
        }
    }
}

// ───────────────────────────── Previews ─────────────────────────────

private val usuariosPreview = listOf(
    Usuario("1", "Administrador", "admin@campus.edu.co", Rol.ADMIN),
    Usuario("2", "Investigador", "investigador@campus.edu.co", Rol.INVESTIGADOR),
    Usuario("3", "Usuario", "user@campus.edu.co", Rol.USER, activo = false),
)

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewUsuarios() = UsuariosContent(
    UsuariosUiState(cargando = false, usuarios = usuariosPreview, idSesion = "1"),
    UsuariosAcciones(),
)

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewUsuariosVacio() = UsuariosContent(UsuariosUiState(cargando = false), UsuariosAcciones())

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewUsuariosError() = UsuariosContent(
    UsuariosUiState(cargando = false, error = "No se pudieron cargar los usuarios."),
    UsuariosAcciones(),
)
