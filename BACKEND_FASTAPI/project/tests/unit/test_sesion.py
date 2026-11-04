"""Conexión a la base sin base de datos: configuración y clasificación de fallos (`app.db.sesion`)."""

from __future__ import annotations

import asyncio
import socket
import ssl

import asyncpg
import pytest
from sqlalchemy import exc as sa_exc

from app.config import Settings
from app.db import sesion


def _ajustes(**cambios) -> Settings:
    base = {
        "db_host": "campus-locator-dev-db.example",
        "db_name": "campus_locator",
        "db_user": "campus_app",
        "db_password": "contraseña con @ y /",
    }
    return Settings(**(base | cambios))


def test_faltan_variables():
    assert sesion.faltan_variables(Settings(db_host=None, db_password=None)) == [
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]
    assert sesion.faltan_variables(_ajustes()) == []
    assert sesion.faltan_variables(_ajustes(db_host="  ")) == ["DB_HOST"]


def test_url_escapa_y_oculta_la_contrasena():
    url = sesion.url_conexion(_ajustes())
    assert url.password == "contraseña con @ y /"
    assert "contraseña" not in repr(url)
    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.database, url.username) == (
        "campus-locator-dev-db.example",
        5432,
        "campus_locator",
        "campus_app",
    )


def test_url_sin_configuracion_lanza_configuracion_incompleta():
    with pytest.raises(sesion.ConfiguracionIncompleta) as error:
        sesion.url_conexion(Settings(db_host=None))
    assert "DB_HOST" in error.value.faltan


@pytest.mark.parametrize("modo", ["require", "REQUIRE", " disable ", "verify-full"])
def test_argumentos_de_conexion(modo):
    argumentos = sesion.argumentos_conexion(_ajustes(db_sslmode=modo, db_connect_timeout_s=4), "migrate")
    assert argumentos["ssl"] == modo.strip().lower()
    assert argumentos["timeout"] == 4
    assert argumentos["server_settings"] == {"application_name": "campus-locator-migrate"}


def test_crear_motor_no_se_conecta():
    motor = sesion.crear_motor(_ajustes(), "api", pool=5, desborde=5)
    assert motor.pool.size() == 5
    asyncio.run(motor.dispose())


def _envuelto(original: BaseException, invalidada: bool = False) -> sa_exc.DBAPIError:
    return sa_exc.DBAPIError("SELECT 1", {}, original, connection_invalidated=invalidada)


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(111, "Connect call failed"),
        TimeoutError(),
        OSError("Multiple exceptions: [Errno 111] …, [Errno 101] Network is unreachable"),
        socket.gaierror(-2, "Name or service not known"),
        ssl.SSLError("certificate verify failed"),
        asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed in the middle of operation"),
        asyncpg.exceptions.ConnectionFailureError("08006"),
        asyncpg.exceptions.ClientCannotConnectError("08001"),
        asyncpg.exceptions.AdminShutdownError("terminating connection due to administrator command"),
        sesion.BaseNoDisponible("InsufficientPrivilegeError: permission denied for database"),
    ],
)
def test_fallos_de_conexion(error):
    assert sesion.es_fallo_de_conexion(error)
    assert sesion.es_fallo_de_conexion(_envuelto(error))


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("no se encontró migrations/env.py"),
        PermissionError(13, "Permission denied: 'migrations/versions/0001_esquema_inicial.py'"),
        asyncpg.exceptions.InsufficientPrivilegeError("permission denied for table usuarios"),
    ],
)
def test_errores_de_archivos_o_permisos_tras_conectar_no_son_de_conexion(error):
    assert not sesion.es_fallo_de_conexion(error)


def test_no_sigue_el_contexto_implicito():
    try:
        try:
            raise ConnectionRefusedError(111, "antes")
        except ConnectionRefusedError:
            raise ValueError("otro error mientras se manejaba el anterior")  # noqa: B904
    except ValueError as exc:
        assert exc.__context__ is not None
        assert not sesion.es_fallo_de_conexion(exc)


def test_conectar_convierte_cualquier_fallo_al_abrir():
    class ConexionQueNoAbre:
        async def start(self):
            raise asyncpg.exceptions.InsufficientPrivilegeError('permission denied for database "campus_locator"')

    class Motor:
        def connect(self):
            return ConexionQueNoAbre()

    async def abrir():
        async with sesion.conectar(Motor()):
            pass

    with pytest.raises(sesion.BaseNoDisponible, match="InsufficientPrivilegeError") as error:
        asyncio.run(abrir())
    assert sesion.es_fallo_de_conexion(error.value)


def test_el_motor_oculta_los_parametros_en_los_errores():
    motor = sesion.crear_motor(_ajustes(), "migrate")
    assert motor.sync_engine.hide_parameters is True
    asyncio.run(motor.dispose())


def test_conexion_invalidada_es_fallo_de_conexion():
    assert sesion.es_fallo_de_conexion(_envuelto(Exception("x"), invalidada=True))


@pytest.mark.parametrize(
    "error",
    [
        asyncpg.exceptions.UndefinedTableError('relation "x" does not exist'),
        asyncpg.exceptions.CheckViolationError("violates check constraint"),
        ValueError("otra cosa"),
    ],
)
def test_errores_de_sentencias_no_son_de_conexion(error):
    assert not sesion.es_fallo_de_conexion(error)
    assert not sesion.es_fallo_de_conexion(_envuelto(error))


def test_describir_llega_al_error_original():
    original = asyncpg.exceptions.InvalidPasswordError('password authentication failed for user "campus_app"')
    try:
        try:
            raise original
        except asyncpg.exceptions.InvalidPasswordError as exc:
            raise _envuelto(exc) from exc
    except sa_exc.DBAPIError as envuelto:
        assert sesion.describir(envuelto) == (
            'InvalidPasswordError: password authentication failed for user "campus_app"'
        )


def test_describir_un_timeout_no_dice_cancelled():
    async def lento():
        async with asyncio.timeout(0.01):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError) as error:
        asyncio.run(lento())
    assert sesion.describir(error.value) == "TimeoutError"


def test_comprobar_conexion_convierte_cualquier_fallo(monkeypatch):
    class MotorRoto:
        def connect(self):
            raise ConnectionRefusedError(111, "rechazada")

    with pytest.raises(sesion.BaseNoDisponible, match="ConnectionRefusedError"):
        asyncio.run(sesion.comprobar_conexion(MotorRoto(), 1))
