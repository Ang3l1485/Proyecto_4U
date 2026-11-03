"""Bucket del dataset en S3 (infra §5.5) con boto3, desde BE-2.1 (ARCHITECTURE §4.5).

`AlmacenS3(bucket, region)` es síncrono (boto3); los servicios asíncronos lo llaman en hilos con `firmar_puts` y
`consultar_varios`. Lo usan `api` (firmar `PUT` y `HEAD`, con el rol `tarea-api`), la CLI `limpiar-validacion`
(listar y borrar, con el rol `tarea-worker`; infra §5.8) y, desde BE-2.2, el `worker` (`descargar` el original y
`escribir` la miniatura, con el rol `tarea-worker`). BE-4.1: `firmar_get` (URLs de 1 h del panel, en `api`) y
`borrar_prefijo` en la purga del `worker`.

Reglas:
- Nunca se registra una URL prefirmada (§4.1). Los motivos de `FalloS3` llevan la clase y el código del error de AWS,
  no la URL.
- `consultar` (HEAD) toma 404 **y 403** como «no está»: sin `s3:ListBucket` (el rol de `api` no lo tiene), S3 responde
  403 a un objeto que no existe (ADR-BE-14).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import anyio.to_thread

from app.dominio.recoleccion import TIPO_JPEG

#: Códigos de error de un HEAD que significan «el objeto no está» (sin `s3:ListBucket` llega 403 en vez de 404).
_AUSENTE = {"404", "NoSuchKey", "NotFound", "403", "Forbidden", "AccessDenied"}
#: HEAD a la vez en `consultar_varios` (el pool de conexiones de botocore es de 10).
CONCURRENCIA_HEAD = 8


class FalloS3(Exception):
    """S3 no respondió o respondió un error que no es «no está». El mensaje no lleva URLs."""


@dataclass(frozen=True)
class UrlFirmada:
    url: str
    expira_en: datetime  # cota inferior: la firma se hace en el mismo segundo o después


@dataclass(frozen=True)
class ObjetoS3:
    bytes: int
    etag: str | None  # sin comillas, como en los eventos de S3 (§5.8)


@dataclass(frozen=True)
class ObjetoDescargado:
    datos: bytes
    etag: str | None  # sin comillas


class ObjetoDemasiadoGrande(Exception):
    """El objeto pasa del máximo pedido a `descargar` (no se lee). `bytes` = su tamaño."""

    def __init__(self, n_bytes: int) -> None:
        self.bytes = n_bytes
        super().__init__(f"{n_bytes} bytes")


def crear_cliente(region: str) -> Any:
    """Cliente de S3 con SigV4 y direccionamiento virtual: las URL quedan `https://<bucket>.s3.amazonaws.com/…`."""
    import boto3
    from botocore.config import Config

    configuracion = Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=3,
        read_timeout=5,
        max_pool_connections=CONCURRENCIA_HEAD + 2,
    )
    return boto3.session.Session().client("s3", region_name=region, config=configuracion)


def _motivo(exc: BaseException) -> str:
    respuesta = getattr(exc, "response", None) or {}
    codigo = respuesta.get("Error", {}).get("Code") if isinstance(respuesta, dict) else None
    return f"{type(exc).__name__}: {codigo}" if codigo else type(exc).__name__


class AlmacenS3:
    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        *,
        cliente: Any = None,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.bucket = bucket
        self.cliente = cliente if cliente is not None else crear_cliente(region)
        self.reloj = reloj

    def firmar_put(self, clave: str, ttl_s: int) -> UrlFirmada:
        """URL prefirmada `PUT` de `clave` con `Content-Type: image/jpeg` firmado (§5.4)."""
        inicio = self.reloj().astimezone(UTC).replace(microsecond=0)
        try:
            url = self.cliente.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": clave, "ContentType": TIPO_JPEG},
                ExpiresIn=ttl_s,
                HttpMethod="PUT",
            )
        except Exception as exc:  # p. ej. NoCredentialsError
            raise FalloS3(f"firmar: {_motivo(exc)}") from None
        return UrlFirmada(url=url, expira_en=inicio + timedelta(seconds=ttl_s))

    def firmar_get(self, clave: str, ttl_s: int) -> UrlFirmada:
        """BE-4.1: URL prefirmada `GET` de `clave` (sin encabezados firmados), para ver una foto o su miniatura (§5.5).
        No comprueba que el objeto exista: si no está, S3 responde 403/404 al descargarla."""
        inicio = self.reloj().astimezone(UTC).replace(microsecond=0)
        try:
            url = self.cliente.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": clave}, ExpiresIn=ttl_s, HttpMethod="GET"
            )
        except Exception as exc:
            raise FalloS3(f"firmar: {_motivo(exc)}") from None
        return UrlFirmada(url=url, expira_en=inicio + timedelta(seconds=ttl_s))

    def consultar(self, clave: str) -> ObjetoS3 | None:
        """HEAD de `clave`: el objeto, o `None` si no está (404 o 403). Otro error → `FalloS3`."""
        from botocore.exceptions import ClientError

        try:
            respuesta = self.cliente.head_object(Bucket=self.bucket, Key=clave)
        except ClientError as exc:
            codigo = str(exc.response.get("Error", {}).get("Code", ""))
            estado = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if codigo in _AUSENTE or estado in (403, 404):
                return None
            raise FalloS3(f"head: {_motivo(exc)}") from None
        except Exception as exc:
            raise FalloS3(f"head: {_motivo(exc)}") from None
        etag = respuesta.get("ETag")
        return ObjetoS3(bytes=int(respuesta.get("ContentLength", 0)), etag=etag.strip('"') if etag else None)

    def descargar(self, clave: str, max_bytes: int) -> ObjetoDescargado | None:
        """`GetObject` de `clave` (BE-2.2, rol `tarea-worker`): los bytes y el ETag, o `None` si no existe (404). Si el
        objeto pasa de `max_bytes` no lo lee: `ObjetoDemasiadoGrande(bytes)`. Otro error (también 403) → `FalloS3`.

        A diferencia de `consultar`, un 403 **no** es «no está»: el `worker` tiene `s3:ListBucket` (solo con
        `s3:prefix`) y un 403 aquí puede ser un permiso que falta; como `FalloS3`, el mensaje vuelve a la cola."""
        from botocore.exceptions import ClientError

        try:
            respuesta = self.cliente.get_object(Bucket=self.bucket, Key=clave)
        except ClientError as exc:
            codigo = str(exc.response.get("Error", {}).get("Code", ""))
            estado = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if codigo in {"NoSuchKey", "404", "NotFound"} or estado == 404:
                return None
            raise FalloS3(f"descargar: {_motivo(exc)}") from None
        except Exception as exc:
            raise FalloS3(f"descargar: {_motivo(exc)}") from None
        cuerpo = respuesta["Body"]
        try:
            tamano = int(respuesta.get("ContentLength", 0))
            if tamano > max_bytes:
                raise ObjetoDemasiadoGrande(tamano)
            datos = cuerpo.read(max_bytes + 1)
        except ObjetoDemasiadoGrande:
            raise
        except Exception as exc:
            raise FalloS3(f"descargar: {_motivo(exc)}") from None
        finally:
            cuerpo.close()
        if len(datos) > max_bytes:
            raise ObjetoDemasiadoGrande(len(datos))
        etag = respuesta.get("ETag")
        return ObjetoDescargado(datos=datos, etag=etag.strip('"') if etag else None)

    def escribir(self, clave: str, datos: bytes, content_type: str = TIPO_JPEG) -> None:
        """`PutObject` de `clave` con `ContentType` (BE-2.2: la miniatura en `thumbs/`). Error → `FalloS3`.

        Se llama `escribir` y no `subir` para no confundirse con `almacen_falso.subir` (el `PUT` de la app)."""
        try:
            self.cliente.put_object(Bucket=self.bucket, Key=clave, Body=datos, ContentType=content_type)
        except Exception as exc:
            raise FalloS3(f"escribir: {_motivo(exc)}") from None

    def contar_prefijo(self, prefijo: str) -> int:
        """Cuántos objetos hay bajo `prefijo` (solo lista; lo usa `limpiar-validacion --simular`). Error → `FalloS3`."""
        try:
            paginas = self.cliente.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefijo)
            return sum(len(pagina.get("Contents", [])) for pagina in paginas)
        except Exception as exc:
            raise FalloS3(f"listar {prefijo}: {_motivo(exc)}") from None

    def borrar_prefijo(self, prefijo: str) -> int:
        """Borra todos los objetos bajo `prefijo` (lista con `list_objects_v2` y borra de 1000 en 1000). Devuelve
        cuántos borró. Un error de listado o de borrado → `FalloS3`."""
        borrados = 0
        try:
            paginas = self.cliente.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefijo)
            for pagina in paginas:
                claves = [{"Key": objeto["Key"]} for objeto in pagina.get("Contents", [])]
                for inicio in range(0, len(claves), 1000):
                    respuesta = self.cliente.delete_objects(
                        Bucket=self.bucket, Delete={"Objects": claves[inicio : inicio + 1000], "Quiet": False}
                    )
                    errores = respuesta.get("Errors") or []
                    if errores:
                        raise FalloS3(f"borrar: {len(errores)} objetos con error ({errores[0].get('Code', '')})")
                    borrados += len(respuesta.get("Deleted") or [])
        except FalloS3:
            raise
        except Exception as exc:
            raise FalloS3(f"borrar {prefijo}: {_motivo(exc)}") from None
        return borrados


# --- Desde código asíncrono ---------------------------------------------------------------------------------------
async def firmar_puts(almacen: AlmacenS3, claves: Iterable[str], ttl_s: int) -> dict[str, UrlFirmada]:
    """Firma varias claves en un solo hilo (firmar no usa la red salvo para renovar credenciales)."""
    lista = list(claves)
    if not lista:
        return {}
    return await anyio.to_thread.run_sync(lambda: {clave: almacen.firmar_put(clave, ttl_s) for clave in lista})


async def firmar_gets(almacen: AlmacenS3, claves: Iterable[str], ttl_s: int) -> dict[str, UrlFirmada]:
    """BE-4.1: URLs `GET` de varias claves en un solo hilo (como `firmar_puts`)."""
    lista = list(dict.fromkeys(claves))
    if not lista:
        return {}
    return await anyio.to_thread.run_sync(lambda: {clave: almacen.firmar_get(clave, ttl_s) for clave in lista})


async def consultar_varios(
    almacen: AlmacenS3, claves: Iterable[str], concurrencia: int = CONCURRENCIA_HEAD
) -> dict[str, ObjetoS3 | FalloS3 | None]:
    """HEAD de varias claves, `concurrencia` a la vez en hilos. Por clave: el objeto, `None` (no está) o el
    `FalloS3` (no se pudo saber); nunca lanza por una clave."""
    resultados: dict[str, ObjetoS3 | FalloS3 | None] = {}
    limitador = anyio.CapacityLimiter(max(1, concurrencia))

    async def una(clave: str) -> None:
        try:
            resultados[clave] = await anyio.to_thread.run_sync(almacen.consultar, clave, limiter=limitador)
        except FalloS3 as exc:
            resultados[clave] = exc

    async with anyio.create_task_group() as grupo:
        for clave in dict.fromkeys(claves):
            grupo.start_soon(una, clave)
    return resultados
