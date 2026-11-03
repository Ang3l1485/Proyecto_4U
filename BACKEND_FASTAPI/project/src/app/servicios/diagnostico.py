"""Diagnóstico de búsqueda (ARCHITECTURE §4.8, §5.5), BE-2.4: los vecinos del índice para **una** foto.

`vecinos_de_foto(motor, ajustes, foto, *, k, request_id=None, vectorizar=None)` → `ResultadoVecinos`:
1. Vectoriza la foto con `POST /v1/embed` y prioridad `baja` (no compite con las localizaciones), con un tope total
   de `TOPE_EMBEDDING_S` (los plazos de httpx son por fase, §4.6).
2. Compara la `version_vector` devuelta con `EMBEDDING_VERSION_VECTOR`: si no coincide, `VersionVectorDistinta`
   (no se busca con un vector incomparable).
3. En una transacción corta, `db.consultas.buscar_vecinos` con `k` y `LOC_EF_SEARCH` (el de `/v1/localize`).

La foto no se guarda en ningún sitio ni se registra (ADR-BE-06) y no se escribe nada en la base. Excepciones (las
traduce el router, §5.5): `EmbeddingNoDisponible`, `ImagenRechazada` y `RespuestaNoValida` de
`app.clientes.embedding`, `VersionVectorDistinta`, y `BaseNoDisponible` (de `sesion.transaccion`).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import anyio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clientes import embedding
from app.config import Settings
from app.db import consultas, sesion

#: Tope total de la llamada a embeddings (s). Por debajo de los 30 s de API Gateway; los plazos de httpx
#: (`EMBEDDING_TIMEOUT_S`) son por fase y una respuesta a trozos podría tardar más.
TOPE_EMBEDDING_S = 20.0

Vectorizar = Callable[[Sequence[bytes]], Awaitable[embedding.Vectores]]


class VersionVectorDistinta(Exception):
    def __init__(self, esperada: str, recibida: str) -> None:
        self.esperada = esperada
        self.recibida = recibida
        super().__init__(f"version_vector {recibida!r}, se esperaba {esperada!r}")


@dataclass(frozen=True)
class ResultadoVecinos:
    version_vector: str
    k: int
    vecinos: list[consultas.Vecino]
    embedding_ms: int
    busqueda_ms: int


def _ms(desde: float) -> int:
    return int((time.perf_counter() - desde) * 1000)


async def vecinos_de_foto(
    motor: AsyncEngine,
    ajustes: Settings,
    foto: bytes,
    *,
    k: int,
    request_id: str | None = None,
    vectorizar: Vectorizar | None = None,
) -> ResultadoVecinos:
    """Lo del docstring del módulo. `vectorizar` sustituye a `embedding.vectorizar` en las pruebas."""

    async def por_defecto(imagenes: Sequence[bytes]) -> embedding.Vectores:
        return await embedding.vectorizar(ajustes, imagenes, prioridad="baja", request_id=request_id)

    llamar = vectorizar or por_defecto
    inicio = time.perf_counter()
    try:
        with anyio.fail_after(TOPE_EMBEDDING_S):
            vectores = await llamar([foto])
    except TimeoutError:
        raise embedding.EmbeddingNoDisponible(f"sin respuesta en {TOPE_EMBEDDING_S:g} s (tope total)") from None
    embedding_ms = _ms(inicio)
    if vectores.version_vector != ajustes.embedding_version_vector:
        raise VersionVectorDistinta(ajustes.embedding_version_vector, vectores.version_vector)

    inicio = time.perf_counter()
    async with sesion.transaccion(motor) as conexion:
        [vecinos] = await consultas.buscar_vecinos(
            conexion,
            vectores.vectores[:1],
            k=k,
            version_vector=ajustes.embedding_version_vector,
            ef_search=ajustes.loc_ef_search,
        )
    return ResultadoVecinos(
        version_vector=ajustes.embedding_version_vector,
        k=k,
        vecinos=vecinos,
        embedding_ms=embedding_ms,
        busqueda_ms=_ms(inicio),
    )
