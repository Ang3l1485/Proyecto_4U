"""Diagnóstico de búsqueda (ARCHITECTURE §4.8, §5.5): `POST /v1/admin/diagnostico/vecinos` (BE-2.4). Va en
`RUTAS_ADMIN` (exige `requiere_admin`, que corre antes que todo lo de aquí).

Orden de las respuestas: `401`/`403` (token) → `422 VALIDACION` (`k`) → `400` (cuerpo y foto) →
`503 EMBEDDING_NO_DISPONIBLE` o `400 FOTOS_INVALIDAS` (embeddings) → `503 BASE_NO_DISPONIBLE` (búsqueda) → `200`.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Query, Request

from app.api.cuerpo import CuerpoDemasiadoGrande, leer_cuerpo
from app.api.dependencias import obtener_ajustes, obtener_motor
from app.clientes import embedding
from app.config import Settings
from app.dominio.fotos import motivo_foto_no_valida
from app.dominio.multipart import MultipartInvalido, NoEsMultipart, partes_multipart
from app.dominio.recoleccion import real_legible
from app.errores import ErrorApi
from app.esquemas.diagnostico import (
    DECIMALES_SIMILITUD,
    K_MAX,
    K_MIN,
    K_POR_DEFECTO,
    VecinoDiagnostico,
    VecinosRespuesta,
)
from app.esquemas.errores import ErrorRespuesta
from app.logs import obtener_logger, registrar, request_id_actual
from app.servicios import diagnostico

log = obtener_logger(__name__)
router = APIRouter(prefix="/diagnostico", tags=["diagnóstico"])

#: Nombre de la parte con la foto (§5.5). Las partes con otro nombre se ignoran.
PARTE_FOTO = "foto"
#: Lo que el cuerpo multipart puede pesar además de la foto (delimitadores, cabeceras de las partes, otras partes).
MARGEN_MULTIPART = 65_536

_CUERPO_MULTIPART = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": [PARTE_FOTO],
                "properties": {PARTE_FOTO: {"type": "string", "format": "binary", "description": "image/jpeg"}},
            }
        }
    },
}


def _foto_invalida(motivo: str, indice: int = 0) -> ErrorApi:
    return ErrorApi(400, "FOTOS_INVALIDAS", detalle={"indice": indice, "motivo": motivo})


async def foto_de_la_peticion(request: Request, max_bytes: int) -> bytes:
    """Los bytes de la única parte `foto` válida (`app.dominio.fotos`), o el `ErrorApi` de §5.5."""
    try:
        cuerpo = await leer_cuerpo(request, max_bytes + MARGEN_MULTIPART)
    except CuerpoDemasiadoGrande as exc:
        raise _foto_invalida(f"la petición pasa de {exc.max_bytes} bytes (la foto, como mucho {max_bytes})") from None
    try:
        partes = partes_multipart(request.headers.get("content-type"), cuerpo)
    except NoEsMultipart:
        raise _foto_invalida("falta la parte foto (se espera multipart/form-data)") from None
    except MultipartInvalido:
        raise ErrorApi(400, "SOLICITUD_INVALIDA", "El cuerpo multipart/form-data está mal formado.") from None
    fotos = [parte for parte in partes if parte.nombre == PARTE_FOTO]
    if not fotos:
        raise _foto_invalida("falta la parte foto")
    if len(fotos) > 1:
        raise _foto_invalida("solo se admite una parte foto", indice=1)
    motivo = motivo_foto_no_valida(fotos[0].tipo, fotos[0].datos, max_bytes)
    if motivo is not None:
        raise _foto_invalida(motivo)
    return fotos[0].datos


@router.post(
    "/vecinos",
    response_model=VecinosRespuesta,
    summary="Vecinos del índice para una foto (sin umbral ni agrupación)",
    openapi_extra={"requestBody": _CUERPO_MULTIPART},
    responses={
        400: {
            "model": ErrorRespuesta,
            "description": "FOTOS_INVALIDAS (detalle.indice y .motivo) · SOLICITUD_INVALIDA",
        },
        422: {"model": ErrorRespuesta, "description": "VALIDACION (k)"},
        503: {"model": ErrorRespuesta, "description": "EMBEDDING_NO_DISPONIBLE · BASE_NO_DISPONIBLE"},
    },
)
async def vecinos(
    request: Request,
    k: int = Query(K_POR_DEFECTO, ge=K_MIN, le=K_MAX, description="Vecinos que se devuelven"),
    ajustes: Settings = Depends(obtener_ajustes),
) -> VecinosRespuesta:
    inicio = time.perf_counter()
    foto = await foto_de_la_peticion(request, ajustes.loc_max_bytes_foto)
    motor = obtener_motor(request)
    try:
        resultado = await diagnostico.vecinos_de_foto(motor, ajustes, foto, k=k, request_id=request_id_actual.get())
    except embedding.ImagenRechazada as exc:
        raise _foto_invalida(f"embeddings la rechazó ({exc.codigo})") from None
    except embedding.EmbeddingNoDisponible as exc:
        registrar(log, "embedding_no_disponible", logging.WARNING, motivo=str(exc))
        raise ErrorApi(503, "EMBEDDING_NO_DISPONIBLE") from None
    except embedding.RespuestaNoValida as exc:
        registrar(log, "embedding_no_disponible", logging.ERROR, motivo=f"respuesta no válida: {exc}")
        raise ErrorApi(503, "EMBEDDING_NO_DISPONIBLE") from None
    except diagnostico.VersionVectorDistinta as exc:
        registrar(log, "version_vector_distinta", logging.ERROR, esperada=exc.esperada, recibida=exc.recibida)
        raise ErrorApi(503, "EMBEDDING_NO_DISPONIBLE") from None
    salida = [
        VecinoDiagnostico(
            imagen_id=v.imagen_id,
            video_id=v.video_id,
            lat=v.lat,
            lng=v.lng,
            rumbo=real_legible(v.rumbo),
            lugar_id=v.lugar_id,
            similitud=round(v.similitud, DECIMALES_SIMILITUD),
        )
        for v in resultado.vecinos
    ]
    latencia_ms = int((time.perf_counter() - inicio) * 1000)
    registrar(
        log,
        "vecinos_consultados",
        k=k,
        devueltos=len(salida),
        similitud_max=salida[0].similitud if salida else None,
        bytes=len(foto),
        embedding_ms=resultado.embedding_ms,
        busqueda_ms=resultado.busqueda_ms,
        latencia_ms=latencia_ms,
    )
    return VecinosRespuesta(version_vector=resultado.version_vector, k=k, vecinos=salida, latencia_ms=latencia_ms)
