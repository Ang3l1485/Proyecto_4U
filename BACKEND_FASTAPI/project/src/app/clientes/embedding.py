"""Cliente del servicio de embeddings (`SERVICE_EMBEDDING/docs/ARCHITECTURE.md` §5).

- `esta_listo(ajustes)` (BE-1.1): `GET /health/ready` para `GET /v1/health/ready` y, desde BE-2.2, para el `worker`
  antes de recibir mensajes.
- `vectorizar(ajustes, imagenes, prioridad=…)` (BE-2.2; lo reutilizan BE-2.4 con `baja` y BE-3.2 con `alta`):
  `POST /v1/embed` con las imágenes como partes `imagenes` (`image/jpeg`) y `X-Prioridad`. Devuelve `Vectores`
  (`version_vector`, `dim`, `vectores`, `tiempos_ms`) en el orden de las imágenes. Quien llama compara
  `version_vector` con `EMBEDDING_VERSION_VECTOR` (§5.10): este módulo no decide qué hacer si no coincide.

Errores de `vectorizar`:
- `EmbeddingNoDisponible(motivo)`: sin `EMBEDDING_URL`, sin conexión, sin respuesta en `EMBEDDING_TIMEOUT_S`, `503`
  (`NO_LISTO`, `SATURADO`) o cualquier `5xx`. Transitorio. Solo se reintenta una vez, y solo si la conexión fue
  **rechazada** (§5.10).
- `ImagenRechazada(indice, codigo)`: `400 IMAGEN_INVALIDA`, `413` o `415` con `detalle.indice` (embeddings §5.6): esa
  imagen no vale; las demás del lote sí.
- `RespuestaNoValida(motivo)`: otra respuesta (`4xx` sin índice, `200` sin la forma de §5.2): error de contrato.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx

from app.config import Settings

RUTA_PREPARADO = "/health/ready"
RUTA_EMBED = "/v1/embed"
PRIORIDADES = ("alta", "baja")


class EmbeddingNoDisponible(Exception):
    """Embeddings apagado, cargando, saturado, caído o lento (transitorio). El motivo no lleva datos de imagen."""


class ImagenRechazada(Exception):
    def __init__(self, indice: int, codigo: str) -> None:
        self.indice = indice
        self.codigo = codigo
        super().__init__(f"imagen {indice}: {codigo}")


class RespuestaNoValida(Exception):
    """Respuesta que no cumple el contrato de embeddings §5.2/§5.6."""


@dataclass(frozen=True)
class Vectores:
    version_vector: str
    dim: int
    vectores: list[list[float]]
    tiempos_ms: dict[str, int] = field(default_factory=dict)


async def esta_listo(ajustes: Settings, transporte: httpx.AsyncBaseTransport | None = None) -> bool:
    """`True` si `GET {EMBEDDING_URL}/health/ready` responde 200 dentro de `EMBEDDING_CONNECT_TIMEOUT_S`.

    Fuera de horario `embedding` está apagado y su nombre DNS no resuelve: eso es `False`, no un error.
    """
    if not ajustes.embedding_url:
        return False
    limite = httpx.Timeout(ajustes.embedding_connect_timeout_s)
    try:
        # trust_env=False: es un servicio interno de la VPC; no debe pasar por proxies del entorno.
        async with httpx.AsyncClient(timeout=limite, transport=transporte, trust_env=False) as cliente:
            respuesta = await cliente.get(f"{ajustes.embedding_url}{RUTA_PREPARADO}")
    except httpx.HTTPError:
        return False
    return respuesta.status_code == 200


def _rechazada(exc: BaseException) -> bool:
    """¿La causa (siguiendo `__cause__` y `__context__`) es una conexión rechazada?"""
    vistas: set[int] = set()
    actual: BaseException | None = exc
    while actual is not None and id(actual) not in vistas:
        if isinstance(actual, ConnectionRefusedError):
            return True
        vistas.add(id(actual))
        actual = actual.__cause__ or actual.__context__
    return False


def _codigo_y_indice(respuesta: httpx.Response) -> tuple[str | None, int | None]:
    try:
        error = respuesta.json().get("error") or {}
    except (ValueError, AttributeError):
        return None, None
    detalle = error.get("detalle") if isinstance(error, dict) else None
    indice = detalle.get("indice") if isinstance(detalle, dict) else None
    codigo = error.get("codigo") if isinstance(error, dict) else None
    return (str(codigo) if codigo else None), (indice if type(indice) is int else None)


def _leer(respuesta: httpx.Response, n: int) -> Vectores:
    try:
        cuerpo = respuesta.json()
        version = cuerpo["version_vector"]
        dim = cuerpo["dim"]
        vectores = cuerpo["vectores"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise RespuestaNoValida("200 sin version_vector, dim o vectores") from None
    if not isinstance(version, str) or type(dim) is not int or not isinstance(vectores, list) or len(vectores) != n:
        raise RespuestaNoValida(f"200 con {len(vectores) if isinstance(vectores, list) else '?'} vectores para {n}")
    for vector in vectores:
        if not isinstance(vector, list) or len(vector) != dim:
            raise RespuestaNoValida(f"un vector no tiene dim = {dim} componentes")
    tiempos = cuerpo.get("tiempos_ms") if isinstance(cuerpo.get("tiempos_ms"), dict) else {}
    return Vectores(version_vector=version, dim=dim, vectores=vectores, tiempos_ms=tiempos)


async def vectorizar(
    ajustes: Settings,
    imagenes: Sequence[bytes],
    *,
    prioridad: str = "baja",
    transporte: httpx.AsyncBaseTransport | None = None,
    request_id: str | None = None,
) -> Vectores:
    """`POST {EMBEDDING_URL}/v1/embed` con 1 a 8 JPEG (embeddings §5.2). Errores: los del docstring del módulo."""
    if prioridad not in PRIORIDADES:
        raise ValueError(f"prioridad {prioridad!r}")
    if not imagenes:
        raise ValueError("sin imágenes")
    if not ajustes.embedding_url:
        raise EmbeddingNoDisponible("sin EMBEDDING_URL")
    limite = httpx.Timeout(ajustes.embedding_timeout_s, connect=ajustes.embedding_connect_timeout_s)
    partes = [("imagenes", (f"{i}.jpg", datos, "image/jpeg")) for i, datos in enumerate(imagenes)]
    encabezados = {"X-Prioridad": prioridad} | ({"X-Request-Id": request_id} if request_id else {})
    url = f"{ajustes.embedding_url}{RUTA_EMBED}"
    async with httpx.AsyncClient(timeout=limite, transport=transporte, trust_env=False) as cliente:
        for intento in (1, 2):
            try:
                respuesta = await cliente.post(url, files=partes, headers=encabezados)
                break
            except httpx.TimeoutException:
                raise EmbeddingNoDisponible(f"sin respuesta en {ajustes.embedding_timeout_s:g} s") from None
            except httpx.HTTPError as exc:
                if intento == 1 and _rechazada(exc):
                    continue
                raise EmbeddingNoDisponible(f"sin conexión ({type(exc).__name__})") from None
    codigo, indice = _codigo_y_indice(respuesta)
    if respuesta.status_code == 200:
        return _leer(respuesta, len(imagenes))
    if respuesta.status_code >= 500:
        raise EmbeddingNoDisponible(f"{respuesta.status_code} {codigo or ''}".strip())
    if respuesta.status_code in (400, 413, 415) and indice is not None and 0 <= indice < len(imagenes):
        raise ImagenRechazada(indice, codigo or str(respuesta.status_code))
    raise RespuestaNoValida(f"{respuesta.status_code} {codigo or ''}".strip())
