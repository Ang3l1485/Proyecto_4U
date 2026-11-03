"""Dependencias comunes de los routers (ARCHITECTURE §4.4, §4.5).

- `obtener_ajustes(request)`: los `Settings` con que se creó la app.
- `obtener_motor(request)`: el motor de `api` (`app.state.motor`). Sin motor (faltan `DB_*` o `DB_SSLMODE` no válido)
  lanza `BaseNoDisponible`, que se responde `503 BASE_NO_DISPONIBLE`. Cada unidad de trabajo abre su transacción con
  `async with sesion.transaccion(motor) as conexion:` (§4.4).
- `obtener_cola_hash(request)`: la `ColaHash` de la app, que acota las verificaciones argon2id del login
  (`LOGIN_HASH_*`, §5.10).
- `obtener_almacen(request)` (BE-2.1): el `AlmacenS3` del bucket del dataset (`app.state.almacen`, creado al arrancar si
  hay `S3_BUCKET_DATASET`). Sin él, `500 ERROR_INTERNO` con el evento `configuracion_incompleta` (`sin_almacen`).
  `almacen_o_none(request)` lo devuelve o `None`, para los servicios que comprueban antes otra cosa (p. ej. que el video
  exista) y lanzan `AlmacenNoConfigurado` solo si de verdad necesitan S3.
"""

from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clientes.s3 import AlmacenS3
from app.clientes.sqs import Colas
from app.config import Settings
from app.db import sesion
from app.errores import ErrorApi
from app.logs import obtener_logger, registrar
from app.servicios.autenticacion import ColaHash

log = obtener_logger(__name__)


def obtener_ajustes(request: Request) -> Settings:
    return request.app.state.ajustes


def obtener_motor(request: Request) -> AsyncEngine:
    motor = getattr(request.app.state, "motor", None)
    if motor is None:
        raise sesion.BaseNoDisponible(getattr(request.app.state, "motivo_sin_motor", "configuracion_incompleta"))
    return motor


def obtener_cola_hash(request: Request) -> ColaHash:
    cola = getattr(request.app.state, "cola_hash", None)
    if cola is None:
        cola = request.app.state.cola_hash = ColaHash.desde(request.app.state.ajustes)
    return cola


def almacen_o_none(request: Request) -> AlmacenS3 | None:
    return getattr(request.app.state, "almacen", None)


def sin_almacen(request: Request) -> ErrorApi:
    """`500 ERROR_INTERNO` por falta de cliente de S3, con su evento `configuracion_incompleta`."""
    registrar(
        log,
        "configuracion_incompleta",
        logging.ERROR,
        faltan=["S3_BUCKET_DATASET"] if not request.app.state.ajustes.s3_bucket_dataset else [],
        invalidas=[],
        motivo=getattr(request.app.state, "motivo_sin_almacen", "falta S3_BUCKET_DATASET"),
    )
    return ErrorApi(500, "ERROR_INTERNO")


def obtener_colas(request: Request) -> Colas:
    """BE-4.1: las colas de `app.state.colas` (`Colas(ingesta, purga)`; cada una `None` sin su variable)."""
    return getattr(request.app.state, "colas", None) or Colas()


def sin_cola(variable: str) -> ErrorApi:
    """BE-4.1: `500 ERROR_INTERNO` por falta de `SQS_URL_PURGA` o `SQS_URL_INGESTA` en `api`, con su evento."""
    registrar(
        log, "configuracion_incompleta", logging.ERROR, faltan=[variable], invalidas=[], motivo=f"falta {variable}"
    )
    return ErrorApi(500, "ERROR_INTERNO")


def obtener_almacen(request: Request) -> AlmacenS3:
    almacen = almacen_o_none(request)
    if almacen is None:
        raise sin_almacen(request)
    return almacen
