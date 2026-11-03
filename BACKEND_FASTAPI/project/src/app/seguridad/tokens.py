"""JWT de sesión (ARCHITECTURE §5.2, ADR-BE-03): HS256 con `JWT_SECRET` usada como texto, emisor fijo.

El módulo no se llama `jwt.py` para no confundirse con el paquete `jwt` (PyJWT), que es el que firma y comprueba.

- `emitir(...)` firma un token con los *claims* de §5.2 y devuelve también `expira_en` (= `exp`).
- `decodificar(token, ajustes)` comprueba firma (solo HS256), emisor, *claims* obligatorios y vencimiento (sin
  margen). Lanza `TokenExpirado` (firma válida y `exp` pasado), `TokenInvalido` (todo lo demás) o
  `ClaveNoConfigurada` (falta `JWT_SECRET`).

Que el usuario siga activo y con rol `admin` no se mira aquí: lo hace `requiere_admin` contra la base.
Nunca registrar un token ni la clave.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt

from app.config import Settings
from app.dominio.enumerados import RolUsuario

ALGORITMO = "HS256"
EMISOR = "campus-locator-api"
#: Claims de §5.2: todos obligatorios, y no se emite ninguno más.
CLAIMS = ("iss", "sub", "rol", "nombre", "iat", "exp", "jti")


class ClaveNoConfigurada(Exception):
    """Falta `JWT_SECRET` (infra §5.4) o está vacía."""


class TokenInvalido(Exception):
    """Formato, firma, algoritmo, emisor o *claims* no válidos: `401 TOKEN_INVALIDO` (§5.2)."""


class TokenExpirado(Exception):
    """Firma válida pero `exp` ya pasó: `401 TOKEN_EXPIRADO` (§5.2)."""


@dataclass(frozen=True)
class TokenEmitido:
    token: str
    expira_en: datetime  # = exp, en UTC y sin fracción de segundo
    jti: str


@dataclass(frozen=True)
class Claims:
    sub: uuid.UUID
    rol: RolUsuario
    nombre: str
    iat: int
    exp: int
    jti: str


def clave(ajustes: Settings) -> str:
    """`JWT_SECRET` tal cual (la cadena base64 de infra §5.4, sin decodificar). PyJWT usa sus bytes UTF-8."""
    secreto = ajustes.jwt_secret.get_secret_value() if ajustes.jwt_secret is not None else ""
    if not secreto:
        raise ClaveNoConfigurada("falta JWT_SECRET")
    return secreto


def emitir(
    *, usuario_id: uuid.UUID, rol: RolUsuario | str, nombre: str, ajustes: Settings, ahora: datetime | None = None
) -> TokenEmitido:
    """Token con `iss`, `sub`, `rol`, `nombre`, `iat`, `exp` (= `iat` + `JWT_TTL_MIN`) y `jti` (UUID v4)."""
    secreto = clave(ajustes)
    iat = int((ahora or datetime.now(UTC)).timestamp())
    exp = iat + ajustes.jwt_ttl_min * 60
    jti = str(uuid.uuid4())
    datos: dict[str, Any] = {
        "iss": EMISOR,
        "sub": str(usuario_id),
        "rol": str(RolUsuario(rol)),
        "nombre": nombre,
        "iat": iat,
        "exp": exp,
        "jti": jti,
    }
    token = jwt.encode(datos, secreto, algorithm=ALGORITMO)
    return TokenEmitido(token=token, expira_en=datetime.fromtimestamp(exp, UTC), jti=jti)


def decodificar(token: str, ajustes: Settings) -> Claims:
    """Claims de un token válido. El vencimiento solo se informa si la firma es correcta."""
    secreto = clave(ajustes)
    try:
        datos = jwt.decode(
            token,
            secreto,
            algorithms=[ALGORITMO],
            issuer=EMISOR,
            leeway=0,
            options={"require": list(CLAIMS)},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpirado("token vencido") from None
    except jwt.InvalidTokenError as exc:
        raise TokenInvalido(type(exc).__name__) from None
    try:
        return Claims(
            sub=uuid.UUID(str(datos["sub"])),
            rol=RolUsuario(datos["rol"]),
            nombre=_texto(datos["nombre"]),
            iat=_entero(datos["iat"]),
            exp=_entero(datos["exp"]),
            jti=_texto(datos["jti"]),
        )
    except (ValueError, TypeError) as exc:
        raise TokenInvalido(f"claims no válidos: {type(exc).__name__}") from None


def _texto(valor: Any) -> str:
    if not isinstance(valor, str) or not valor:
        raise ValueError("se esperaba un texto no vacío")
    return valor


def _entero(valor: Any) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise TypeError("se esperaba un número")
    return int(valor)
