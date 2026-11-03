"""Línea de comandos del backend: `python -m app.cli <comando>` (ARCHITECTURE §5.9).

Comandos que corren como tarea suelta con la definición `campus-locator-dev-migrate`:
- `migrar` (BE-1.2): migraciones Alembic y admin inicial (§4.3). Es el comando de la tarea `migrate` y el paso 2 de
  `backend.yml` (infra §5.9).
- `verificar-esquema` (BE-1.2): compara la base con §5.7 sin modificar nada.
- `crear-usuario` y `desactivar-usuario` (BE-1.3, §4.4): la contraseña de `crear-usuario` llega en
  `CREAR_USUARIO_PASSWORD` o se pide dos veces por la terminal; nunca como argumento.

Con la definición `campus-locator-dev-worker` (la que puede borrar en S3):
- `limpiar-validacion [--video ID …] [--simular]` (BE-2.1, §4.5): borra los videos `validacion-` con sus filas y sus
  objetos (con `--simular`, solo comprueba y cuenta).

Todo lo que escriben son líneas JSON (§5.10) con `proceso = migrate`; los resultados son eventos de log.
`limpiar-validacion` imprime además la línea `LIMPIEZA {"videos": n, "objetos": m}` (o, con `--simular`,
`SIMULACION {…}`) (§5.9).

Códigos de salida, comunes a todos los comandos de `app.cli` (§5.9):
- 0: hecho (`verificar-esquema`: la base coincide);
- 1: resultado negativo (`verificar-esquema`: difiere; `migrar`: falló una migración o el admin inicial;
  `desactivar-usuario`: no existe; los dos: dejaría sin ningún admin activo o falló; `limpiar-validacion`: algún
  `--video` no existe o no es de validación, o falló S3);
- 2: no se pudo trabajar con la base (no conecta, credenciales, TLS, tiempo agotado o se perdió la conexión; en
  `verificar-esquema`, también un error al leer el catálogo);
- 3: uso o configuración (argumentos, variables con un valor no válido, `DB_*` o `ADMIN_INICIAL_*` que faltan,
  contraseña de `crear-usuario` que falta o no vale, `S3_BUCKET_DATASET` que falta en `limpiar-validacion`).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, NoReturn, TextIO

from pydantic import ValidationError

from app import __version__
from app.config import Settings, get_settings
from app.db import sesion
from app.dominio import validaciones
from app.dominio.enumerados import RolUsuario
from app.logs import configurar_logs, obtener_logger, registrar
from app.servicios import limpieza, migracion, usuarios

PROCESO = "migrate"
SALIDA_OK, SALIDA_NEGATIVA, SALIDA_BASE, SALIDA_CONFIGURACION = 0, 1, 2, 3
VARIABLE_PASSWORD = "CREAR_USUARIO_PASSWORD"  # noqa: S105 (nombre de la variable, no un valor)

log = obtener_logger("app.cli")  # estable también con `python -m app.cli`


class _Parser(argparse.ArgumentParser):
    """argparse sale con 2 ante un error de uso; aquí el 2 es «base no disponible», así que se usa el 3."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(SALIDA_CONFIGURACION, f"{self.prog}: error: {message}\n")


def _correo(valor: str) -> str:
    correo = validaciones.normalizar_correo(valor)
    if not validaciones.tiene_forma_de_correo(correo):
        raise argparse.ArgumentTypeError("se esperaba un correo de la forma nombre@dominio")
    return correo


def _nombre(valor: str) -> str:
    nombre = valor.strip()
    if not nombre:
        raise argparse.ArgumentTypeError("el nombre no puede estar vacío")
    motivo = validaciones.motivo_texto_no_admitido(nombre)
    if motivo is not None:
        raise argparse.ArgumentTypeError(motivo)
    return nombre


def crear_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m app.cli", description="Comandos del backend (ARCHITECTURE §5.9).")
    comandos = parser.add_subparsers(dest="comando", required=True, metavar="comando", parser_class=_Parser)
    comandos.add_parser("migrar", help="Aplica las migraciones y crea el admin inicial si no hay ningún admin")
    comandos.add_parser("verificar-esquema", help="Compara la base con el esquema de §5.7 (no modifica nada)")
    crear = comandos.add_parser(
        "crear-usuario",
        help="Crea un usuario o, si el correo existe, actualiza nombre, rol y contraseña y lo reactiva",
        description=f"La contraseña llega en {VARIABLE_PASSWORD} o se pide dos veces por la terminal.",
    )
    crear.add_argument("--correo", required=True, type=_correo)
    crear.add_argument("--nombre", required=True, type=_nombre)
    crear.add_argument(
        "--rol",
        choices=[r.value for r in RolUsuario],
        default=None,
        help="Sin --rol: un usuario nuevo es `user` y uno existente conserva su rol",
    )
    desactivar = comandos.add_parser("desactivar-usuario", help="Desactiva un usuario (sus tokens dejan de valer)")
    desactivar.add_argument("--correo", required=True, type=_correo)
    limpiar = comandos.add_parser(
        "limpiar-validacion",
        help="Borra los videos `validacion-` con sus filas y sus objetos de S3 (datos de los validadores)",
        description="Sin --video, todos los videos cuyo nombre y ref_cliente empiezan por `validacion-`. Con --video, "
        "solo esos, y se niega (código 1) si alguno no existe o no lleva el prefijo. Con --simular, las mismas "
        "comprobaciones sin borrar nada.",
    )
    limpiar.add_argument("--video", dest="videos", action="extend", nargs="+", type=_uuid, default=None, metavar="ID")
    limpiar.add_argument(
        "--simular",
        action="store_true",
        help="No borra nada: comprueba, cuenta lo que borraría e imprime `SIMULACION {…}` (o se niega con 1)",
    )
    return parser


def _uuid(valor: str) -> uuid.UUID:
    try:
        return uuid.UUID(valor.strip())
    except ValueError:
        raise argparse.ArgumentTypeError("se esperaba un UUID") from None


def _motor(ajustes: Settings):
    """Motor sin pool para la CLI, o `None` si la configuración está incompleta (ya registrado)."""
    try:
        return sesion.crear_motor(ajustes, PROCESO)
    except sesion.ConfiguracionIncompleta as exc:
        registrar(
            log, "configuracion_incompleta", logging.ERROR, faltan=exc.faltan, invalidas=exc.invalidas, motivo=str(exc)
        )
        return None


def _base_no_disponible(exc: BaseException) -> int:
    registrar(log, "base_no_disponible", logging.ERROR, motivo=sesion.describir(exc))
    return SALIDA_BASE


def _fallo(comando: str, exc: BaseException) -> int:
    """Error al trabajar con la base: 2 si es de conexión; si no, `comando_fallido` y 1."""
    if sesion.es_fallo_de_conexion(exc):
        return _base_no_disponible(exc)
    registrar(log, "comando_fallido", logging.ERROR, comando=comando, motivo=sesion.describir(exc), exc_info=True)
    return SALIDA_NEGATIVA


async def comando_migrar(ajustes: Settings, argumentos: argparse.Namespace | None = None) -> int:
    motor = _motor(ajustes)
    if motor is None:
        return SALIDA_CONFIGURACION
    inicio = time.perf_counter()
    try:
        registrar(
            log,
            "migracion_iniciada",
            version=__version__,
            commit=ajustes.commit_corto,
            entorno=ajustes.app_env,
            revision_objetivo=migracion.revision_head(),
        )
        resultado = await migracion.migrar(motor, ajustes)
    except migracion.AdminInicialSinConfigurar as exc:
        registrar(log, "configuracion_incompleta", logging.ERROR, faltan=exc.faltan, invalidas=[], motivo=str(exc))
        return SALIDA_CONFIGURACION
    except Exception as exc:
        if sesion.es_fallo_de_conexion(exc):
            return _base_no_disponible(exc)
        registrar(log, "migracion_fallida", logging.ERROR, motivo=sesion.describir(exc), exc_info=True)
        return SALIDA_NEGATIVA
    finally:
        await motor.dispose()
    campos = {"usuario_id": resultado.usuario_id} if resultado.usuario_id else {}
    registrar(
        log,
        "migracion_terminada",
        revision_anterior=resultado.revision_anterior,
        revision=resultado.revision,
        aplicada=resultado.revision_anterior != resultado.revision,
        admin_inicial=resultado.admin_inicial,
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
        **campos,
    )
    return SALIDA_OK


async def comando_verificar_esquema(ajustes: Settings, argumentos: argparse.Namespace | None = None) -> int:
    motor = _motor(ajustes)
    if motor is None:
        return SALIDA_CONFIGURACION
    try:
        resultado = await migracion.verificar(motor)
    except Exception as exc:
        if sesion.es_fallo_de_conexion(exc):
            return _base_no_disponible(exc)
        registrar(log, "verificacion_fallida", logging.ERROR, motivo=sesion.describir(exc), exc_info=True)
        return SALIDA_BASE
    finally:
        await motor.dispose()
    for diferencia in resultado.diferencias:
        registrar(log, "esquema_diferencia", logging.WARNING, **diferencia.como_campos())
    coincide = not resultado.diferencias
    registrar(
        log,
        "esquema_verificado",
        logging.INFO if coincide else logging.WARNING,
        resultado="coincide" if coincide else "difiere",
        diferencias=len(resultado.diferencias),
        revision=resultado.catalogo.revision,
        revision_esperada=resultado.revision_esperada,
        servidor=resultado.catalogo.servidor,
        pgvector=resultado.catalogo.extensiones.get("vector"),
    )
    return SALIDA_OK if coincide else SALIDA_NEGATIVA


class _PasswordNoValida(Exception):
    def __init__(self, faltan: list[str], invalidas: list[str], motivo: str) -> None:
        self.faltan, self.invalidas, self.motivo = faltan, invalidas, motivo
        super().__init__(motivo)


def leer_password(entrada: TextIO | None = None, pedir: Callable[[str], str] = getpass.getpass) -> str:
    """`CREAR_USUARIO_PASSWORD` si está definida y no vacía; si no, y hay terminal, se pide dos veces.

    Lanza `_PasswordNoValida` si falta, si las dos no coinciden o si no cumple §5.9 (8–256 caracteres). El valor nunca
    se registra.
    """
    valor = os.environ.get(VARIABLE_PASSWORD, "")
    origen = VARIABLE_PASSWORD
    if not valor:
        entrada = entrada or sys.stdin
        if not (entrada is not None and entrada.isatty()):
            raise _PasswordNoValida(
                [VARIABLE_PASSWORD], [], f"falta {VARIABLE_PASSWORD} y no hay terminal para pedir la contraseña"
            )
        valor, origen = pedir("Contraseña: "), "terminal"
        if pedir("Repite la contraseña: ") != valor:
            raise _PasswordNoValida([], [origen], "las dos contraseñas escritas no coinciden")
    motivo = validaciones.motivo_password_no_valida(valor)
    if motivo is not None:
        raise _PasswordNoValida([], [origen], motivo)
    return valor


async def comando_crear_usuario(ajustes: Settings, argumentos: argparse.Namespace) -> int:
    try:
        password = leer_password()
    except _PasswordNoValida as exc:
        campos = {"faltan": exc.faltan, "invalidas": exc.invalidas, "motivo": exc.motivo}
        registrar(log, "configuracion_incompleta", logging.ERROR, **campos)
        return SALIDA_CONFIGURACION
    motor = _motor(ajustes)
    if motor is None:
        return SALIDA_CONFIGURACION
    try:
        guardado = await usuarios.crear_o_actualizar(
            motor,
            correo=argumentos.correo,
            nombre=argumentos.nombre,
            rol=RolUsuario(argumentos.rol) if argumentos.rol else None,
            password=password,
        )
    except usuarios.UltimoAdmin as exc:
        registrar(log, "usuario_rechazado", logging.ERROR, motivo=str(exc))
        return SALIDA_NEGATIVA
    except Exception as exc:
        return _fallo("crear-usuario", exc)
    finally:
        await motor.dispose()
    campos: dict[str, Any] = {"rol_anterior": str(guardado.rol_anterior)} if guardado.rol_anterior else {}
    registrar(
        log,
        "usuario_guardado",
        resultado=guardado.resultado,
        usuario_id=str(guardado.usuario_id),
        rol=str(guardado.rol),
        reactivado=guardado.reactivado,
        **campos,
    )
    return SALIDA_OK


async def comando_desactivar_usuario(ajustes: Settings, argumentos: argparse.Namespace) -> int:
    motor = _motor(ajustes)
    if motor is None:
        return SALIDA_CONFIGURACION
    try:
        desactivado = await usuarios.desactivar(motor, correo=argumentos.correo)
    except usuarios.UsuarioNoEncontrado:
        registrar(log, "usuario_no_encontrado", logging.WARNING)
        return SALIDA_NEGATIVA
    except usuarios.UltimoAdmin as exc:
        registrar(log, "usuario_rechazado", logging.ERROR, motivo=str(exc))
        return SALIDA_NEGATIVA
    except Exception as exc:
        return _fallo("desactivar-usuario", exc)
    finally:
        await motor.dispose()
    registrar(
        log,
        "usuario_desactivado",
        usuario_id=str(desactivado.usuario_id),
        ya_estaba_inactivo=desactivado.ya_estaba_inactivo,
    )
    return SALIDA_OK


def crear_almacen(ajustes: Settings):
    """El `AlmacenS3` del bucket del dataset (las pruebas sustituyen esta función por un doble)."""
    from app.clientes.s3 import AlmacenS3

    return AlmacenS3(ajustes.s3_bucket_dataset or "", ajustes.aws_region)


async def comando_limpiar_validacion(ajustes: Settings, argumentos: argparse.Namespace) -> int:
    from app.clientes.s3 import FalloS3

    if not (ajustes.s3_bucket_dataset or "").strip():
        registrar(
            log,
            "configuracion_incompleta",
            logging.ERROR,
            faltan=["S3_BUCKET_DATASET"],
            invalidas=[],
            motivo="falta S3_BUCKET_DATASET: limpiar-validacion corre con la definición de worker",
        )
        return SALIDA_CONFIGURACION
    motor = _motor(ajustes)
    if motor is None:
        return SALIDA_CONFIGURACION
    try:
        resultado = await limpieza.limpiar_validacion(
            motor, crear_almacen(ajustes), argumentos.videos, simular=argumentos.simular
        )
    except limpieza.LimpiezaRechazada as exc:
        registrar(
            log,
            "limpieza_rechazada",
            logging.ERROR,
            inexistentes=exc.inexistentes,
            sin_prefijo=exc.sin_prefijo,
            motivo=str(exc),
        )
        return SALIDA_NEGATIVA
    except FalloS3 as exc:
        operacion = "listar" if argumentos.simular else "borrar"
        registrar(log, "s3_fallido", logging.ERROR, operacion=operacion, motivo=str(exc))
        return SALIDA_NEGATIVA
    except Exception as exc:
        return _fallo("limpiar-validacion", exc)
    finally:
        await motor.dispose()
    resumen = json.dumps({"videos": resultado.videos, "objetos": resultado.objetos})
    if resultado.simulada:
        registrar(
            log,
            "limpieza_simulada",
            videos=resultado.videos,
            objetos=resultado.objetos,
            video_ids=resultado.video_ids,
        )
        print(f"SIMULACION {resumen}", flush=True)
        return SALIDA_OK
    if resultado.restos_s3:
        # Las filas ya no están: no se falla, pero quedan objetos huérfanos que hay que borrar a mano (§4.5).
        registrar(
            log,
            "limpieza_s3_incompleta",
            logging.WARNING,
            prefijos=resultado.restos_s3,
            motivo=resultado.motivo_restos,
        )
    registrar(
        log,
        "limpieza_validacion",
        videos=resultado.videos,
        objetos=resultado.objetos,
        video_ids=resultado.video_ids,
    )
    print(f"LIMPIEZA {resumen}", flush=True)
    return SALIDA_OK


COMANDOS: dict[str, Callable[[Settings, argparse.Namespace], Awaitable[int]]] = {
    "migrar": comando_migrar,
    "verificar-esquema": comando_verificar_esquema,
    "crear-usuario": comando_crear_usuario,
    "desactivar-usuario": comando_desactivar_usuario,
    "limpiar-validacion": comando_limpiar_validacion,
}


def main(argv: Sequence[str] | None = None, ajustes: Settings | None = None) -> int:
    try:
        argumentos = crear_parser().parse_args(argv)
    except SystemExit as salida:  # --help (0) o error de uso (3)
        return int(salida.code or 0)
    if ajustes is None:
        try:
            ajustes = get_settings()
        except ValidationError as exc:  # p. ej. DB_PORT=abc: código 3 y un evento JSON, no una traza suelta
            configurar_logs(PROCESO)
            invalidas = sorted({str(error["loc"][0]).upper() for error in exc.errors() if error.get("loc")})
            # `msg` no incluye el valor recibido (podría ser un secreto); `input` sí, y no se registra.
            motivo = "; ".join(f"{str(e['loc'][0]).upper()}: {e['msg']}" for e in exc.errors() if e.get("loc"))
            registrar(
                log, "configuracion_incompleta", logging.ERROR, faltan=[], invalidas=invalidas, motivo=motivo[:500]
            )
            return SALIDA_CONFIGURACION
    configurar_logs(PROCESO, ajustes.log_level)
    return asyncio.run(COMANDOS[argumentos.comando](ajustes, argumentos))


if __name__ == "__main__":
    sys.exit(main())
