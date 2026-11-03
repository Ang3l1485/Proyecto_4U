"""BE-3.3 sin base de datos: `GET /v1/alerts` es público y valida `desde` antes de tocar la base; `/v1/admin/alerts`
exige token antes de validar el cuerpo (ARCHITECTURE §4.11, §5.3, §5.5)."""

from __future__ import annotations

import base64
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import crear_app

CLAVE = base64.b64encode(b"clave-de-pruebas-de-alertas-sin-base".ljust(64, b"x")).decode()


@pytest.fixture
def cliente_jwt(ajustes: Settings):
    with TestClient(crear_app(ajustes.model_copy(update={"jwt_secret": SecretStr(CLAVE)}))) as c:
        yield c


def _error(r) -> str:
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}
    return cuerpo["error"]["codigo"]


@pytest.mark.parametrize("encabezados", [{}, {"Authorization": "Bearer no-es-un-token"}])
def test_get_alerts_es_publico_y_sin_base_da_503(cliente, encabezados):
    r = cliente.get("/v1/alerts", headers=encabezados)
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")


@pytest.mark.parametrize(
    "desde",
    ["ayer", "2026-10-26T10:00:00", "2026-13-01T00:00:00Z", "0001-01-01T00:00:00+05:00", "2026-10-26T10:00:00 00:00"],
)
def test_desde_no_valido_es_422_antes_de_la_base(cliente, desde):
    r = cliente.get("/v1/alerts", params={"desde": desde})
    assert (r.status_code, _error(r)) == (422, "VALIDACION"), r.text
    assert [c["campo"] for c in r.json()["error"]["detalle"]["campos"]] == ["desde"]


def test_desde_con_z_llega_bien_sin_codificar(cliente):
    """`generado_en` lleva `Z`: tal cual en la URL no hace falta codificarlo (sin base, 503: pasó la validación)."""
    r = cliente.get("/v1/alerts?desde=2026-10-26T10:00:00Z")
    assert r.status_code == 503


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("GET", "/v1/admin/alerts", None),
        ("PUT", f"/v1/admin/alerts/{uuid.uuid4()}", {"radio_m": 500}),
        ("PUT", "/v1/admin/alerts/no-es-uuid", {}),
        ("DELETE", f"/v1/admin/alerts/{uuid.uuid4()}", None),
        ("POST", "/v1/admin/alerts/sincronizar", {"cambios": []}),
    ],
)
def test_admin_alerts_sin_token_es_401_antes_que_422(cliente_jwt, metodo, ruta, cuerpo):
    r = cliente_jwt.request(metodo, ruta, json=cuerpo)
    assert (r.status_code, _error(r)) == (401, "NO_AUTENTICADO")
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_barra_final_y_metodo_no_permitido(cliente):
    assert cliente.get("/v1/alerts/").status_code == 404  # sin barra final (§5.1)
    r = cliente.post("/v1/alerts")
    assert (r.status_code, _error(r)) == (405, "SOLICITUD_INVALIDA")
