"""Validador de BE-3.3 (validation-3-3.md).

- Sin base: contra `ApiFalsa`, una API de alertas en memoria con el contrato de §5.3/§5.5 (reloj falso, margen de 60 s
  en las diferencias) e interruptores de backend defectuoso. Prueba el camino feliz en `local` y en `dev` (AWS
  simulado), `--solo`, el barrido de restos y los códigos 1, 2 y 3.
- Con base (marca `base`): contra el backend real (la app con una base PostgreSQL efímera servida con `TestClient`
  como el `http` de `comun.ClienteApi`), como `test_validate31.py`.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

import comun
import validate33

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
URL = "http://testserver/v1"
COMPROBACIONES = ["C1a", "C1b", "C1c", "C1d", "C2", "C3", "C4", "C5"]
FORMATO = "%Y-%m-%dT%H:%M:%SZ"
PLAN = "| Lote | Fase | Estado |\n|---|---|---|\n| BE-2.3 | 2 | Hecho | x |\n| BE-3.3 | 3 | En curso | x |\n"


def _error(estado: int, codigo: str, detalle: Any = None) -> httpx.Response:
    return httpx.Response(estado, json={"error": {"codigo": codigo, "mensaje": "…", "detalle": detalle}})


def _validacion(campo: str) -> httpx.Response:
    return _error(422, "VALIDACION", {"campos": [{"campo": campo, "motivo": "…"}]})


class ApiFalsa:
    """`request()`/`close()` como un `httpx.Client` sobre una API de alertas en memoria. Cada petición avanza el reloj
    0,25 s. Interruptores: `desplegado` (rutas de alertas), `sin_eliminadas` (las diferencias no traen `eliminadas`),
    `sin_conflicto` (ignora `If-Match`), `todo_o_nada` (`sincronizar` no aplica nada si un cambio falla),
    `cuenta_inactivas` (`alertas_activas` cuenta también las inactivas), `foto_sin_futuras` (la foto completa filtra
    por vigencia) y `deja_tombstone` (`DELETE` de un id desconocido deja un *tombstone*)."""

    def __init__(self) -> None:
        self.reloj = datetime(2026, 10, 26, 15, 0, 0, tzinfo=UTC)
        self.alertas: dict[str, dict[str, Any]] = {}
        self.token = "token-falso-de-pruebas"
        self.desplegado = True
        self.sin_eliminadas = False
        self.sin_conflicto = False
        self.todo_o_nada = False
        self.cuenta_inactivas = False
        self.foto_sin_futuras = False
        self.deja_tombstone = False
        self.stats_desplegado = True

    # -- utilidades --------------------------------------------------------------------------------------------------
    def _publica(self, fila: dict[str, Any]) -> dict[str, Any]:
        return {campo: fila[campo] for campo in comun.CAMPOS_ALERTA}

    def _admin(self, fila: dict[str, Any]) -> dict[str, Any]:
        quien = {"id": "7c1e0000-0000-4000-8000-000000000001", "nombre": "Administrador"}
        return self._publica(fila) | {"creado_en": fila["creado_en"], "creado_por": quien, "actualizado_por": quien}

    def _texto(self, momento: datetime) -> str:
        return momento.strftime(FORMATO)

    def _entrada(self, cuerpo: dict[str, Any]) -> dict[str, Any] | str:
        """Los campos de `AlertaEntrada` con sus valores por defecto, o el nombre del primer campo no válido."""
        mensaje = str(cuerpo.get("mensaje", "")).strip()
        if not 1 <= len(mensaje) <= 200:
            return "mensaje"
        radio = cuerpo.get("radio_m", 15)
        if not isinstance(radio, int) or not 5 <= radio <= 100:
            return "radio_m"
        return {
            "lat": cuerpo["lat"],
            "lng": cuerpo["lng"],
            "mensaje": mensaje,
            "tipo": cuerpo.get("tipo") or "otro",
            "prioridad": cuerpo.get("prioridad") or "normal",
            "radio_m": radio,
            "activa": cuerpo.get("activa", True),
            "vigencia_desde": cuerpo.get("vigencia_desde"),
            "vigencia_hasta": cuerpo.get("vigencia_hasta"),
        }

    def _guardar(self, alerta_id: str, datos: dict[str, Any], version: int | None) -> tuple[int, dict[str, Any]]:
        ahora = self._texto(self.reloj)
        fila = self.alertas.get(alerta_id)
        if version is not None and not self.sin_conflicto and (fila is None or fila["version"] != version):
            raise LookupError
        if fila is None:
            fila = {"id": alerta_id, **datos, "version": 1, "creado_en": ahora, "actualizado_en": ahora}
            fila["eliminada"] = False
            self.alertas[alerta_id] = fila
            return 201, fila
        restaurar = fila["eliminada"]
        if restaurar or any(fila[c] != v for c, v in datos.items()):
            fila.update(datos, version=fila["version"] + 1, actualizado_en=ahora, eliminada=False)
        return (201 if restaurar else 200), fila

    def _borrar(self, alerta_id: str) -> None:
        fila = self.alertas.get(alerta_id)
        ahora = self._texto(self.reloj)
        if fila is None and self.deja_tombstone:
            self.alertas[alerta_id] = {"id": alerta_id, "eliminada": True, "actualizado_en": ahora, "version": 1}
        elif fila is not None and not fila["eliminada"]:
            fila.update(eliminada=True, actualizado_en=ahora, version=fila["version"] + 1)

    # -- rutas -------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, **kwargs: Any) -> httpx.Response:
        self.reloj += timedelta(milliseconds=250)
        ruta = urlsplit(url).path.removeprefix("/v1")
        encabezados = kwargs.get("headers") or {}
        params = kwargs.get("params") or {}
        cuerpo = kwargs.get("json")
        if ruta == "/health/ready":
            return httpx.Response(200, json={"estado": "ok", "db": "ok", "embedding": "no_configurado"})
        if (metodo, ruta) == ("POST", "/auth/login"):
            if (cuerpo or {}).get("password") != PASSWORD_ADMIN:
                return _error(401, "CREDENCIALES_INVALIDAS")
            return httpx.Response(200, json={"token": self.token, "usuario": {"rol": "admin"}, "expira_en": "…"})
        if ruta.startswith("/admin") and encabezados.get("Authorization") != f"Bearer {self.token}":
            return _error(401, "NO_AUTENTICADO")
        if ruta == "/admin/stats":
            if not self.stats_desplegado:
                return _error(404, "NO_ENCONTRADO")
            vivas = [f for f in self.alertas.values() if not f["eliminada"]]
            activas = len([f for f in vivas if f["activa"] or self.cuenta_inactivas])
            return httpx.Response(
                200, json={"total_fotos": 0, "total_lugares": 0, "alertas_activas": activas, "ultimo_video": None}
            )
        if not self.desplegado or not ruta.startswith(("/alerts", "/admin/alerts")):
            return _error(404, "NO_ENCONTRADO")
        if (metodo, ruta) == ("GET", "/alerts"):
            return self._foto(params.get("desde"))
        if (metodo, ruta) == ("GET", "/admin/alerts"):
            q = comun.normalizar_nombre(str(params.get("q", "")))
            vivas = [f for f in self.alertas.values() if not f["eliminada"]]
            items = [self._admin(f) for f in vivas if q in comun.normalizar_nombre(f["mensaje"])]
            items.sort(key=lambda a: a["actualizado_en"], reverse=True)
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if (metodo, ruta) == ("POST", "/admin/alerts/sincronizar"):
            return self._sincronizar(cuerpo["cambios"])
        alerta_id = ruta.removeprefix("/admin/alerts/")
        if metodo == "DELETE":
            self._borrar(alerta_id)
            return httpx.Response(204)
        if metodo == "PUT":
            datos = self._entrada(cuerpo)
            if isinstance(datos, str):
                return _validacion(datos)
            version = encabezados.get("If-Match")
            try:
                estado, fila = self._guardar(alerta_id, datos, int(version.strip('"')) if version else None)
            except LookupError:
                return _error(409, "CONFLICTO_VERSION")
            return httpx.Response(estado, json=self._admin(fila))
        return _error(405, "SOLICITUD_INVALIDA")

    def _foto(self, desde: str | None) -> httpx.Response:
        generado_en = self._texto(self.reloj)
        if desde is None:
            vivas = [f for f in self.alertas.values() if not f["eliminada"] and f["activa"]]
            if self.foto_sin_futuras:
                vivas = [f for f in vivas if not f["vigencia_desde"] or f["vigencia_desde"] <= generado_en]
            alertas = [self._publica(f) for f in sorted(vivas, key=lambda f: f["actualizado_en"])]
            return httpx.Response(
                200, json={"generado_en": generado_en, "completo": True, "alertas": alertas, "eliminadas": []}
            )
        corte = self._texto(datetime.strptime(desde, FORMATO).replace(tzinfo=UTC) - timedelta(seconds=60))
        cambiadas = sorted((f for f in self.alertas.values() if f["actualizado_en"] >= corte), key=lambda f: f["id"])
        return httpx.Response(
            200,
            json={
                "generado_en": generado_en,
                "completo": False,
                "alertas": [self._publica(f) for f in cambiadas if not f["eliminada"]],
                "eliminadas": [] if self.sin_eliminadas else [f["id"] for f in cambiadas if f["eliminada"]],
            },
        )

    def _sincronizar(self, cambios: list[dict[str, Any]]) -> httpx.Response:
        entradas = [self._entrada(c["alerta"]) if c["op"] == "upsert" else None for c in cambios]
        falla_alguno = any(isinstance(e, str) for e in entradas)
        resultados = []
        for cambio, datos in zip(cambios, entradas, strict=True):
            alerta_id = cambio["alerta"]["id"] if cambio["op"] == "upsert" else cambio["id"]
            if isinstance(datos, str) or (self.todo_o_nada and falla_alguno):
                resultados.append({"id": alerta_id, "op": cambio["op"], "estado": "error", "codigo": "VALIDACION"})
                continue
            if cambio["op"] == "upsert":
                self._guardar(alerta_id, datos, None)
            else:
                self._borrar(alerta_id)
            resultados.append({"id": alerta_id, "op": cambio["op"], "estado": "ok", "codigo": None})
        return httpx.Response(200, json={"generado_en": self._texto(self.reloj), "resultados": resultados})

    def close(self) -> None:
        pass

    def vivas(self) -> list[dict[str, Any]]:
        return [f for f in self.alertas.values() if not f["eliminada"]]


@pytest.fixture
def entorno_local(monkeypatch):
    monkeypatch.setenv("VALIDACION_API_URL", URL)
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)
    monkeypatch.setattr(comun, "sesion_aws", lambda: object())
    monkeypatch.setattr(comun, "verificar_cuenta", lambda sesion: "arn:aws:iam::648617469176:user/validador")
    monkeypatch.setattr(comun, "outputs_terraform", lambda: {"api_base_url": "http://testserver"})
    plan = tmp_path / "PLAN.md"
    plan.write_text(PLAN, encoding="utf-8")
    return plan


def correr(http: Any, tmp_path, *argumentos: str, entorno: str = "local", sello: str | None = None, plan=None):
    ctx = validate33.Contexto(entorno)
    ctx.http = http
    ctx.dormir = lambda s: None
    ctx.ahora = lambda: datetime(2026, 10, 26, 15, 0, 0, tzinfo=UTC)
    if plan is not None:
        ctx.plan = plan
    if sello:
        ctx.sello = sello
    informe = tmp_path / f"informe-{len(list(tmp_path.glob('informe-*')))}.json"
    codigo = validate33.main(["--entorno", entorno, "--informe", str(informe), *argumentos], ctx=ctx)
    return codigo, json.loads(informe.read_text(encoding="utf-8")), ctx


def estados(datos: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in datos["precondiciones"] + datos["comprobaciones"]}


def detalle(datos: dict, id_: str) -> str:
    return next(c["detalle"] for c in datos["precondiciones"] + datos["comprobaciones"] if c["id"] == id_)


# --- Sin base: contra ApiFalsa -----------------------------------------------------------------------------------
def test_local_pasa_entero_y_deja_solo_tombstones(tmp_path, entorno_local, capsys):
    api = ApiFalsa()
    codigo, datos, _ = correr(api, tmp_path)
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    assert estados(datos) == {"P2": "pasa", "P3": "pasa", "P4": "pasa"} | dict.fromkeys(COMPROBACIONES, "pasa")
    assert datos["lote"] == "BE-3.3" and datos["entorno"] == "local" and datos["resultado"] == "pasa"
    assert detalle(datos, "P4") == "GET /v1/admin/stats → 200"  # en local no mira el PLAN
    salida = capsys.readouterr().out
    assert "[PREPARACION] sin alertas validacion- de ejecuciones anteriores" in salida
    assert "[LIMPIEZA] alertas de prueba borradas: 4" in salida  # F (C3), A2 (C4), G y H (C5)
    assert api.vivas() == []
    assert PASSWORD_ADMIN not in salida and api.token not in salida
    assert "alertas_activas 2 → 3 (+1)" in detalle(datos, "C5")  # antes: F (C3) y A2 (C4)


def test_dev_toma_la_url_de_terraform_y_repetir_da_lo_mismo(tmp_path, entorno_dev):
    api = ApiFalsa()
    for sello in ("20261026-150000", "20261026-150001"):
        codigo, datos, _ = correr(api, tmp_path, entorno="dev", sello=sello, plan=entorno_dev)
        assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
        assert estados(datos)["P1"] == "pasa" and set(estados(datos).values()) == {"pasa"}
        assert detalle(datos, "P4") == "BE-2.3 «Hecho» · GET /v1/admin/stats → 200"
    assert api.vivas() == []


def test_preparacion_borra_restos_y_no_toca_alertas_reales(tmp_path, entorno_local, capsys):
    api = ApiFalsa()
    real = {"lat": 6.2, "lng": -75.57, "mensaje": "Lago de la biblioteca"}
    for alerta_id, cuerpo in (
        ("resto-1", {"lat": 0.001, "lng": 0.001, "mensaje": "validacion-99 resto"}),
        ("resto-2", {"lat": 0.001, "lng": 0.001, "mensaje": "VALIDACIÓN-41 otro resto"}),
        ("real-1", real),
    ):
        api.request(
            "PUT", f"{URL}/admin/alerts/{alerta_id}", json=cuerpo, headers={"Authorization": f"Bearer {api.token}"}
        )
    codigo, datos, _ = correr(api, tmp_path, "--solo", "C2")
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    assert "[PREPARACION] alertas validacion- borradas: 2" in capsys.readouterr().out
    assert [f["id"] for f in api.vivas()] == ["real-1"]
    assert "P4" not in estados(datos)  # sin C5 no hace falta el resumen


@pytest.mark.parametrize("solo", ["C1b", "C1c", "C1d", "C3", "C4", "C5"])
def test_cada_comprobacion_crea_lo_que_necesita_con_solo(tmp_path, entorno_local, solo):
    api = ApiFalsa()
    codigo, datos, _ = correr(api, tmp_path, "--solo", solo)
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    pasan = {i for i, e in estados(datos).items() if e == "pasa" and i.startswith("C")}
    assert pasan == {solo}
    assert api.vivas() == []


def test_con_sin_limpieza_deja_las_alertas(tmp_path, entorno_local):
    api = ApiFalsa()
    codigo, _, _ = correr(api, tmp_path, "--solo", "C5", "--sin-limpieza")
    assert codigo == 0
    assert len(api.vivas()) == 2


@pytest.mark.parametrize(
    ("interruptor", "falla", "pasan", "texto"),
    [
        ("sin_eliminadas", "C1c", {"C1a", "C1b", "C2", "C3", "C4", "C5"}, "eliminadas"),
        ("sin_conflicto", "C1b", {"C1a", "C2", "C3", "C4", "C5"}, "409"),
        ("todo_o_nada", "C4", {"C1a", "C1b", "C1c", "C1d", "C2", "C3", "C5"}, "resultados"),
        ("cuenta_inactivas", "C5", {"C1a", "C1b", "C1c", "C1d", "C2", "C3", "C4"}, "+2"),
        ("foto_sin_futuras", "C3", {"C1a", "C1b", "C1c", "C1d", "C2", "C4", "C5"}, "vigencia futura"),
        ("deja_tombstone", "C2", {"C1a", "C1b", "C1c", "C1d", "C3", "C4", "C5"}, "tombstone"),
    ],
)
def test_backend_defectuoso_falla_su_comprobacion_y_limpia(tmp_path, entorno_local, interruptor, falla, pasan, texto):
    api = ApiFalsa()
    setattr(api, interruptor, True)
    codigo, datos, _ = correr(api, tmp_path)
    assert codigo == 1, json.dumps(datos, ensure_ascii=False, indent=1)
    resultado = estados(datos)
    assert resultado[falla] == "falla" and texto in detalle(datos, falla)
    assert {i for i, e in resultado.items() if e == "pasa" and i.startswith("C")} == pasan
    assert api.vivas() == []


def test_un_paso_de_c1_que_falla_no_se_repite(tmp_path, entorno_local):
    api = ApiFalsa()
    api.sin_conflicto = True
    _, datos, _ = correr(api, tmp_path, "--solo", "C1")
    assert detalle(datos, "C1c") == "depende de C1b, que falló"
    assert detalle(datos, "C1d") == "depende de C1b, que falló"


def test_sin_alertas_desplegadas_es_codigo_2(tmp_path, entorno_local):
    api = ApiFalsa()
    api.desplegado = False
    codigo, datos, _ = correr(api, tmp_path)
    assert codigo == 2
    assert "BE-3.3 sin desplegar" in detalle(datos, "P3") and datos["comprobaciones"] == []


def test_sin_stats_desplegado_es_codigo_2_solo_con_c5(tmp_path, entorno_local):
    api = ApiFalsa()
    api.stats_desplegado = False
    codigo, datos, _ = correr(api, tmp_path)
    assert codigo == 2 and "BE-2.3 sin desplegar" in detalle(datos, "P4")
    codigo, _, _ = correr(api, tmp_path, "--solo", "C1,C2,C3,C4")
    assert codigo == 0


def test_en_dev_sin_be_2_3_hecho_es_codigo_2(tmp_path, entorno_dev):
    entorno_dev.write_text(PLAN.replace("| BE-2.3 | 2 | Hecho |", "| BE-2.3 | 2 | En curso |"), encoding="utf-8")
    codigo, datos, _ = correr(ApiFalsa(), tmp_path, entorno="dev", plan=entorno_dev)
    assert codigo == 2 and "BE-2.3 no está «Hecho»" in detalle(datos, "P4")


def test_credenciales_malas_son_codigo_3(tmp_path, entorno_local, monkeypatch, capsys):
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", "otra-contraseña-123")
    codigo, datos, _ = correr(ApiFalsa(), tmp_path)
    assert codigo == 3 and "401" in detalle(datos, "P3")
    salida = capsys.readouterr().out
    assert "[LIMPIEZA] nada que limpiar (no se llegó a iniciar sesión)" in salida
    assert "otra-contraseña-123" not in salida


def test_local_sin_url_es_codigo_3(tmp_path, monkeypatch):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    codigo, datos, _ = correr(ApiFalsa(), tmp_path)
    assert codigo == 3 and "VALIDACION_API_URL" in detalle(datos, "P2")


def test_aplicar_como_la_app():
    cache: dict[str, dict] = {}
    validate33.aplicar(
        cache, {"completo": True, "alertas": [{"id": "a", "activa": True, "version": 1}], "eliminadas": []}
    )
    diferencia = {
        "completo": False,
        "alertas": [{"id": "a", "activa": False, "version": 2}, {"id": "b", "activa": True, "version": 1}],
        "eliminadas": ["c"],
    }
    validate33.aplicar(cache, diferencia)
    assert validate33.versiones(cache.values()) == {"b": 1}
    validate33.aplicar(cache, {"completo": False, "alertas": [], "eliminadas": ["b"]})
    assert cache == {}


def test_incluida_y_fecha():
    assert validate33.incluida(None, "C5") and validate33.incluida("C1", "C1c") and not validate33.incluida("C1", "C5")
    assert validate33.fecha(datetime(2026, 10, 28, 10, 0, 0, 900, tzinfo=UTC)) == "2026-10-28T10:00:00Z"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", validate33.fecha(datetime.now(UTC)))


# --- Con base: contra el backend real ----------------------------------------------------------------------------
CLAVE = base64.b64encode(b"clave-de-pruebas-de-validate33".ljust(64, b"z")).decode()


class Http:
    """`request()`/`close()` sobre un `TestClient` ya abierto; `close()` no lo cierra (lo cierra la fixture)."""

    def __init__(self, cliente) -> None:
        self.cliente = cliente

    def request(self, metodo: str, url: str, **kwargs: Any) -> Any:
        return self.cliente.request(metodo, url, **kwargs)

    def close(self) -> None:
        pass


@pytest.fixture
def http_real(base_migrada):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.main import crear_app

    with TestClient(crear_app(base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)}))) as cliente:
        yield Http(cliente)


def vivas_en_base(http: Http) -> list[dict]:
    r = http.cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
    token = r.json()["token"]
    return http.cliente.get("/v1/admin/alerts", headers={"Authorization": f"Bearer {token}"}).json()["items"]


@pytest.mark.base
def test_backend_real_local_pasa_entero(http_real, tmp_path, entorno_local, capsys):
    codigo, datos, _ = correr(http_real, tmp_path)
    assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    assert set(estados(datos).values()) == {"pasa"} and len(datos["comprobaciones"]) == len(COMPROBACIONES)
    assert "[LIMPIEZA] alertas de prueba borradas: 4" in capsys.readouterr().out
    assert vivas_en_base(http_real) == []


@pytest.mark.base
def test_backend_real_dev_dos_veces_y_con_restos(http_real, tmp_path, entorno_dev, capsys):
    for sello in ("20261026-150000", "20261026-150001"):
        codigo, datos, _ = correr(http_real, tmp_path, "--sin-limpieza", entorno="dev", sello=sello, plan=entorno_dev)
        assert codigo == 0, json.dumps(datos, ensure_ascii=False, indent=1)
    assert "[PREPARACION] alertas validacion- borradas: 4" in capsys.readouterr().out  # las de la primera
    assert len(vivas_en_base(http_real)) == 4
    codigo, _, _ = correr(http_real, tmp_path, "--solo", "C2", entorno="dev", plan=entorno_dev)
    assert codigo == 0 and vivas_en_base(http_real) == []


@pytest.mark.base
def test_backend_real_que_no_manda_eliminadas_falla_c1c(http_real, tmp_path, entorno_local, monkeypatch):
    from app.servicios import alertas

    original = alertas.foto

    async def sin_eliminadas(motor, **kwargs):
        respuesta = await original(motor, **kwargs)
        return respuesta.model_copy(update={"eliminadas": []})

    monkeypatch.setattr(alertas, "foto", sin_eliminadas)
    codigo, datos, _ = correr(http_real, tmp_path, "--solo", "C1")
    assert codigo == 1 and estados(datos)["C1c"] == "falla" and estados(datos)["C1b"] == "pasa"
    assert vivas_en_base(http_real) == []
