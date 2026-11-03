"""Reglas de validación y normalización sin infraestructura (ARCHITECTURE §4.1)."""

from __future__ import annotations

import re

#: Longitud de una contraseña (§5.3 `POST /v1/auth/login`, §5.9 `crear-usuario`). El máximo acota el trabajo del hash.
PASSWORD_MIN = 8
PASSWORD_MAX = 256
#: Longitud máxima de `identificador` en el login (un correo tiene como mucho 254; se deja margen).
IDENTIFICADOR_MAX = 320

_FORMA_CORREO = re.compile(r"[^@\s]+@[^@\s]+")


def normalizar_correo(correo: str) -> str:
    """Correo como se guarda y se busca (§4.4, §5.7 `usuarios.correo`): sin espacios alrededor y en minúsculas."""
    return correo.strip().lower()


def motivo_texto_no_admitido(texto: str) -> str | None:
    """`None` si `texto` se puede guardar en PostgreSQL y hashear; si no, el motivo (sin el valor).

    PostgreSQL rechaza el carácter NUL en `text` (error 22021, que acabaría en `500`), y un sustituto suelto no se
    puede codificar en UTF-8. Todo texto que venga de una petición y llegue a la base o al hash pasa por aquí (en los
    esquemas Pydantic, con un `field_validator`, para que responda `422 VALIDACION`).
    """
    if "\x00" in texto:
        return "No puede contener el carácter NUL."
    try:
        texto.encode("utf-8")
    except UnicodeEncodeError:
        return "Tiene caracteres que no se pueden codificar en UTF-8."
    return None


def tiene_forma_de_correo(correo: str) -> bool:
    """`algo@algo`, sin espacios ni una segunda `@` (no comprueba dominios: lo usa `crear-usuario`, §5.9)."""
    return bool(_FORMA_CORREO.fullmatch(correo)) and motivo_texto_no_admitido(correo) is None


def motivo_password_no_valida(password: str) -> str | None:
    """`None` si `password` vale para `crear-usuario` (§5.9); si no, el motivo, sin incluir el valor."""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return f"la contraseña debe tener entre {PASSWORD_MIN} y {PASSWORD_MAX} caracteres"
    if motivo_texto_no_admitido(password) is not None:
        return "la contraseña tiene el carácter NUL o caracteres que no se pueden codificar en UTF-8"
    return None
