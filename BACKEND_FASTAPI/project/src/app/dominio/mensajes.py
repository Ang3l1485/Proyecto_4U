"""Mensajes de la cola `ingesta` (ARCHITECTURE §5.8), sin red ni base.

`interpretar(cuerpo)` convierte el cuerpo de un mensaje de SQS en una de estas formas:

- `EventosS3(objetos)`: notificación de S3 (`Records`); un `ObjetoSubido(clave, etag, bytes)` por cada `Record`
  `ObjectCreated:*` (la clave ya decodificada con `unquote_plus`; el ETag sin comillas). Un mensaje puede traer varios.
- `Reprocesar(imagen_id)`: `{"tipo": "reprocesar_imagen", "version": 1, "imagen_id": …}` (lo envía `api`).
- `PruebaS3()`: el `s3:TestEvent` que S3 envía al configurar la notificación: se borra sin hacer nada.
- `NoReconocido(motivo)`: cualquier otra cosa; el `worker` lo registra y lo borra.

BE-4.1 añade la cola `purga`: `interpretar_purga(cuerpo)` → `PurgarVideo(video_id)`, `PurgarImagen(imagen_id,
video_id, s3_keys)` o `NoReconocido(motivo)`; y los cuerpos que envía `api`: `cuerpo_reprocesar`,
`cuerpo_purgar_video` y `cuerpo_purgar_imagen` (JSON compacto, §5.8).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote_plus

from app.dominio.recoleccion import clave_dataset, clave_miniatura

#: Versiones aceptadas de `reprocesar_imagen` (§5.8: la actual y la anterior durante un despliegue).
VERSIONES_REPROCESAR = frozenset({1})
TIPO_REPROCESAR = "reprocesar_imagen"


@dataclass(frozen=True)
class ObjetoSubido:
    clave: str
    etag: str | None
    bytes: int | None


@dataclass(frozen=True)
class EventosS3:
    objetos: tuple[ObjetoSubido, ...]
    ignorados: int = 0  # `Records` que no son `ObjectCreated:*` o no traen clave


@dataclass(frozen=True)
class Reprocesar:
    imagen_id: uuid.UUID


@dataclass(frozen=True)
class PruebaS3:
    pass


@dataclass(frozen=True)
class NoReconocido:
    motivo: str


Mensaje = EventosS3 | Reprocesar | PruebaS3 | NoReconocido


def _objeto(registro: Any) -> ObjetoSubido | None:
    if not isinstance(registro, dict) or not str(registro.get("eventName", "")).startswith("ObjectCreated:"):
        return None
    objeto = (registro.get("s3") or {}).get("object") if isinstance(registro.get("s3"), dict) else None
    if not isinstance(objeto, dict) or not isinstance(objeto.get("key"), str):
        return None
    etag = objeto.get("eTag")
    tamano = objeto.get("size")
    return ObjetoSubido(
        clave=unquote_plus(objeto["key"]),
        etag=etag.strip('"') if isinstance(etag, str) and etag.strip('"') else None,
        bytes=tamano if isinstance(tamano, int) and not isinstance(tamano, bool) and tamano >= 0 else None,
    )


def interpretar(cuerpo: str) -> Mensaje:
    try:
        datos = json.loads(cuerpo)
    except (ValueError, TypeError):
        return NoReconocido("cuerpo que no es JSON")
    if not isinstance(datos, dict):
        return NoReconocido("cuerpo que no es un objeto JSON")
    if "Records" in datos:
        registros = datos["Records"]
        if not isinstance(registros, list):
            return NoReconocido("Records no es una lista")
        objetos = [o for o in (_objeto(r) for r in registros) if o is not None]
        return EventosS3(objetos=tuple(objetos), ignorados=len(registros) - len(objetos))
    if datos.get("Event") == "s3:TestEvent":
        return PruebaS3()
    if "tipo" in datos:
        if datos["tipo"] != TIPO_REPROCESAR:
            return NoReconocido(f"tipo desconocido: {str(datos['tipo'])[:60]}")
        version = datos.get("version")
        if type(version) is not int or version not in VERSIONES_REPROCESAR:
            return NoReconocido(f"versión no admitida de {TIPO_REPROCESAR}: {str(datos.get('version'))[:20]}")
        try:
            imagen_id = uuid.UUID(str(datos.get("imagen_id")))
        except ValueError:
            return NoReconocido(f"{TIPO_REPROCESAR} sin imagen_id válido")
        return Reprocesar(imagen_id=imagen_id)
    return NoReconocido("ni Records ni tipo")


# --- Cola `purga` y cuerpos que envía `api` (BE-4.1) --------------------------------------------------------------
TIPO_PURGAR_VIDEO = "purgar_video"
TIPO_PURGAR_IMAGEN = "purgar_imagen"
#: Versiones aceptadas de los mensajes de `purga` (§5.8).
VERSIONES_PURGA = frozenset({1})


@dataclass(frozen=True)
class PurgarVideo:
    video_id: uuid.UUID


@dataclass(frozen=True)
class PurgarImagen:
    imagen_id: uuid.UUID
    video_id: uuid.UUID
    s3_keys: tuple[str, ...]


MensajePurga = PurgarVideo | PurgarImagen | NoReconocido


def _uuid(valor: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(valor)) if isinstance(valor, str) else None
    except ValueError:
        return None


def interpretar_purga(cuerpo: str) -> MensajePurga:
    """Un mensaje de `purga`. `purgar_imagen` solo admite en `s3_keys` las dos claves de esa imagen (el original y la
    miniatura, infra §5.5): así un mensaje nunca puede borrar otra cosa del bucket."""
    try:
        datos = json.loads(cuerpo)
    except (ValueError, TypeError):
        return NoReconocido("cuerpo que no es JSON")
    if not isinstance(datos, dict):
        return NoReconocido("cuerpo que no es un objeto JSON")
    tipo = datos.get("tipo")
    if tipo not in (TIPO_PURGAR_VIDEO, TIPO_PURGAR_IMAGEN):
        return NoReconocido(f"tipo desconocido: {str(tipo)[:60]}")
    version = datos.get("version")
    if type(version) is not int or version not in VERSIONES_PURGA:
        return NoReconocido(f"versión no admitida de {tipo}: {str(version)[:20]}")
    video_id = _uuid(datos.get("video_id"))
    if video_id is None:
        return NoReconocido(f"{tipo} sin video_id válido")
    if tipo == TIPO_PURGAR_VIDEO:
        return PurgarVideo(video_id=video_id)
    imagen_id = _uuid(datos.get("imagen_id"))
    if imagen_id is None:
        return NoReconocido(f"{tipo} sin imagen_id válido")
    claves = datos.get("s3_keys")
    permitidas = {clave_dataset(video_id, imagen_id), clave_miniatura(video_id, imagen_id)}
    if not isinstance(claves, list) or not claves or any(c not in permitidas for c in claves):
        return NoReconocido(f"{tipo} con s3_keys que no son de la imagen")
    return PurgarImagen(imagen_id=imagen_id, video_id=video_id, s3_keys=tuple(dict.fromkeys(claves)))


def _sello(ahora: datetime | None) -> str:
    return (ahora or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(datos: dict[str, Any]) -> str:
    return json.dumps(datos, separators=(",", ":"), ensure_ascii=False)


def cuerpo_reprocesar(imagen_id: uuid.UUID, solicitado_por: uuid.UUID | None, ahora: datetime | None = None) -> str:
    return _json(
        {
            "tipo": TIPO_REPROCESAR,
            "version": 1,
            "imagen_id": str(imagen_id),
            "solicitado_por": str(solicitado_por) if solicitado_por else None,
            "solicitado_en": _sello(ahora),
        }
    )


def cuerpo_purgar_video(video_id: uuid.UUID, solicitado_por: uuid.UUID | None, ahora: datetime | None = None) -> str:
    return _json(
        {
            "tipo": TIPO_PURGAR_VIDEO,
            "version": 1,
            "video_id": str(video_id),
            "solicitado_por": str(solicitado_por) if solicitado_por else None,
            "solicitado_en": _sello(ahora),
        }
    )


def cuerpo_purgar_imagen(
    imagen_id: uuid.UUID, video_id: uuid.UUID, solicitado_por: uuid.UUID | None, ahora: datetime | None = None
) -> str:
    return _json(
        {
            "tipo": TIPO_PURGAR_IMAGEN,
            "version": 1,
            "imagen_id": str(imagen_id),
            "video_id": str(video_id),
            "s3_keys": [clave_dataset(video_id, imagen_id), clave_miniatura(video_id, imagen_id)],
            "solicitado_por": str(solicitado_por) if solicitado_por else None,
            "solicitado_en": _sello(ahora),
        }
    )
