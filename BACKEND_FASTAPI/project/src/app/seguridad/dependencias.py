"""Dependencia `requiere_admin` (ARCHITECTURE §4.4, §5.2, ADR-BE-03).

Protege todo `/v1/admin/*` y `/v1/collect/*` (se pone en los routers de `app/api/v1/__init__.py`). Rechazos, en este
orden (el primero que aplica):
1. Sin encabezado `Authorization`, con otro esquema que `Bearer` o sin token → `401 NO_AUTENTICADO`.
2. Token con firma vencida → `401 TOKEN_EXPIRADO`; cualquier otro defecto del token → `401 TOKEN_INVALIDO`
   (`tokens.decodificar`).
3. `sub` que no es un usuario, o usuario desactivado → `401 TOKEN_INVALIDO` (consulta a la base en cada petición).
4. Rol distinto de `admin` en el token o en la base → `403 SIN_PERMISOS`.

Los `401` llevan `WWW-Authenticate: Bearer`. Sin `JWT_SECRET`, `500 ERROR_INTERNO` (evento `configuracion_incompleta`).
Devuelve el `UsuarioActual` con los datos de la base; un endpoint que lo necesite lo declara con
`usuario: UsuarioActual = Depends(requiere_admin)` (FastAPI lo evalúa una sola vez por petición).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.dependencias import obtener_ajustes, obtener_motor
from app.config import Settings
from app.db import sesion
from app.db.modelos import Usuario
from app.dominio.enumerados import RolUsuario
from app.errores import ErrorApi
from app.logs import obtener_logger, registrar
from app.seguridad import tokens

log = obtener_logger(__name__)

_portador = HTTPBearer(
    auto_error=False,
    scheme_name="jwt",
    bearerFormat="JWT",
    description="Token de `POST /v1/auth/login` (ARCHITECTURE §5.2)",
)
_DESAFIO = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class UsuarioActual:
    id: uuid.UUID
    nombre: str
    correo: str
    rol: RolUsuario


def _rechazo(estado: int, codigo: str, usuario_id: uuid.UUID | None = None) -> ErrorApi:
    registrar(
        log,
        "autorizacion_rechazada",
        codigo=codigo,
        usuario_id=str(usuario_id) if usuario_id is not None else None,
    )
    return ErrorApi(estado, codigo, encabezados=_DESAFIO if estado == 401 else None)


def sin_clave_jwt() -> ErrorApi:
    """`500 ERROR_INTERNO` por falta de `JWT_SECRET`, con su evento (lo usan el login y `requiere_admin`)."""
    registrar(
        log,
        "configuracion_incompleta",
        logging.ERROR,
        faltan=["JWT_SECRET"],
        invalidas=[],
        motivo="falta JWT_SECRET: no se pueden emitir ni comprobar tokens",
    )
    return ErrorApi(500, "ERROR_INTERNO")


async def requiere_admin(
    request: Request,
    credenciales: HTTPAuthorizationCredentials | None = Depends(_portador),
    ajustes: Settings = Depends(obtener_ajustes),
) -> UsuarioActual:
    if credenciales is None or not credenciales.credentials:
        raise _rechazo(401, "NO_AUTENTICADO")
    try:
        claims = tokens.decodificar(credenciales.credentials, ajustes)
    except tokens.ClaveNoConfigurada:
        raise sin_clave_jwt() from None
    except tokens.TokenExpirado:
        raise _rechazo(401, "TOKEN_EXPIRADO") from None
    except tokens.TokenInvalido:
        raise _rechazo(401, "TOKEN_INVALIDO") from None

    # La base se mira después del token: sin token válido, la respuesta no depende de que la base esté disponible.
    motor = obtener_motor(request)
    async with sesion.transaccion(motor) as conexion:
        fila = (
            await conexion.execute(
                select(Usuario.id, Usuario.nombre, Usuario.correo, Usuario.rol, Usuario.activo).where(
                    Usuario.id == claims.sub
                )
            )
        ).first()
    if fila is None or not fila.activo:
        raise _rechazo(401, "TOKEN_INVALIDO", claims.sub)
    if claims.rol != RolUsuario.admin or fila.rol != RolUsuario.admin:
        raise _rechazo(403, "SIN_PERMISOS", claims.sub)
    return UsuarioActual(id=fila.id, nombre=fila.nombre, correo=fila.correo, rol=fila.rol)
