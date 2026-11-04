"""Lectura acotada del cuerpo de una petición (ARCHITECTURE §4.8), BE-2.4; la reutiliza BE-3.2.

`leer_cuerpo(request, max_bytes)` lee el cuerpo en memoria y lanza `CuerpoDemasiadoGrande` en cuanto pasa de
`max_bytes` (por el `Content-Length` declarado o al leerlo), sin guardarlo en disco (ADR-BE-06). API Gateway ya corta a
10 MB (§5.1); esto evita tener en memoria más de lo que un endpoint admite.
"""

from __future__ import annotations

from fastapi import Request


class CuerpoDemasiadoGrande(Exception):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"el cuerpo pasa de {max_bytes} bytes")


async def leer_cuerpo(request: Request, max_bytes: int) -> bytes:
    declarado = (request.headers.get("content-length") or "").strip()
    if declarado.isdigit() and int(declarado) > max_bytes:
        raise CuerpoDemasiadoGrande(max_bytes)
    trozos: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > max_bytes:
            raise CuerpoDemasiadoGrande(max_bytes)
        trozos.append(trozo)
    return b"".join(trozos)
