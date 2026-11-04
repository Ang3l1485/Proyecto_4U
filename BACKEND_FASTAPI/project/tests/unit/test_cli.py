"""`python -m app.cli`: argumentos y códigos de salida sin base de datos (ARCHITECTURE §5.9)."""

from __future__ import annotations

import pytest

from app import cli
from app.config import Settings


@pytest.fixture
def sin_base() -> Settings:
    return Settings(app_env="test", log_level="DEBUG", db_host=None, db_password=None)


def _eventos(logs_json, nombre):
    return [linea for linea in logs_json.lineas if linea["evento"] == nombre]


@pytest.mark.parametrize("comando", ["migrar", "verificar-esquema"])
def test_sin_variables_db_termina_con_3(sin_base, logs_json, comando):
    assert cli.main([comando], ajustes=sin_base) == 3
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert evento["faltan"] == ["DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    assert evento["nivel"] == "ERROR"


@pytest.mark.parametrize("comando", ["migrar", "verificar-esquema"])
def test_base_inalcanzable_termina_con_2(logs_json, comando):
    # Puerto 1 de localhost: conexión rechazada al instante.
    ajustes = Settings(
        app_env="test",
        db_host="127.0.0.1",
        db_port=1,
        db_name="campus_locator",
        db_user="campus_app",
        db_password="no-importa",
        db_sslmode="disable",
        db_connect_timeout_s=2,
    )
    assert cli.main([comando], ajustes=ajustes) == 2
    [evento] = _eventos(logs_json, "base_no_disponible")
    assert "ConnectionRefusedError" in evento["motivo"] or "OSError" in evento["motivo"]
    assert "no-importa" not in str(logs_json.lineas)


def test_sslmode_no_valido_termina_con_3(logs_json):
    ajustes = Settings(db_host="h", db_name="n", db_user="u", db_password="p", db_sslmode="obligatorio")
    assert cli.main(["verificar-esquema"], ajustes=ajustes) == 3
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert (evento["faltan"], evento["invalidas"]) == ([], ["DB_SSLMODE"])


@pytest.mark.parametrize(("variable", "valor"), [("DB_PORT", "abc"), ("DB_CONNECT_TIMEOUT_S", "pronto")])
def test_variable_con_valor_no_valido_termina_con_3_en_json(monkeypatch, logs_json, capsys, variable, valor):
    from app.config import get_settings

    monkeypatch.setenv(variable, valor)
    get_settings.cache_clear()
    try:
        assert cli.main(["migrar"]) == 3
    finally:
        get_settings.cache_clear()
    [evento] = _eventos(logs_json, "configuracion_incompleta")
    assert evento["invalidas"] == [variable]
    assert valor not in evento["motivo"]  # el valor recibido no se registra
    assert "Traceback" not in capsys.readouterr().err


def _ajustes_con_base() -> Settings:
    return Settings(db_host="127.0.0.1", db_port=1, db_name="n", db_user="u", db_password="p", db_sslmode="disable")


def test_sin_migraciones_migrar_falla_con_1(monkeypatch, logs_json):
    from app.servicios import migracion

    def sin_directorio():
        raise FileNotFoundError("no se encontró migrations/env.py")

    monkeypatch.setattr(migracion, "directorio_migraciones", sin_directorio)
    assert cli.main(["migrar"], ajustes=_ajustes_con_base()) == 1
    assert "FileNotFoundError" in _eventos(logs_json, "migracion_fallida")[0]["motivo"]
    assert _eventos(logs_json, "base_no_disponible") == []


def test_sin_migraciones_verificar_no_dice_base_no_disponible(monkeypatch, logs_json):
    from app.servicios import migracion

    def sin_directorio():
        raise FileNotFoundError("no se encontró migrations/env.py")

    monkeypatch.setattr(migracion, "directorio_migraciones", sin_directorio)
    assert cli.main(["verificar-esquema"], ajustes=_ajustes_con_base()) == 2
    assert "FileNotFoundError" in _eventos(logs_json, "verificacion_fallida")[0]["motivo"]
    assert _eventos(logs_json, "base_no_disponible") == []


@pytest.mark.parametrize("argumentos", [[], ["otro-comando"], ["migrar", "--sobra"]])
def test_error_de_uso_termina_con_3_no_con_2(sin_base, argumentos, capsys):
    assert cli.main(argumentos, ajustes=sin_base) == 3
    assert "usage:" in capsys.readouterr().err


def test_ayuda_termina_con_0(capsys):
    assert cli.main(["--help"]) == 0
    salida = capsys.readouterr().out
    assert "migrar" in salida
    assert "verificar-esquema" in salida


def test_se_ejecuta_como_modulo():
    import runpy

    with pytest.raises(SystemExit) as salida:
        runpy.run_module("app.cli", run_name="__main__", alter_sys=True)
    assert salida.value.code == 3  # sin comando: error de uso
