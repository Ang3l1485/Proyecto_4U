"""`POST /v1/auth/login` (ARCHITECTURE §4.4, §5.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencias import obtener_ajustes, obtener_cola_hash, obtener_motor
from app.config import Settings
from app.errores import ErrorApi
from app.esquemas.auth import LoginPeticion, LoginRespuesta, UsuarioSesion
from app.esquemas.errores import ErrorRespuesta
from app.seguridad import tokens
from app.seguridad.dependencias import sin_clave_jwt
from app.servicios import autenticacion

router = APIRouter(prefix="/auth", tags=["autenticación"])

#: `Retry-After` de `503 SERVICIO_OCUPADO` (§5.3), en segundos.
REINTENTAR_TRAS_S = 5


@router.post(
    "/login",
    response_model=LoginRespuesta,
    summary="Iniciar sesión",
    responses={
        401: {"model": ErrorRespuesta, "description": "CREDENCIALES_INVALIDAS"},
        422: {"model": ErrorRespuesta, "description": "VALIDACION"},
        503: {"model": ErrorRespuesta, "description": "BASE_NO_DISPONIBLE · SERVICIO_OCUPADO (con Retry-After)"},
    },
)
async def login(
    peticion: LoginPeticion,
    request: Request,
    ajustes: Settings = Depends(obtener_ajustes),
    cola: autenticacion.ColaHash = Depends(obtener_cola_hash),
) -> LoginRespuesta:
    """Devuelve el token también a usuarios `user`: la app decide no abrir el panel. Cada intento en el que se
    comprueba la contraseña queda en `auditoria`. Correo inexistente, contraseña incorrecta y usuario inactivo
    responden lo mismo."""
    try:
        tokens.clave(ajustes)  # sin JWT_SECRET: 500 antes de mirar la base
    except tokens.ClaveNoConfigurada:
        raise sin_clave_jwt() from None
    motor = obtener_motor(request)  # sin motor: 503 BASE_NO_DISPONIBLE
    try:
        sesion_iniciada = await autenticacion.iniciar_sesion(
            motor, ajustes, peticion.identificador, peticion.password, cola=cola
        )
    except autenticacion.CredencialesInvalidas:
        raise ErrorApi(401, "CREDENCIALES_INVALIDAS") from None
    except autenticacion.Saturado:
        raise ErrorApi(503, "SERVICIO_OCUPADO", encabezados={"Retry-After": str(REINTENTAR_TRAS_S)}) from None
    return LoginRespuesta(
        token=sesion_iniciada.token.token,
        expira_en=sesion_iniciada.token.expira_en,
        usuario=UsuarioSesion(
            id=sesion_iniciada.usuario_id,
            nombre=sesion_iniciada.nombre,
            correo=sesion_iniciada.correo,
            rol=sesion_iniciada.rol,
        ),
    )
