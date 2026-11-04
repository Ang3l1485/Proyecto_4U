"""`multipart/form-data` en memoria (ARCHITECTURE §4.8), BE-2.4; lo reutiliza BE-3.2 (`/v1/localize`).

Las fotos de consulta no se guardan en ningún sitio (ADR-BE-06), tampoco en disco: el analizador de Starlette
(`request.form()`) pasa a un archivo temporal toda parte de más de 1 MB y además exigiría `python-multipart`. Por eso el
cuerpo se lee acotado en memoria (`app.api.cuerpo`) y se parte aquí, sin dependencias.

- `partes_multipart(content_type, cuerpo)` → `list[Parte]` en el orden en que llegan. `NoEsMultipart` si el
  `Content-Type` no es `multipart/form-data` (o falta); `MultipartInvalido(motivo)` si lo es pero el cuerpo está mal
  formado (sin `boundary`, sin el delimitador final, una parte sin `Content-Disposition: form-data; name=…`).
- `Parte(nombre, archivo, tipo, datos)`: `tipo` es el `Content-Type` de la parte en minúsculas y sin parámetros
  (`text/plain` si no trae, RFC 7578 §4.4); `archivo` el `filename` o `None`.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from email.utils import collapse_rfc2231_value

#: RFC 2046 §5.1.1: el `boundary` tiene de 1 a 70 caracteres.
BOUNDARY_MAX = 70
TIPO_POR_DEFECTO = "text/plain"


class NoEsMultipart(Exception):
    """El `Content-Type` no es `multipart/form-data` (o no viene)."""


class MultipartInvalido(Exception):
    """Cuerpo `multipart/form-data` mal formado. El motivo no lleva datos del cuerpo."""


@dataclass(frozen=True)
class Parte:
    nombre: str
    archivo: str | None
    tipo: str
    datos: bytes


def _cabecera(nombre: str, valor: str) -> Message:
    mensaje = Message()
    mensaje[nombre] = valor
    return mensaje


def boundary_de(content_type: str | None) -> str:
    """El `boundary` de un `Content-Type: multipart/form-data`. `NoEsMultipart` o `MultipartInvalido`."""
    if not content_type or not content_type.strip():
        raise NoEsMultipart("sin Content-Type")
    cabecera = _cabecera("Content-Type", content_type)
    if cabecera.get_content_type() != "multipart/form-data":
        raise NoEsMultipart(cabecera.get_content_type())
    boundary = cabecera.get_param("boundary")
    if not isinstance(boundary, str) or not 1 <= len(boundary) <= BOUNDARY_MAX:
        raise MultipartInvalido("sin boundary válido")
    return boundary


def _parte(bloque: bytes) -> Parte:
    if bloque.startswith(b"\r\n"):  # sin cabeceras
        crudas, datos = b"", bloque[2:]
    else:
        fin = bloque.find(b"\r\n\r\n")
        if fin < 0:
            raise MultipartInvalido("una parte sin el fin de sus cabeceras")
        crudas, datos = bloque[:fin], bloque[fin + 4 :]
    cabeceras: dict[str, str] = {}
    for linea in crudas.split(b"\r\n"):
        if not linea.strip():
            continue
        nombre, separador, valor = linea.partition(b":")
        if not separador:
            raise MultipartInvalido("una cabecera de parte sin «:»")
        cabeceras[nombre.decode("latin-1").strip().lower()] = valor.decode("utf-8", "replace").strip()
    disposicion = cabeceras.get("content-disposition")
    if disposicion is None:
        raise MultipartInvalido("una parte sin Content-Disposition")
    mensaje = _cabecera("Content-Disposition", disposicion)
    nombre = mensaje.get_param("name", header="content-disposition")
    if isinstance(nombre, tuple):  # `name*=utf-8''…` (RFC 2231)
        nombre = collapse_rfc2231_value(nombre)
    if mensaje.get_content_disposition() != "form-data" or not isinstance(nombre, str):
        raise MultipartInvalido("una parte sin Content-Disposition: form-data; name=…")
    archivo = mensaje.get_filename()
    tipo = cabeceras.get("content-type")
    tipo_normal = _cabecera("Content-Type", tipo).get_content_type() if tipo else TIPO_POR_DEFECTO
    return Parte(nombre=nombre, archivo=archivo, tipo=tipo_normal, datos=datos)


def partes_multipart(content_type: str | None, cuerpo: bytes) -> list[Parte]:
    """Las partes de un cuerpo `multipart/form-data` (RFC 7578 y RFC 2046 §5.1). Admite preámbulo y epílogo."""
    delimitador = b"--" + boundary_de(content_type).encode("latin-1")
    # El primer delimitador va al principio del cuerpo o tras un CRLF (lo de antes es preámbulo).
    if cuerpo.startswith(delimitador):
        posicion = 0
    else:
        posicion = cuerpo.find(b"\r\n" + delimitador)
        if posicion < 0:
            raise MultipartInvalido("sin el primer delimitador")
        posicion += 2
    separador = b"\r\n" + delimitador
    partes: list[Parte] = []
    while True:
        posicion += len(delimitador)
        if cuerpo[posicion : posicion + 2] == b"--":
            return partes  # delimitador final; lo que sigue es epílogo
        fin_linea = cuerpo.find(b"\r\n", posicion)
        if fin_linea < 0 or cuerpo[posicion:fin_linea].strip(b" \t"):
            raise MultipartInvalido("delimitador mal terminado")
        inicio = fin_linea + 2
        siguiente = cuerpo.find(separador, inicio)
        if siguiente < 0:
            raise MultipartInvalido("sin el delimitador final")
        partes.append(_parte(cuerpo[inicio:siguiente]))
        posicion = siguiente + 2
