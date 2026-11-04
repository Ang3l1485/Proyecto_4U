"""BE-2.1 sin base: autorización, validación y configuración de las rutas de recolección y de videos (§5.4, §5.5).

`requiere_admin` se sustituye con `dependency_overrides` para llegar a la validación sin base; con la base real, las
pruebas de `tests/base/test_recoleccion_base.py`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.dominio.enumerados import RolUsuario
from app.main import crear_app
from app.seguridad.dependencias import UsuarioActual, requiere_admin

VIDEO = {"ref_cliente": "rec_0001"}
IMAGEN = {"orden": 1, "lat": 6.2, "lng": -75.5, "rumbo": None, "capturada_en": "2026-10-20T14:00:05Z", "bytes": 10}


def _admin() -> UsuarioActual:
    return UsuarioActual(id=uuid.uuid4(), nombre="Admin", correo="a@campus.edu.co", rol=RolUsuario.admin)


@pytest.fixture
def sin_base(ajustes):
    """App sin base (motor `None`) con `requiere_admin` sustituido."""
    app = crear_app(ajustes)
    app.dependency_overrides[requiere_admin] = _admin
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def sin_base_con_s3(ajustes, almacen_falso):
    app = crear_app(ajustes, almacen=almacen_falso)
    app.dependency_overrides[requiere_admin] = _admin
    with TestClient(app) as cliente:
        yield cliente


def _error(r) -> str:
    assert set(r.json()) == {"error"}
    return r.json()["error"]["codigo"]


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("POST", "/v1/collect/videos", VIDEO),
        ("POST", f"/v1/collect/videos/{uuid.uuid4()}/images", {"imagenes": [IMAGEN]}),
        ("POST", f"/v1/collect/videos/{uuid.uuid4()}/complete", None),
        ("GET", "/v1/admin/videos", None),
        ("GET", f"/v1/admin/videos/{uuid.uuid4()}", None),
    ],
)
def test_sin_token_es_401(cliente, metodo, ruta, cuerpo):
    r = cliente.request(metodo, ruta, json=cuerpo)
    assert (r.status_code, _error(r)) == (401, "NO_AUTENTICADO")


def test_con_admin_y_sin_base_es_503(sin_base_con_s3):
    r = sin_base_con_s3.post("/v1/collect/videos", json=VIDEO)
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    r = sin_base_con_s3.post(f"/v1/collect/videos/{uuid.uuid4()}/complete")
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    assert sin_base_con_s3.get("/v1/admin/videos").status_code == 503


def test_sin_s3_bucket_dataset_ni_base_responde_la_base_primero(sin_base, logs_json):
    """S3 se exige después de comprobar el video (§5.4): sin base, 503; el 500 por S3 está en las pruebas con base."""
    r = sin_base.post(f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [IMAGEN]})
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    r = sin_base.post(f"/v1/collect/videos/{uuid.uuid4()}/complete")
    assert (r.status_code, _error(r)) == (503, "BASE_NO_DISPONIBLE")
    assert not [e for e in logs_json.lineas if e["evento"] == "configuracion_incompleta"]


def test_un_lote_de_mas_de_50_se_rechaza_en_el_esquema(sin_base):
    r = sin_base.post(f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [IMAGEN] * 51})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert r.json()["error"]["detalle"]["campos"] == [
        {"campo": "imagenes", "motivo": "Debe tener como máximo 50 elementos."}
    ]


@pytest.mark.parametrize("fecha", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:00:00-05:00"])
def test_fechas_fuera_de_rango_en_utc_son_422_y_no_500(sin_base, fecha):
    r = sin_base.post("/v1/collect/videos", json=VIDEO | {"iniciado_en": fecha})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert r.json()["error"]["detalle"]["campos"][0]["campo"] == "iniciado_en"
    r = sin_base.post(
        f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [IMAGEN | {"capturada_en": fecha}]}
    )
    assert (r.status_code, _error(r)) == (422, "VALIDACION")


def test_el_cuerpo_se_valida_antes_que_la_base(sin_base):
    r = sin_base.post("/v1/collect/videos", json={})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert r.json()["error"]["detalle"]["campos"] == [{"campo": "ref_cliente", "motivo": "Campo obligatorio."}]
    r = sin_base.post(f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": []})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    r = sin_base.post(f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [IMAGEN | {"bytes": 0}]})
    assert r.json()["error"]["detalle"]["campos"][0]["campo"] == "imagenes.0.bytes"
    r = sin_base.post("/v1/collect/videos", content=b"{roto", headers={"Content-Type": "application/json"})
    assert (r.status_code, _error(r)) == (400, "SOLICITUD_INVALIDA")


def test_campos_de_mas_se_ignoran(sin_base_con_s3):
    r = sin_base_con_s3.post("/v1/collect/videos", json=VIDEO | {"otro": 1, "inicio": {"lat": 1, "lng": 2, "x": 3}})
    assert r.status_code == 503  # pasó la validación y llegó a la base


def test_parametros_del_listado_se_validan_antes_que_la_base(sin_base):
    r = sin_base.get("/v1/admin/videos", params={"por_pagina": 101})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    r = sin_base.get("/v1/admin/videos", params={"q": "x" * 101})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")


def test_rutas_con_barra_final_no_existen(sin_base):
    assert sin_base.post("/v1/collect/videos/", json=VIDEO).status_code == 404
    assert sin_base.get("/v1/admin/videos/").status_code == 404


def test_metodo_no_permitido_es_405(sin_base):
    r = sin_base.get(f"/v1/collect/videos/{uuid.uuid4()}/complete")
    assert (r.status_code, _error(r)) == (405, "SOLICITUD_INVALIDA")
