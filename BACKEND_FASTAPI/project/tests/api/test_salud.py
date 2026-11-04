"""GET /v1/health y GET /v1/health/ready (ARCHITECTURE §5.3). Con base real: tests/base/test_salud_base.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.clientes.embedding as cliente_embedding
from app import __version__
from app.config import Settings
from app.db import sesion
from app.main import crear_app


def test_health_responde_estado_version_y_commit_corto(cliente):
    r = cliente.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "version": __version__, "commit": "0123456"}


def test_health_no_redirige_con_barra_final(cliente):
    r = cliente.get("/v1/health/", follow_redirects=False)
    assert r.status_code == 404
    assert r.json()["error"]["codigo"] == "NO_ENCONTRADO"


def test_ready_sin_db_configurada_es_503(cliente, logs_json):
    r = cliente.get("/v1/health/ready", headers={"X-Request-Id": "ready-sin-base"})
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "BASE_NO_DISPONIBLE"
    assert r.headers["X-Request-Id"] == "ready-sin-base"
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "base_no_disponible"]
    assert "DB_HOST" in evento["motivo"]
    assert evento["request_id"] == "ready-sin-base"


@pytest.fixture
def cliente_con_base(ajustes: Settings, monkeypatch):
    """App con `DB_*` (a un host que no existe) y la comprobación de la base sustituida: responde `SELECT 1`."""
    llamadas: list[float] = []

    async def base_responde(_motor, timeout_s):
        llamadas.append(timeout_s)

    monkeypatch.setattr(sesion, "comprobar_conexion", base_responde)
    configurados = ajustes.model_copy(
        update={
            "db_host": "base.invalid",
            "db_name": "campus_locator",
            "db_user": "campus_app",
            "db_password": SecretStr("x"),
        }
    )
    with TestClient(crear_app(configurados)) as cliente:
        cliente.llamadas = llamadas
        yield cliente


@pytest.mark.parametrize(("listo", "esperado"), [(True, "ok"), (False, "no_disponible")])
def test_ready_con_base_informa_embedding_sin_503(cliente_con_base, monkeypatch, listo, esperado):
    async def falso(_ajustes):
        return listo

    monkeypatch.setattr(cliente_embedding, "esta_listo", falso)
    r = cliente_con_base.get("/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "db": "ok", "embedding": esperado}
    assert cliente_con_base.llamadas == [5.0]  # DB_CONNECT_TIMEOUT_S


def test_ready_con_base_caida_es_503(cliente_con_base, monkeypatch, logs_json):
    async def base_caida(_motor, _timeout_s):
        raise sesion.BaseNoDisponible("TimeoutError")

    monkeypatch.setattr(sesion, "comprobar_conexion", base_caida)
    r = cliente_con_base.get("/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["error"] == {
        "codigo": "BASE_NO_DISPONIBLE",
        "mensaje": "La base de datos no está disponible.",
        "detalle": None,
    }
    assert [linea["motivo"] for linea in logs_json.lineas if linea["evento"] == "base_no_disponible"] == [
        "TimeoutError"
    ]


def test_ready_con_sslmode_no_valido_dice_el_motivo(ajustes: Settings, logs_json):
    configurados = ajustes.model_copy(
        update={
            "db_host": "h",
            "db_name": "n",
            "db_user": "u",
            "db_password": SecretStr("x"),
            "db_sslmode": "obligatorio",
        }
    )
    with TestClient(crear_app(configurados)) as cliente:
        assert cliente.get("/v1/health/ready").status_code == 503
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "base_no_disponible"]
    assert "DB_SSLMODE" in evento["motivo"]


def test_health_no_toca_la_base(cliente_con_base, monkeypatch):
    async def no_llamar(*_):
        raise AssertionError("/v1/health no debe consultar la base")

    monkeypatch.setattr(sesion, "comprobar_conexion", no_llamar)
    assert cliente_con_base.get("/v1/health").status_code == 200
