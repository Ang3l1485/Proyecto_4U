"""Casos de uso del proceso `migrate` (ARCHITECTURE §4.3): aplicar las migraciones, crear el admin inicial y
comparar la base con el esquema de §5.7.

`migrar` es idempotente (se ejecuta en cada despliegue, infra §5.9):
1. Toma un bloqueo consultivo de sesión (`pg_advisory_lock`): dos `migrate` a la vez (un despliegue y un validador)
   se ejecutan uno detrás de otro. Espera hasta `ESPERA_BLOQUEO_S`.
2. `alembic upgrade head` en una transacción (el DDL de PostgreSQL es transaccional: o se aplica todo o nada).
3. Si no hay **ninguna** fila con rol `admin` (activa o no), crea el admin inicial con `ADMIN_INICIAL_CORREO` y
   `ADMIN_INICIAL_PASSWORD` (infra §5.4). Si ya hay uno, no toca nada: desactivar al admin a propósito no lo revive.

`verificar` toma el mismo bloqueo en modo compartido: con un `migrar` en curso, espera a que termine en lugar de leer
un esquema a medio migrar y decir que difiere.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import app
from app.config import Settings
from app.db import esquema, sesion
from app.dominio.validaciones import normalizar_correo
from app.seguridad import hash as hash_password

#: Clave del bloqueo consultivo de `migrar` (un `bigint` cualquiera, fijo para todo el proyecto).
CLAVE_BLOQUEO = 7_242_031_220_260_001
ESPERA_BLOQUEO_S = 300
NOMBRE_ADMIN_INICIAL = "Administrador"


class AdminInicialSinConfigurar(Exception):
    """Hace falta crear el admin inicial y faltan `ADMIN_INICIAL_*`."""

    def __init__(self, faltan: list[str]) -> None:
        self.faltan = faltan
        super().__init__(f"faltan variables para crear el admin inicial: {', '.join(faltan)}")


class ConflictoAdminInicial(Exception):
    """El correo del admin inicial ya es de un usuario que no es admin."""


@dataclass(frozen=True)
class ResultadoMigracion:
    revision_anterior: str | None
    revision: str | None
    admin_inicial: str  # "creado" | "ya_habia_admin"
    usuario_id: str | None = None


# --- Alembic ------------------------------------------------------------------------------------------------------
def directorio_migraciones() -> Path:
    """`migrations/`: junto al paquete en la imagen (`/srv/migrations`) o en `project/` en el repositorio."""
    paquete = Path(app.__file__).resolve().parent
    for base in (paquete.parent, paquete.parent.parent):
        candidato = base / "migrations"
        if (candidato / "env.py").is_file():
            return candidato
    raise FileNotFoundError(f"no se encontró migrations/env.py junto a {paquete}")


def configuracion_alembic() -> Config:
    configuracion = Config()
    configuracion.set_main_option("script_location", str(directorio_migraciones()))
    configuracion.set_main_option("path_separator", "os")
    return configuracion


def revision_head() -> str:
    """Última revisión de las migraciones que trae la imagen."""
    head = ScriptDirectory.from_config(configuracion_alembic()).get_current_head()
    if head is None:
        raise RuntimeError("no hay migraciones en migrations/versions/")
    return head


def _aplicar(conexion_sync: Any, configuracion: Config) -> None:
    configuracion.attributes["connection"] = conexion_sync
    command.upgrade(configuracion, "head")


async def _terminar_transaccion(conexion: AsyncConnection) -> None:
    if conexion.in_transaction():
        await conexion.commit()


# --- Casos de uso -------------------------------------------------------------------------------------------------
async def migrar(motor: AsyncEngine, ajustes: Settings) -> ResultadoMigracion:
    """Aplica las migraciones pendientes y crea el admin inicial si no hay ningún admin."""
    configuracion = configuracion_alembic()
    async with sesion.conectar(motor) as conexion:
        async with conexion.begin():
            await conexion.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_BLOQUEO_S}s'"))
            await conexion.execute(text("SELECT pg_advisory_lock(:clave)"), {"clave": CLAVE_BLOQUEO})
        try:
            anterior = await esquema.leer_revision(conexion)
            await _terminar_transaccion(conexion)
            await conexion.run_sync(_aplicar, configuracion)
            await _terminar_transaccion(conexion)
            actual = await esquema.leer_revision(conexion)
            await _terminar_transaccion(conexion)
            async with conexion.begin():
                admin, usuario_id = await _admin_inicial(conexion, ajustes)
        finally:
            # Cerrar la conexión también suelta el bloqueo; esto solo lo hace explícito. Si la conexión se perdió, el
            # error que importa es el original.
            with contextlib.suppress(Exception):
                if conexion.in_transaction():
                    await conexion.rollback()
                await conexion.execute(text("SELECT pg_advisory_unlock(:clave)"), {"clave": CLAVE_BLOQUEO})
                await conexion.commit()
    return ResultadoMigracion(anterior, actual, admin, usuario_id)


async def _admin_inicial(conexion: AsyncConnection, ajustes: Settings) -> tuple[str, str | None]:
    hay_admin = (await conexion.execute(text("SELECT EXISTS (SELECT 1 FROM usuarios WHERE rol = 'admin')"))).scalar()
    if hay_admin:
        return "ya_habia_admin", None
    correo = normalizar_correo(ajustes.admin_inicial_correo or "")
    password = ajustes.admin_inicial_password.get_secret_value() if ajustes.admin_inicial_password else ""
    faltan = [
        nombre
        for nombre, valor in (("ADMIN_INICIAL_CORREO", correo), ("ADMIN_INICIAL_PASSWORD", password))
        if not valor
    ]
    if faltan:
        raise AdminInicialSinConfigurar(faltan)
    existente = (
        await conexion.execute(text("SELECT rol FROM usuarios WHERE correo = :correo"), {"correo": correo})
    ).scalar()
    if existente is not None:
        raise ConflictoAdminInicial(
            f"ADMIN_INICIAL_CORREO ya es de un usuario con rol `{existente}`; "
            "para hacerlo admin, usa crear-usuario --rol admin"
        )
    usuario_id = (
        await conexion.execute(
            text(
                "INSERT INTO usuarios (correo, nombre, rol, hash_password) "
                "VALUES (:correo, :nombre, 'admin', :hash) RETURNING id"
            ),
            {"correo": correo, "nombre": NOMBRE_ADMIN_INICIAL, "hash": hash_password.calcular(password)},
        )
    ).scalar_one()
    return "creado", str(usuario_id)


@dataclass(frozen=True)
class ResultadoVerificacion:
    diferencias: list[esquema.Diferencia]
    catalogo: esquema.Catalogo
    revision_esperada: str


async def verificar(motor: AsyncEngine) -> ResultadoVerificacion:
    """Compara la base con §5.7 (`esquema.ESPERADO`) en una transacción de solo lectura: no modifica nada.

    Antes de leer espera, como mucho `ESPERA_BLOQUEO_S`, a que termine un `migrar` en curso (bloqueo compartido).
    """
    head = revision_head()
    async with sesion.conectar(motor) as conexion:
        async with conexion.begin():
            await conexion.execute(text("SET TRANSACTION READ ONLY"))
            await conexion.execute(text(f"SET LOCAL lock_timeout = '{ESPERA_BLOQUEO_S}s'"))
            await conexion.execute(text("SELECT pg_advisory_xact_lock_shared(:clave)"), {"clave": CLAVE_BLOQUEO})
            catalogo = await esquema.leer_catalogo(conexion)
    return ResultadoVerificacion(esquema.comparar(esquema.ESPERADO, catalogo, revision=head), catalogo, head)
