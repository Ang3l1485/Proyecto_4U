"""Pruebas de contrato: las respuestas cumplen exactamente los esquemas de ARCHITECTURE §5.1 y §5.3."""

from __future__ import annotations

import tomllib
from pathlib import Path

from app import __version__
from app.esquemas.errores import ErrorRespuesta
from app.esquemas.salud import PreparacionRespuesta, SaludRespuesta

RAIZ = Path(__file__).resolve().parents[2]


def test_health_cumple_el_esquema(cliente):
    cuerpo = cliente.get("/v1/health").json()
    SaludRespuesta.model_validate(cuerpo)  # extra="forbid": ni más ni menos campos
    assert set(cuerpo) == {"estado", "version", "commit"}


def test_ready_cumple_el_esquema(cliente, ajustes, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.db import sesion
    from app.main import crear_app

    async def base_responde(_motor, _timeout_s):
        return None

    monkeypatch.setattr(sesion, "comprobar_conexion", base_responde)
    configurados = ajustes.model_copy(
        update={
            "db_host": "base.invalid",
            "db_name": "campus_locator",
            "db_user": "campus_app",
            "db_password": SecretStr("x"),
        }
    )
    with TestClient(crear_app(configurados)) as con_base:
        cuerpo = con_base.get("/v1/health/ready").json()
    PreparacionRespuesta.model_validate(cuerpo)
    assert set(cuerpo) == {"estado", "db", "embedding"}
    assert cuerpo["db"] == "ok"


def test_ready_sin_base_cumple_el_formato_de_error(cliente):
    r = cliente.get("/v1/health/ready")
    assert r.status_code == 503
    ErrorRespuesta.model_validate(r.json())
    assert r.json()["error"]["codigo"] == "BASE_NO_DISPONIBLE"


def test_errores_cumplen_el_esquema(cliente):
    for metodo, ruta in (("GET", "/v1/no-existe"), ("DELETE", "/v1/health"), ("GET", "/no-v1")):
        r = cliente.request(metodo, ruta)
        assert r.status_code >= 400
        ErrorRespuesta.model_validate(r.json())


def test_openapi_publica_las_rutas_del_lote(cliente):
    rutas = cliente.get("/v1/openapi.json").json()["paths"]
    assert {"/v1/health", "/v1/health/ready"} <= set(rutas)


def test_version_del_paquete_coincide_con_pyproject():
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert datos["project"]["version"] == __version__
