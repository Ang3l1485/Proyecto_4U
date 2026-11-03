"""Inicio de sesión (ARCHITECTURE §4.4, §5.3 `POST /v1/auth/login`).

Pasos, iguales para todos los intentos para que la respuesta y el tiempo no revelen qué correos existen:
1. Reserva un puesto en la cola del hash (`ColaHash`): si ya hay `LOGIN_HASH_CONCURRENTES` + `LOGIN_HASH_COLA_MAX`
   intentos dentro, `Saturado` sin tocar la base.
2. Busca el usuario por correo normalizado (una transacción corta).
3. Verifica **una** contraseña con argon2id fuera de la base y en un hilo, como mucho `LOGIN_HASH_CONCURRENTES` a la
   vez: la del usuario o, si el correo no existe, `hash.hash_ficticio()`. Si no le toca el turno en
   `LOGIN_HASH_ESPERA_MAX_S`, `Saturado`.
4. En otra transacción, anota el intento en `auditoria` (`usuario.login`) y, si entró, fija `ultimo_acceso_en`.
5. Si falló (correo desconocido, contraseña incorrecta o usuario inactivo), `CredencialesInvalidas`; si no, firma el
   token (§5.2).

Un intento rechazado por `Saturado` no comprobó ninguna contraseña: no se anota en `auditoria` (solo el evento `login`
con `resultado = rechazado`), para que una avalancha no traslade la carga a la base. Nunca registra ni guarda la
contraseña ni el identificador escrito.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import anyio
import anyio.to_thread
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db import sesion
from app.db.modelos import Usuario
from app.dominio.enumerados import RolUsuario
from app.dominio.validaciones import normalizar_correo
from app.logs import obtener_logger, registrar
from app.seguridad import hash as hash_password
from app.seguridad import tokens
from app.servicios import auditoria

log = obtener_logger(__name__)

ACCION_LOGIN = "usuario.login"
#: Motivos de un login fallido (solo para el log y `auditoria.detalle.motivo`, §5.7).
CORREO_DESCONOCIDO = "correo_desconocido"
PASSWORD_INCORRECTA = "password_incorrecta"  # noqa: S105 (nombre del motivo, no un valor)
USUARIO_INACTIVO = "usuario_inactivo"
#: Motivos de un rechazo por saturación (`Saturado`; solo para el log).
COLA_LLENA = "cola_llena"
ESPERA_AGOTADA = "espera_agotada"


class CredencialesInvalidas(Exception):
    """Login fallido. `motivo` es solo para el log y la auditoría: la respuesta es la misma en los tres casos."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class Saturado(Exception):
    """La cola del hash está llena o no llegó el turno a tiempo: `503 SERVICIO_OCUPADO` (§5.3)."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class ColaHash:
    """Acota las verificaciones argon2id de `api` (§4.4, §5.10).

    `concurrentes` a la vez (cada una usa 64 MiB); como mucho `cola_max` más esperando, y cada una espera su turno como
    mucho `espera_max_s`. Así un cliente que insiste no acumula trabajo para peticiones que API Gateway ya cortó a los
    30 s. El `CapacityLimiter` de anyio se crea en el primer uso, dentro del bucle de eventos que lo va a usar.
    """

    def __init__(self, concurrentes: int, cola_max: int, espera_max_s: float) -> None:
        self.concurrentes = max(1, concurrentes)
        self.cola_max = max(0, cola_max)
        self.espera_max_s = espera_max_s
        self.dentro = 0  # reservados: verificando o esperando turno
        self._limitador: anyio.CapacityLimiter | None = None

    @classmethod
    def desde(cls, ajustes: Settings) -> ColaHash:
        return cls(ajustes.login_hash_concurrentes, ajustes.login_hash_cola_max, ajustes.login_hash_espera_max_s)

    def reservar(self) -> None:
        """Ocupa un puesto o lanza `Saturado(cola_llena)`. Cada `reservar` va seguido de un `verificar` o `liberar`."""
        if self.dentro >= self.concurrentes + self.cola_max:
            raise Saturado(COLA_LLENA)
        self.dentro += 1

    def liberar(self) -> None:
        self.dentro -= 1

    async def verificar(self, hash_guardado: str, password: str) -> bool:
        """`hash.verificar` en un hilo cuando haya turno (libera el puesto reservado al terminar)."""
        try:
            if self._limitador is None:
                self._limitador = anyio.CapacityLimiter(self.concurrentes)
            try:
                with anyio.fail_after(self.espera_max_s):
                    await self._limitador.acquire()
            except TimeoutError:
                raise Saturado(ESPERA_AGOTADA) from None
            try:
                return await anyio.to_thread.run_sync(hash_password.verificar, hash_guardado, password)
            finally:
                self._limitador.release()
        finally:
            self.liberar()


@dataclass(frozen=True)
class SesionIniciada:
    token: tokens.TokenEmitido
    usuario_id: uuid.UUID
    nombre: str
    correo: str
    rol: RolUsuario


async def iniciar_sesion(
    motor: AsyncEngine, ajustes: Settings, identificador: str, password: str, *, cola: ColaHash | None = None
) -> SesionIniciada:
    tokens.clave(ajustes)  # sin JWT_SECRET no se toca la base ni se anota nada (ClaveNoConfigurada)
    cola = cola or ColaHash.desde(ajustes)
    try:
        cola.reservar()
    except Saturado as exc:
        registrar(log, "login", logging.WARNING, resultado="rechazado", motivo=exc.motivo, usuario_id=None)
        raise
    correo = normalizar_correo(identificador)
    try:
        async with sesion.transaccion(motor) as conexion:
            fila = (
                await conexion.execute(
                    select(
                        Usuario.id, Usuario.nombre, Usuario.correo, Usuario.rol, Usuario.activo, Usuario.hash_password
                    ).where(Usuario.correo == correo)
                )
            ).first()
    except BaseException:
        cola.liberar()
        raise

    hash_guardado = fila.hash_password if fila is not None else hash_password.hash_ficticio()
    try:
        correcta = await cola.verificar(hash_guardado, password)
    except Saturado as exc:
        usuario_id = str(fila.id) if fila is not None else None
        registrar(log, "login", logging.WARNING, resultado="rechazado", motivo=exc.motivo, usuario_id=usuario_id)
        raise

    if fila is None:
        motivo = CORREO_DESCONOCIDO
    elif not correcta:
        motivo = PASSWORD_INCORRECTA
    elif not fila.activo:
        motivo = USUARIO_INACTIVO
    else:
        motivo = None

    async with sesion.transaccion(motor) as conexion:
        if motivo is None:
            await conexion.execute(update(Usuario).where(Usuario.id == fila.id).values(ultimo_acceso_en=func.now()))
        await auditoria.anotar(
            conexion,
            accion=ACCION_LOGIN,
            entidad="usuario",
            entidad_id=fila.id if fila is not None else None,
            actor_id=fila.id if motivo is None else None,
            detalle={"resultado": "exito"} if motivo is None else {"resultado": "fallo", "motivo": motivo},
        )

    usuario_id = str(fila.id) if fila is not None else None
    if motivo is not None:
        registrar(log, "login", logging.WARNING, resultado="fallo", motivo=motivo, usuario_id=usuario_id)
        raise CredencialesInvalidas(motivo)
    registrar(log, "login", resultado="exito", motivo=None, usuario_id=usuario_id)
    token = tokens.emitir(usuario_id=fila.id, rol=fila.rol, nombre=fila.nombre, ajustes=ajustes)
    return SesionIniciada(token=token, usuario_id=fila.id, nombre=fila.nombre, correo=fila.correo, rol=fila.rol)
