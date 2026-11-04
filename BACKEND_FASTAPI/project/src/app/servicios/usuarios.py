"""Usuarios por línea de comandos (ARCHITECTURE §4.4, §5.9): `crear-usuario` y `desactivar-usuario`.

- Las dos operaciones toman, al empezar su transacción, el bloqueo consultivo `CLAVE_BLOQUEO_USUARIOS`
  (`pg_advisory_xact_lock`): dos a la vez se ejecutan en fila. Así la comprobación del último admin no tiene carreras
  y dos `crear-usuario` con el mismo correo nuevo dan uno `creado` y otro `actualizado`. El `INSERT` lleva además
  `ON CONFLICT (correo) DO NOTHING` por si el correo lo crea a la vez otro proceso (p. ej. el admin inicial de
  `migrar`).
- Ninguna deja la base sin un admin **activo**: quitar el rol o desactivar a un usuario con rol `admin` exige que
  quede otro admin activo (`UltimoAdmin`). Sin ninguna fila `admin`, además, `migrar` intentaría crear el admin
  inicial (§4.3) y, si su correo es el de ese usuario, fallaría en cada despliegue.
- No hay borrado: la fila se conserva por la auditoría (§5.7). Cada cambio deja una fila en `auditoria`
  (`usuario.crear`, `usuario.actualizar` o `usuario.desactivar`, sin actor porque viene de la CLI).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import sesion
from app.db.modelos import Usuario
from app.dominio.enumerados import RolUsuario
from app.dominio.validaciones import normalizar_correo
from app.seguridad import hash as hash_password
from app.servicios import auditoria

#: Bloqueo consultivo de los cambios de usuarios por CLI (distinto del de `migrar`, `7242031220260001`).
CLAVE_BLOQUEO_USUARIOS = 7_242_031_220_260_002


class UltimoAdmin(Exception):
    """El cambio dejaría la base sin ningún admin activo."""


class UsuarioNoEncontrado(Exception):
    """No hay ningún usuario con ese correo."""


@dataclass(frozen=True)
class UsuarioGuardado:
    resultado: str  # "creado" | "actualizado"
    usuario_id: uuid.UUID
    rol: RolUsuario
    rol_anterior: RolUsuario | None  # None si se creó
    reactivado: bool  # estaba desactivado y ahora está activo


@dataclass(frozen=True)
class UsuarioDesactivado:
    usuario_id: uuid.UUID
    ya_estaba_inactivo: bool


async def _bloquear(conexion: AsyncConnection) -> None:
    await conexion.execute(text("SELECT pg_advisory_xact_lock(:clave)"), {"clave": CLAVE_BLOQUEO_USUARIOS})


async def _exigir_otro_admin_activo(conexion: AsyncConnection, usuario_id: uuid.UUID, que: str) -> None:
    otros = (
        await conexion.execute(
            select(func.count())
            .select_from(Usuario)
            .where(Usuario.rol == RolUsuario.admin, Usuario.activo, Usuario.id != usuario_id)
        )
    ).scalar_one()
    if otros == 0:
        raise UltimoAdmin(f"no hay otro admin activo: crea o reactiva otro admin antes de {que}")


async def _buscar(conexion: AsyncConnection, correo: str) -> Any:
    consulta = select(Usuario.id, Usuario.rol, Usuario.activo).where(Usuario.correo == correo).with_for_update()
    return (await conexion.execute(consulta)).first()


async def crear_o_actualizar(
    motor: AsyncEngine, *, correo: str, nombre: str, rol: RolUsuario | None, password: str
) -> UsuarioGuardado:
    """Crea el usuario (con `rol`, o `user` si es `None`) o, si el correo ya existe, actualiza nombre, contraseña y,
    si se indica, rol, y lo deja activo."""
    correo = normalizar_correo(correo)
    nombre = nombre.strip()
    nuevo_hash = hash_password.calcular(password)
    async with sesion.transaccion(motor) as conexion:
        await _bloquear(conexion)
        fila = await _buscar(conexion, correo)
        if fila is None:
            rol_nuevo = rol or RolUsuario.user
            usuario_id = (
                await conexion.execute(
                    insert(Usuario)
                    .values(correo=correo, nombre=nombre, rol=rol_nuevo, hash_password=nuevo_hash)
                    .on_conflict_do_nothing(index_elements=["correo"])
                    .returning(Usuario.id)
                )
            ).scalar_one_or_none()
            if usuario_id is None:  # lo creó otro proceso entre la búsqueda y el INSERT
                fila = await _buscar(conexion, correo)
        if fila is None:
            guardado = UsuarioGuardado("creado", usuario_id, rol_nuevo, None, False)
            accion = "usuario.crear"
        else:
            rol_nuevo = rol or fila.rol
            if fila.rol == RolUsuario.admin and rol_nuevo != RolUsuario.admin:
                await _exigir_otro_admin_activo(conexion, fila.id, "quitarle el rol")
            await conexion.execute(
                update(Usuario)
                .where(Usuario.id == fila.id)
                .values(nombre=nombre, rol=rol_nuevo, hash_password=nuevo_hash, activo=True)
            )
            guardado = UsuarioGuardado("actualizado", fila.id, rol_nuevo, fila.rol, not fila.activo)
            accion = "usuario.actualizar"
        detalle = {"origen": "cli", "rol": str(guardado.rol), "reactivado": guardado.reactivado}
        if guardado.rol_anterior is not None:
            detalle["rol_anterior"] = str(guardado.rol_anterior)
        await auditoria.anotar(
            conexion, accion=accion, entidad="usuario", entidad_id=guardado.usuario_id, detalle=detalle
        )
    return guardado


async def desactivar(motor: AsyncEngine, *, correo: str) -> UsuarioDesactivado:
    """Deja `activo = false` (también si ya lo estaba). Sus tokens dejan de valer en la siguiente petición (§5.2)."""
    correo = normalizar_correo(correo)
    async with sesion.transaccion(motor) as conexion:
        await _bloquear(conexion)
        fila = await _buscar(conexion, correo)
        if fila is None:
            raise UsuarioNoEncontrado("no hay ningún usuario con ese correo")
        if fila.activo:
            if fila.rol == RolUsuario.admin:
                await _exigir_otro_admin_activo(conexion, fila.id, "desactivarlo")
            await conexion.execute(update(Usuario).where(Usuario.id == fila.id).values(activo=False))
        await auditoria.anotar(
            conexion,
            accion="usuario.desactivar",
            entidad="usuario",
            entidad_id=fila.id,
            detalle={"origen": "cli", "ya_estaba_inactivo": not fila.activo},
        )
    return UsuarioDesactivado(fila.id, not fila.activo)
