"""Conexión a PostgreSQL con SQLAlchemy asíncrono sobre asyncpg (ARCHITECTURE §4.3, ADR-BE-01).

Las variables `DB_*` las inyecta la infraestructura (infra §5.4): `DB_PASSWORD` llega del secreto `db` y
`DB_SSLMODE = require` en AWS (RDS exige TLS). Cada proceso crea un solo motor: `api` con `DB_POOL_API` +
`DB_POOL_API_DESBORDE` conexiones, `worker` con `DB_POOL_WORKER` y la CLI (`migrate`) con una sola, sin pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings

#: Valores de `DB_SSLMODE` que entiende asyncpg (los mismos de libpq).
MODOS_SSL = frozenset({"disable", "allow", "prefer", "require", "verify-ca", "verify-full"})


class ConfiguracionIncompleta(Exception):
    """Faltan variables `DB_*` o alguna tiene un valor no válido."""

    def __init__(self, faltan: list[str], mensaje: str | None = None, invalidas: list[str] | None = None) -> None:
        self.faltan = faltan
        self.invalidas = invalidas or []
        super().__init__(mensaje or f"faltan variables: {', '.join(faltan)}")


class BaseNoDisponible(Exception):
    """No se pudo abrir la conexión con la base (red, DNS, TLS, credenciales, permiso, base inexistente o tiempo
    agotado), o se perdió después."""


def faltan_variables(ajustes: Settings) -> list[str]:
    """Variables `DB_*` obligatorias que no están definidas (vacío = configuración completa)."""
    valores = {
        "DB_HOST": ajustes.db_host,
        "DB_NAME": ajustes.db_name,
        "DB_USER": ajustes.db_user,
        "DB_PASSWORD": ajustes.db_password.get_secret_value() if ajustes.db_password else None,
    }
    return [nombre for nombre, valor in valores.items() if not (valor and str(valor).strip())]


def url_conexion(ajustes: Settings) -> URL:
    """URL de SQLAlchemy (`URL.create` escapa la contraseña; su `repr` la oculta)."""
    faltan = faltan_variables(ajustes)
    if faltan:
        raise ConfiguracionIncompleta(faltan)
    assert ajustes.db_password is not None  # noqa: S101 (comprobado arriba)
    return URL.create(
        "postgresql+asyncpg",
        username=ajustes.db_user,
        password=ajustes.db_password.get_secret_value(),
        host=ajustes.db_host,
        port=ajustes.db_port,
        database=ajustes.db_name,
    )


def argumentos_conexion(ajustes: Settings, proceso: str) -> dict[str, Any]:
    """Argumentos de `asyncpg.connect`: TLS según `DB_SSLMODE`, tiempo de conexión y nombre en `pg_stat_activity`."""
    modo = ajustes.db_sslmode.strip().lower()
    if modo not in MODOS_SSL:
        raise ConfiguracionIncompleta([], f"DB_SSLMODE no válido: {ajustes.db_sslmode!r}", invalidas=["DB_SSLMODE"])
    return {
        "ssl": modo,
        "timeout": ajustes.db_connect_timeout_s,
        "server_settings": {"application_name": f"campus-locator-{proceso}"},
    }


def crear_motor(ajustes: Settings, proceso: str, *, pool: int | None = None, desborde: int = 0) -> AsyncEngine:
    """Motor asíncrono. `pool=None` = sin pool (una conexión por uso; la CLI). No se conecta hasta usarlo.

    `hide_parameters`: los errores de SQLAlchemy no llevan los valores de la sentencia, que podrían ser un hash de
    contraseña o un correo, y acabarían en la traza del log (§4.1).
    """
    opciones: dict[str, Any] = {"connect_args": argumentos_conexion(ajustes, proceso), "hide_parameters": True}
    if pool is None:
        opciones["poolclass"] = NullPool
    else:
        opciones.update(pool_size=pool, max_overflow=desborde, pool_pre_ping=True)
    return create_async_engine(url_conexion(ajustes), **opciones)


# --- Fallos de conexión -------------------------------------------------------------------------------------------
#: Un `OSError` de estos es de archivos (p. ej. falta `migrations/`), no de red.
_OSERROR_DE_ARCHIVOS = (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError, PermissionError)


def _cadena(exc: BaseException) -> Iterator[BaseException]:
    """La excepción y sus causas explícitas (`orig` de SQLAlchemy y `raise … from`); no sigue `__context__`."""
    actual: Any = exc
    vistas: set[int] = set()
    while isinstance(actual, BaseException) and id(actual) not in vistas:
        vistas.add(id(actual))
        yield actual
        actual = getattr(actual, "orig", None) or actual.__cause__


def es_fallo_de_conexion(exc: BaseException) -> bool:
    """¿El error viene de no poder hablar con la base (y no de una sentencia que la base rechazó)?

    Cualquier fallo al **abrir** la conexión llega como `BaseNoDisponible` (`conectar`). Después, solo cuentan los de
    red y del protocolo: `OSError` que no es de archivos (rechazo, DNS, TLS…), tiempo agotado, clase 08 de PostgreSQL,
    servidor apagándose y conexiones que SQLAlchemy da por perdidas.
    """
    import asyncpg

    del_servidor = (
        asyncpg.exceptions.PostgresConnectionError,  # clase 08
        asyncpg.exceptions.AdminShutdownError,  # 57P01
        asyncpg.exceptions.CannotConnectNowError,  # 57P03
    )
    for causa in _cadena(exc):
        if isinstance(causa, (BaseNoDisponible, TimeoutError, *del_servidor)):
            return True
        if isinstance(causa, OSError) and not isinstance(causa, _OSERROR_DE_ARCHIVOS):
            return True
        if isinstance(causa, sa_exc.DBAPIError) and causa.connection_invalidated:
            return True
    return False


def es_fallo_de_base(exc: BaseException) -> bool:
    """`es_fallo_de_conexion`, pero solo si la excepción es de la base o de la red: de SQLAlchemy, de asyncpg o un
    `OSError` suelto que no sea `TimeoutError` (BE-1.3, §4.4).

    Lo usa `transaccion`. El filtro evita tomar por «base no disponible» un error de otra dependencia cuya cadena de
    causas lleve un `OSError` o un `TimeoutError` (p. ej. un *timeout* de httpx al llamar a embeddings) y un
    `TimeoutError` suelto, que suele venir de un `asyncio.timeout` del propio código.
    """
    import asyncpg

    de_la_base = (sa_exc.SQLAlchemyError, asyncpg.exceptions.PostgresError, asyncpg.exceptions.InterfaceError)
    suelto_de_red = isinstance(exc, OSError) and not isinstance(exc, TimeoutError)
    return (isinstance(exc, (BaseNoDisponible, *de_la_base)) or suelto_de_red) and es_fallo_de_conexion(exc)


def _origen(exc: BaseException) -> BaseException:
    """La excepción original detrás de los envoltorios de SQLAlchemy (`orig`) y de `raise … from`."""
    actual, vistas = exc, {id(exc)}
    while True:
        siguiente = getattr(actual, "orig", None) or actual.__cause__
        if not isinstance(siguiente, Exception) or id(siguiente) in vistas:  # p. ej. CancelledError tras un timeout
            return actual
        vistas.add(id(siguiente))
        actual = siguiente


def describir(exc: BaseException) -> str:
    """Motivo corto y sin secretos (asyncpg y SQLAlchemy no incluyen la contraseña en sus mensajes)."""
    causa = _origen(exc)
    texto = str(causa).strip().splitlines()[0] if str(causa).strip() else ""
    return f"{type(causa).__name__}: {texto}"[:300] if texto else type(causa).__name__


@asynccontextmanager
async def conectar(motor: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Conexión del motor. Cualquier fallo al abrirla es `BaseNoDisponible`: red, DNS, TLS, credenciales, falta de
    permiso `CONNECT`, base inexistente, demasiadas conexiones o tiempo agotado."""
    conexion = motor.connect()
    try:
        await conexion.start()
    except Exception as exc:
        raise BaseNoDisponible(describir(exc)) from exc
    try:
        yield conexion
    finally:
        await conexion.close()


@asynccontextmanager
async def transaccion(motor: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Una unidad de trabajo (BE-1.3, §4.4): abre una conexión con `conectar`, empieza una transacción, la confirma al
    salir del bloque (o la deshace si sale con una excepción) y cierra la conexión.

    Un fallo de conexión en cualquier punto (al abrir, en una sentencia o al confirmar) sale como `BaseNoDisponible`,
    que la API responde con `503 BASE_NO_DISPONIBLE`; el resto de excepciones salen tal cual. La conexión solo se tiene
    mientras dura el bloque: lo lento que no use la base (un hash, una llamada a embeddings) va fuera.
    """
    async with conectar(motor) as conexion:
        try:
            async with conexion.begin():
                yield conexion
        except BaseNoDisponible:
            raise
        except Exception as exc:
            if es_fallo_de_base(exc):
                raise BaseNoDisponible(describir(exc)) from exc
            raise


async def comprobar_conexion(motor: AsyncEngine, timeout_s: float) -> None:
    """`SELECT 1` en menos de `timeout_s`. Lanza `BaseNoDisponible` con el motivo si no se puede."""
    try:
        async with asyncio.timeout(timeout_s):
            async with conectar(motor) as conexion:
                await conexion.execute(text("SELECT 1"))
    except BaseNoDisponible:
        raise
    except Exception as exc:
        raise BaseNoDisponible(describir(exc)) from exc
