"""`crear-usuario` y `desactivar-usuario` sin base de datos: argumentos, contraseña y códigos (ARCHITECTURE §5.9)."""

from __future__ import annotations

import io

import pytest
from pydantic import SecretStr

from app import cli
from app.config import Settings

CORRECTOS = ["crear-usuario", "--correo", "a@campus.edu.co", "--nombre", "Persona"]


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def sin_base() -> Settings:
    return Settings(app_env="test", log_level="DEBUG", db_host=None, db_password=None)


@pytest.fixture
def inalcanzable() -> Settings:
    return Settings(
        app_env="test",
        db_host="127.0.0.1",
        db_port=1,
        db_name="campus_locator",
        db_user="campus_app",
        db_password=SecretStr("no-importa"),
        db_sslmode="disable",
        db_connect_timeout_s=2,
    )


@pytest.fixture(autouse=True)
def sin_terminal(monkeypatch):
    monkeypatch.delenv(cli.VARIABLE_PASSWORD, raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO())  # no es una terminal


def _eventos(logs_json, nombre):
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


@pytest.mark.parametrize(
    "argumentos",
    [
        ["crear-usuario", "--correo", "sin-arroba", "--nombre", "P"],
        ["crear-usuario", "--correo", "dos@@x", "--nombre", "P"],
        ["crear-usuario", "--correo", "con espacio@x.co", "--nombre", "P"],
        ["crear-usuario", "--correo", "a@b.co", "--nombre", "   "],
        ["crear-usuario", "--correo", "a@b.co", "--nombre", "P", "--rol", "root"],
        ["crear-usuario", "--correo", "a@b.co"],
        ["desactivar-usuario"],
        ["desactivar-usuario", "--correo", "x"],
    ],
)
def test_argumentos_no_validos_terminan_con_3_por_stderr(sin_base, capsys, argumentos):
    assert cli.main(argumentos, ajustes=sin_base) == 3
    assert "error:" in capsys.readouterr().err


def test_sin_password_ni_terminal_termina_con_3(sin_base, logs_json):
    assert cli.main(CORRECTOS, ajustes=sin_base) == 3
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert (evento["faltan"], evento["invalidas"]) == (["CREAR_USUARIO_PASSWORD"], [])


@pytest.mark.parametrize("password", ["corta", "x" * 257])
def test_password_fuera_de_rango_termina_con_3_sin_mostrarla(sin_base, logs_json, monkeypatch, password):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, password)
    assert cli.main(CORRECTOS, ajustes=sin_base) == 3
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert evento["invalidas"] == ["CREAR_USUARIO_PASSWORD"]
    assert "entre 8 y 256" in evento["motivo"]
    assert password not in str(logs_json.lineas)


def test_password_valida_sin_db_termina_con_3_por_db(sin_base, logs_json, monkeypatch):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, "una-clave-valida")
    assert cli.main(CORRECTOS, ajustes=sin_base) == 3
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert evento["faltan"] == ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]


def test_desactivar_sin_db_termina_con_3(sin_base):
    assert cli.main(["desactivar-usuario", "--correo", "a@b.co"], ajustes=sin_base) == 3


def test_base_inalcanzable_termina_con_2(inalcanzable, logs_json, monkeypatch):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, "una-clave-valida")
    assert cli.main(CORRECTOS, ajustes=inalcanzable) == 2
    assert cli.main(["desactivar-usuario", "--correo", "a@b.co"], ajustes=inalcanzable) == 2
    assert len(_eventos(logs_json, "base_no_disponible")) == 2
    texto = str(logs_json.lineas)
    assert "una-clave-valida" not in texto and "no-importa" not in texto


def test_password_desde_la_terminal():
    respuestas = iter(["clave-terminal", "clave-terminal"])
    assert cli.leer_password(Terminal(), lambda _texto: next(respuestas)) == "clave-terminal"


def test_password_de_la_terminal_que_no_coincide():
    respuestas = iter(["clave-terminal", "otra-clave"])
    with pytest.raises(cli._PasswordNoValida) as error:
        cli.leer_password(Terminal(), lambda _texto: next(respuestas))
    assert error.value.invalidas == ["terminal"]
    assert "clave" not in error.value.motivo


def test_la_variable_tiene_prioridad_sobre_la_terminal(monkeypatch):
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, "clave-de-variable")
    assert cli.leer_password(Terminal(), lambda _texto: pytest.fail("no debe preguntar")) == "clave-de-variable"


def test_ayuda_de_los_comandos_nuevos(capsys):
    for comando in ("crear-usuario", "desactivar-usuario"):
        assert cli.main([comando, "--help"]) == 0
    assert "CREAR_USUARIO_PASSWORD" in capsys.readouterr().out
