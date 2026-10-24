package com.example.myapplication.ui.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Login
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.myapplication.ui.components.BannerEstado
import com.example.myapplication.ui.components.TipoBanner

// Paleta de la pantalla. Cuando exista ui/theme, mover aquí los tokens compartidos.
private val Fondo = Color(0xFF030615)
private val CampoFondo = Color(0xFF060C25)
private val CampoBorde = Color(0xFF2A3485)
private val Primario = Color(0xFF5B3CF5)
private val Acento = Color(0xFF8B6BFF)
private val TextoSecundario = Color(0xFFB9B2FF)
private val TextoPrincipal = Color(0xFFFFFFFF)

/**
 * Vista 7.1 — Login (flujo Admin).
 *
 * @param onLoginExitoso se invoca solo cuando hay sesión con rol ADMIN.
 * @param onVolver regresa al flujo público (Inicio).
 */
@Composable
fun LoginScreen(
    onLoginExitoso: () -> Unit,
    onVolver: () -> Unit,
    viewModel: LoginViewModel = viewModel(
        factory = LoginViewModel.Factory(LocalContext.current.applicationContext),
    ),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.eventos.collect { evento ->
            when (evento) {
                LoginEvento.IrAlPanel -> onLoginExitoso()
            }
        }
    }

    LoginContent(
        state = state,
        onIdentificadorChange = viewModel::onIdentificadorChange,
        onPasswordChange = viewModel::onPasswordChange,
        onTogglePassword = viewModel::onTogglePassword,
        onIniciarSesion = viewModel::iniciarSesion,
        onVolver = onVolver,
    )
}

@Composable
internal fun LoginContent(
    state: LoginUiState,
    onIdentificadorChange: (String) -> Unit,
    onPasswordChange: (String) -> Unit,
    onTogglePassword: () -> Unit,
    onIniciarSesion: () -> Unit,
    onVolver: () -> Unit,
) {
    val focus = LocalFocusManager.current

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Fondo)
            .systemBarsPadding()
            .imePadding(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .heightIn(min = maxHeight)
                .padding(horizontal = 24.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(24.dp))
            LogoCampusNavi()
            Spacer(Modifier.height(16.dp))

            Text(
                text = buildAnnotatedString {
                    withStyle(SpanStyle(color = TextoPrincipal)) { append("Campus ") }
                    withStyle(SpanStyle(color = Acento)) { append("Navi") }
                },
                fontSize = 44.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.semantics { heading() },
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Accesibilidad y orientación\npara todos",
                color = TextoSecundario,
                fontSize = 20.sp,
                lineHeight = 28.sp,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(40.dp))

            CampoLogin(
                valor = state.identificador,
                onValor = onIdentificadorChange,
                etiqueta = "Correo o usuario",
                icono = Icons.Outlined.Person,
                teclado = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                acciones = KeyboardActions(onNext = { focus.moveFocus(androidx.compose.ui.focus.FocusDirection.Down) }),
                habilitado = !state.cargando,
            )
            Spacer(Modifier.height(16.dp))
            CampoLogin(
                valor = state.password,
                onValor = onPasswordChange,
                etiqueta = "Contraseña",
                icono = Icons.Outlined.Lock,
                visual = if (state.mostrarPassword) VisualTransformation.None else PasswordVisualTransformation(),
                teclado = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                acciones = KeyboardActions(onDone = {
                    focus.clearFocus()
                    onIniciarSesion()
                }),
                habilitado = !state.cargando,
                trailing = {
                    IconButton(onClick = onTogglePassword, modifier = Modifier.size(56.dp)) {
                        Icon(
                            imageVector = if (state.mostrarPassword) Icons.Outlined.Visibility else Icons.Outlined.VisibilityOff,
                            contentDescription = if (state.mostrarPassword) "Ocultar contraseña" else "Mostrar contraseña",
                            tint = Acento,
                        )
                    }
                },
            )

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = {
                    focus.clearFocus()
                    onIniciarSesion()
                },
                enabled = state.puedeEnviar,
                modifier = Modifier.fillMaxWidth().heightIn(min = 68.dp),
                shape = RoundedCornerShape(22.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Primario,
                    contentColor = Color.White,
                    disabledContainerColor = Primario.copy(alpha = 0.35f),
                    disabledContentColor = Color.White.copy(alpha = 0.6f),
                ),
            ) {
                Icon(Icons.AutoMirrored.Outlined.Login, contentDescription = null, modifier = Modifier.size(28.dp))
                Spacer(Modifier.width(16.dp))
                Text("Iniciar sesión", fontSize = 22.sp, fontWeight = FontWeight.Medium)
            }

            // Zona de estado: carga o error (mutuamente excluyentes).
            Column(
                modifier = Modifier.fillMaxWidth().animateContentSize().padding(top = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                AnimatedVisibility(visible = state.cargando) { IndicadorCarga() }
                AnimatedVisibility(visible = state.error != null) {
                    state.error?.let { BannerError(it) }
                }
            }

            Spacer(Modifier.weight(1f).heightIn(min = 32.dp))

            OutlinedButton(
                onClick = onVolver,
                modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp),
                shape = RoundedCornerShape(22.dp),
                border = BorderStroke(1.5.dp, Primario),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Acento),
            ) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = null, modifier = Modifier.size(26.dp))
                Spacer(Modifier.width(14.dp))
                Text("Volver al inicio", fontSize = 20.sp, fontWeight = FontWeight.Medium)
            }
        }
    }
}

@Composable
private fun CampoLogin(
    valor: String,
    onValor: (String) -> Unit,
    etiqueta: String,
    icono: androidx.compose.ui.graphics.vector.ImageVector,
    teclado: KeyboardOptions,
    acciones: KeyboardActions,
    habilitado: Boolean,
    visual: VisualTransformation = VisualTransformation.None,
    trailing: (@Composable () -> Unit)? = null,
) {
    OutlinedTextField(
        value = valor,
        onValueChange = onValor,
        modifier = Modifier.fillMaxWidth().heightIn(min = 68.dp),
        enabled = habilitado,
        singleLine = true,
        label = { Text(etiqueta) },
        leadingIcon = { Icon(icono, contentDescription = null, modifier = Modifier.size(28.dp)) },
        trailingIcon = trailing,
        visualTransformation = visual,
        keyboardOptions = teclado,
        keyboardActions = acciones,
        shape = RoundedCornerShape(22.dp),
        textStyle = androidx.compose.ui.text.TextStyle(fontSize = 20.sp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = TextoPrincipal,
            unfocusedTextColor = TextoPrincipal,
            disabledTextColor = TextoPrincipal.copy(alpha = 0.6f),
            focusedContainerColor = CampoFondo,
            unfocusedContainerColor = CampoFondo,
            disabledContainerColor = CampoFondo,
            focusedBorderColor = Acento,
            unfocusedBorderColor = CampoBorde,
            disabledBorderColor = CampoBorde.copy(alpha = 0.5f),
            focusedLabelColor = Acento,
            unfocusedLabelColor = Acento,
            disabledLabelColor = Acento.copy(alpha = 0.5f),
            focusedLeadingIconColor = Acento,
            unfocusedLeadingIconColor = Acento,
            disabledLeadingIconColor = Acento.copy(alpha = 0.5f),
            cursorColor = Acento,
        ),
    )
}

@Composable
private fun IndicadorCarga() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(32.dp),
            color = Acento,
            trackColor = CampoBorde,
            strokeWidth = 3.dp,
        )
        Spacer(Modifier.width(16.dp))
        Text("Verificando credenciales…", color = TextoSecundario, fontSize = 18.sp)
    }
}

@Composable
private fun BannerError(error: LoginError) {
    when (error) {
        LoginError.CredencialesInvalidas -> BannerEstado(
            tipo = TipoBanner.Error,
            icono = Icons.Outlined.ErrorOutline,
            titulo = "Credenciales inválidas",
            mensaje = "El usuario o la contraseña son incorrectos.",
        )
        LoginError.SinConexion -> BannerEstado(
            tipo = TipoBanner.Advertencia,
            icono = Icons.Outlined.WarningAmber,
            titulo = "Sin conexión",
            mensaje = "No se puede conectar con el servidor.\nVerifica tu conexión a internet.",
        )
        LoginError.SinPermisos -> BannerEstado(
            tipo = TipoBanner.Error,
            icono = Icons.Outlined.Lock,
            titulo = "Sin permisos",
            mensaje = "Tu cuenta no tiene rol de administrador, por eso no se habilita el panel.",
        )
        LoginError.Desconocido -> BannerEstado(
            tipo = TipoBanner.Error,
            icono = Icons.Outlined.ErrorOutline,
            titulo = "Algo salió mal",
            mensaje = "No pudimos iniciar sesión. Inténtalo de nuevo.",
        )
    }
}

/** Logo: pin de ubicación con órbita. Dibujado en Canvas para no depender de assets. */
@Composable
private fun LogoCampusNavi(modifier: Modifier = Modifier) {
    Canvas(
        modifier = modifier
            .size(width = 130.dp, height = 112.dp)
            .semantics { contentDescription = "Logo de Campus Navi" },
    ) {
        val w = size.width
        val h = size.height
        val cx = w / 2f
        val r = w * 0.27f
        val cy = r + h * 0.03f
        val degradado = Brush.verticalGradient(listOf(Color(0xFF9A7BFF), Color(0xFF5B3CF5)))

        // Órbita
        rotate(degrees = -18f, pivot = Offset(cx, h * 0.5f)) {
            drawOval(
                brush = degradado,
                topLeft = Offset(w * 0.02f, h * 0.34f),
                size = Size(w * 0.96f, h * 0.42f),
                style = Stroke(width = w * 0.05f, cap = StrokeCap.Round),
                alpha = 0.85f,
            )
        }

        // Pin
        val pin = Path().apply {
            moveTo(cx, h * 0.97f)
            cubicTo(cx - r * 0.35f, h * 0.78f, cx - r, h * 0.58f, cx - r, cy)
            arcTo(Rect(cx - r, cy - r, cx + r, cy + r), 180f, 180f, false)
            cubicTo(cx + r, h * 0.58f, cx + r * 0.35f, h * 0.78f, cx, h * 0.97f)
            close()
        }
        drawPath(pin, brush = degradado)
        drawCircle(color = Fondo, radius = r * 0.45f, center = Offset(cx, cy))
        drawCircle(color = Acento, radius = r * 0.2f, center = Offset(cx, cy))
    }
}

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewLoginVacio() = LoginContent(LoginUiState(), {}, {}, {}, {}, {})

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewLoginCargando() = LoginContent(
    LoginUiState("admin@campus.edu.co", "12345678", cargando = true), {}, {}, {}, {}, {},
)

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewLoginCredencialesInvalidas() = LoginContent(
    LoginUiState("admin@campus.edu.co", "12345678", error = LoginError.CredencialesInvalidas), {}, {}, {}, {}, {},
)

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun PreviewLoginSinConexion() = LoginContent(
    LoginUiState("admin@campus.edu.co", "12345678", error = LoginError.SinConexion), {}, {}, {}, {}, {},
)