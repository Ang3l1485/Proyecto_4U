"""Validador de BE-3.1 (validation-3-1.md) contra el backend real: la app de FastAPI con una base PostgreSQL efímera
(marca `base`), servida con `TestClient` como el `http` de `comun.ClienteApi`. Se prueban el camino feliz en `local` y
en `dev` (con AWS simulado), la idempotencia, `--solo`, el barrido de restos y backends defectuosos."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import comun
import validate31
from app.config import Settings
from app.main import crear_app
from app.servicios import lugares

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-validate31".ljust(64, b"z")).decode()
URL = "http://testserver/v1"
COMPROBACIONES = ["C1a", "C1b", "C1c", "C2a", "C2b", "C2c", "C3a", "C3b", "C3c", "C4a", "C4b"]


class Http:
    """`request()`/`close()` sobre un `TestClient` ya abierto; `close()` no lo cierra (lo cierra la fixture).
    `sustituir(ruta) → respuesta | None` permite simular un backend distinto en una ruta."""

    def __init__(self, cliente: TestClient) -> None:
        self.cliente = cliente
        self.sustituir = lambda metodo, url: None

    def request(self, metodo: str, url: str, **kwargs: Any) -> Any:
        return self.sustituir(metodo, url) or self.cliente.request(metodo, url, **kwargs)

    def close(self) -> None:
        pass


@pytest.fixture
def ajustes_val(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def http(ajustes_val):
    with TestClient(crear_app(ajustes_val)) as cliente:
        yield Http(cliente)


@pytest.fixture
def entorno_local(monkeypatch):
    monkeypatch.setenv("VALIDACION_API_URL", URL)
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)


def correr(http: Http, tmp_path, *argumentos: str, entorno: str = "local", sello: str | None = None):
    ctx = validate31.Contexto(entorno)
    ctx.http = http
    ctx.dormir = lambda s: None
    if sello:
        ctx.sello = sello
    informe = tmp_path / f"informe-{len(list(tmp_path.iterdir()))}.json"
    codigo = validate31.main(["--entorno", entorno, "--informe", str(informe), *argumentos], ctx=ctx)
    return codigo, json.loads(informe.read_text(encoding="utf-8")), ctx


def estados(datos: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in datos["precondiciones"] + datos["comprobaciones"]}


def lugares_en_base(http: Http) -> list[dict]:
    r = http.cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
    token = r.json()["token"]
    return http.cliente.get("/v1/admin/places", headers={"Authorization": f"Bearer {token}"}).json()["items"]


def test_local_pasa_entero_y_deja_la_base_limpia(http, tmp_path, entorno_local, capsys):
    codigo, datos, _ = correr(http, tmp_path)
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    assert estados(datos) == {"P2": "pasa", "P3": "pasa"} | dict.fromkeys(COMPROBACIONES, "pasa")
    assert datos["lote"] == "BE-3.1" and datos["entorno"] == "local" and datos["resultado"] == "pasa"
    salida = capsys.readouterr().out
    assert "[PREPARACION] sin lugares validacion- de ejecuciones anteriores" in salida
    assert "[LIMPIEZA] lugares de prueba borrados: 3" in salida  # B, C y D (A ya lo borró C1c)
    assert lugares_en_base(http) == []
    assert PASSWORD_ADMIN not in salida and "Bearer" not in salida


def test_dev_toma_la_url_de_terraform_y_repetir_da_lo_mismo(http, tmp_path, monkeypatch):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)
    monkeypatch.setattr(comun, "sesion_aws", lambda: object())
    monkeypatch.setattr(comun, "verificar_cuenta", lambda sesion: "arn:aws:iam::648617469176:user/validador")
    monkeypatch.setattr(comun, "outputs_terraform", lambda: {"api_base_url": "http://testserver"})
    for sello in ("20261025-120000", "20261025-120001"):
        codigo, datos, _ = correr(http, tmp_path, entorno="dev", sello=sello)
        assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
        assert estados(datos)["P1"] == "pasa" and set(estados(datos).values()) == {"pasa"}
    assert lugares_en_base(http) == []


def test_preparacion_borra_restos_de_otras_ejecuciones(http, tmp_path, entorno_local, capsys):
    token = http.cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN}).json()
    cabecera = {"Authorization": f"Bearer {token['token']}"}
    for nombre in ("validacion-99 resto", "VALIDACIÓN-41 otro resto", "Biblioteca real"):
        cuerpo = {"nombre": nombre, "categoria": "bloque", "lat": 6.2, "lng": -75.57}
        assert http.cliente.post("/v1/admin/places", json=cuerpo, headers=cabecera).status_code == 201
    codigo, _, _ = correr(http, tmp_path, "--solo", "C1")
    assert codigo == 0
    assert "[PREPARACION] lugares validacion- borrados: 2" in capsys.readouterr().out
    assert [lugar["nombre"] for lugar in lugares_en_base(http)] == ["Biblioteca real"]


@pytest.mark.parametrize("solo", ["C1b", "C1c", "C2", "C3c", "C4"])
def test_cada_comprobacion_crea_lo_que_necesita_con_solo(http, tmp_path, entorno_local, solo):
    codigo, datos, _ = correr(http, tmp_path, "--solo", solo)
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    pasan = {i for i, e in estados(datos).items() if e == "pasa" and i.startswith("C")}
    assert pasan and all(i.startswith(solo) for i in pasan)
    assert lugares_en_base(http) == []


def test_con_sin_limpieza_deja_los_lugares(http, tmp_path, entorno_local):
    codigo, _, _ = correr(http, tmp_path, "--solo", "C2a", "--sin-limpieza")
    assert codigo == 0
    assert len(lugares_en_base(http)) == 2


def test_backend_que_distingue_tildes_falla_c3b_y_limpia_lo_que_creo(http, tmp_path, entorno_local, monkeypatch):
    monkeypatch.setattr(lugares, "normalizar_nombre", lambda texto: " ".join(texto.lower().split()))
    codigo, datos, _ = correr(http, tmp_path)
    assert codigo == 1
    resultado = estados(datos)
    assert resultado["C3b"] == "falla" and resultado["C3a"] == "pasa"
    assert "409" in next(c["detalle"] for c in datos["comprobaciones"] if c["id"] == "C3b")
    assert lugares_en_base(http) == []


def test_backend_que_no_ordena_por_distancia_falla_c2a(http, tmp_path, entorno_local, monkeypatch):
    original = lugares.listar_publico

    async def al_reves(motor, **kwargs):
        return list(reversed(await original(motor, **kwargs)))

    monkeypatch.setattr(lugares, "listar_publico", al_reves)
    codigo, datos, _ = correr(http, tmp_path, "--solo", "C2")
    assert codigo == 1
    assert estados(datos)["C2a"] == "falla" and estados(datos)["C2b"] == "pasa"


def test_sin_get_places_desplegado_es_codigo_2(http, tmp_path, entorno_local):
    def sin_lugares(metodo, url):
        if url.endswith("/v1/places"):
            return httpx.Response(404, json={"error": {"codigo": "NO_ENCONTRADO", "mensaje": "…", "detalle": None}})
        return None

    http.sustituir = sin_lugares
    codigo, datos, _ = correr(http, tmp_path)
    assert codigo == 2
    assert "BE-3.1 sin desplegar" in datos["precondiciones"][-1]["detalle"]
    assert all(c["estado"] != "pasa" for c in datos["comprobaciones"]) and datos["comprobaciones"] == []


def test_credenciales_malas_son_codigo_3(http, tmp_path, entorno_local, monkeypatch, capsys):
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", "otra-contraseña-123")
    codigo, datos, _ = correr(http, tmp_path)
    assert codigo == 3
    assert "401" in datos["precondiciones"][-1]["detalle"]
    salida = capsys.readouterr().out
    assert "[LIMPIEZA] nada que limpiar (no se llegó a iniciar sesión)" in salida
    assert "otra-contraseña-123" not in salida


def test_local_sin_url_es_codigo_3(http, tmp_path, monkeypatch):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    codigo, datos, _ = correr(http, tmp_path)
    assert codigo == 3 and "VALIDACION_API_URL" in datos["precondiciones"][0]["detalle"]


def test_normalizar_nombre_de_comun_es_la_regla_del_backend():
    from app.dominio.lugares import normalizar_nombre

    for texto in ("Café  Norte", "BAÑO", "Straße", "ﬁ x", "  validación-31  ", "Ångström", "́"):
        assert comun.normalizar_nombre(texto) == normalizar_nombre(texto)
