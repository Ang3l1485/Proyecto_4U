"""Validador de BE-2.3 con AWS, HTTP, S3, SQS, el `worker` y la API simulados (validation-2-3.md).

Reutiliza el mundo falso de `test_validate22.py` (API de §5.4/§5.5, `/v1/health/ready`, S3 con eventos a `ingesta`, ECS
de `embedding` y `worker` con retraso, escalado, CloudWatch, Cloud Map y un `worker` que procesa las fotos) y le añade:
`creado_en` en los videos, `GET /v1/admin/stats` (con totales previos de «datos reales»), los lugares de
`/v1/admin/places` y una foto ajena en `ingesta`. Interruptores para simular un backend defectuoso. El reloj es falso.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("botocore")

import comun
import validate23

_ruta = Path(__file__).with_name("test_validate22.py")
_spec = importlib.util.spec_from_file_location("falsos_validate22", _ruta)
t22 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t22)

PLAN = (
    "| BE-2.2 | 2 | Hecho | [2-2](x) | `3b01b68` |\n| BE-2.3 | 2 | En curso | [2-3](x) | — |\n"
    "| BE-3.1 | 3 | Hecho | [3-1](x) | `86fc024` |\n"
)


class Mundo(t22.Mundo):
    """`dev` con datos previos: 40 fotos procesadas, 5 lugares, 1 alerta activa y un video real (número 7)."""

    def __init__(self, embedding_encendido: bool = False, hora_bogota: int = 15) -> None:
        super().__init__(embedding_encendido=embedding_encendido, hora_bogota=hora_bogota)
        self.numero = 7
        self.fotos_base = 40
        self.alertas = 1
        self.lugares: dict[str, str] = {f"l{i}": f"Bloque {i}" for i in range(5)}  # id → nombre
        self.ultimo_base = {"numero": 7, "creado_en": "2026-10-20T14:00:00Z"}
        self.lecturas_stats = 0
        # interruptores de un backend defectuoso
        self.desplegado = True
        self.cuenta_pendientes = False  # total_fotos cuenta todas las fotos, no solo las procesada
        self.lugares_fijos = False  # total_lugares no cambia
        self.ultimo_viejo = False  # ultimo_video devuelve el video real anterior
        self.fecha_con_fracciones = False  # creado_en con milisegundos
        self.campo_de_mas = False

    # -- videos con creado_en ----------------------------------------------------------------------------------------
    def nuevo_video(self, nombre: str, ref: str) -> dict[str, Any]:
        video = super().nuevo_video(nombre, ref)
        video["creado_en"] = self.t.strftime("%Y-%m-%dT%H:%M:%SZ")
        return video

    def _resumen(self, video: dict[str, Any]) -> dict[str, Any]:
        return super()._resumen(video) | {"creado_en": video["creado_en"]}

    # -- API ----------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, headers: dict | None = None, json: Any = None, params=None, **resto):
        ruta = url.split("/v1", 1)[1]
        autorizado = (headers or {}).get("Authorization") == f"Bearer {t22.TOKEN}"
        if ruta == "/admin/stats" and metodo == "GET":
            if not self.desplegado:
                return t22._error(404, "NO_ENCONTRADO")
            return self._stats() if autorizado else t22._error(401, "NO_AUTENTICADO")
        if ruta.startswith("/admin/places") and autorizado:
            return self._lugares(metodo, ruta, json, params or {})
        return super().request(metodo, url, headers=headers, json=json, params=params, **resto)

    def _stats(self) -> t22.Respuesta:
        self.lecturas_stats += 1
        fotos = [f for v in self.videos.values() for f in v["fotos"].values()]
        propias = len(fotos) if self.cuenta_pendientes else sum(f["estado"] == "procesada" for f in fotos)
        ultimo = self.ultimo_base
        if self.videos and not self.ultimo_viejo:
            video = max(self.videos.values(), key=lambda v: (v["creado_en"], v["numero"]))
            ultimo = {"numero": video["numero"], "creado_en": video["creado_en"]}
        if self.fecha_con_fracciones:
            ultimo = ultimo | {"creado_en": ultimo["creado_en"].replace("Z", ".123Z")}
        cuerpo = {
            "total_fotos": self.fotos_base + propias,
            "total_lugares": 5 if self.lugares_fijos else len(self.lugares),
            "alertas_activas": self.alertas,
            "ultimo_video": ultimo,
        }
        if self.campo_de_mas:
            cuerpo["fotos_pendientes"] = 0
        return t22.Respuesta(200, cuerpo)

    def _lugares(self, metodo: str, ruta: str, cuerpo: Any, params: dict) -> t22.Respuesta:
        partes = ruta.strip("/").split("/")
        if metodo == "GET" and len(partes) == 2:
            q = params.get("q", "")
            items = [{"id": i, "nombre": n} for i, n in self.lugares.items() if q in comun.normalizar_nombre(n)]
            return t22.Respuesta(200, {"items": items, "total": len(items)})
        if metodo == "POST" and len(partes) == 2:
            lugar_id = str(uuid.uuid4())
            self.lugares[lugar_id] = cuerpo["nombre"]
            return t22.Respuesta(201, {"id": lugar_id, "nombre": cuerpo["nombre"]})
        if metodo == "DELETE" and len(partes) == 3:
            self.lugares.pop(partes[2], None)
            return t22.Respuesta(204)
        return t22._error(404, "NO_ENCONTRADO")

    # -- una foto ajena que el worker procesa si encuentra su mensaje en `ingesta` -----------------------------------
    def foto_ajena_en_cola(self) -> None:
        ajeno = self.nuevo_video("Entrada norte", "rec_0003")
        ajeno["creado_en"] = "2026-10-19T10:00:00Z"
        imagen_id = str(uuid.uuid4())
        clave = f"dataset/{ajeno['id']}/{imagen_id}.jpg"
        ajeno["fotos"][1] = {"id": imagen_id, "estado": "subida", "clave": clave}
        self.put(clave, b"\xff\xd8\xff" + b"ajena")


Sesion = t22.Sesion


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    for variable in ("VALIDACION_API_URL", "VALIDACION_ADMIN_CORREO", "VALIDACION_ADMIN_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: t22.OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")
    plan = tmp_path / "PLAN.md"
    plan.write_text(PLAN, encoding="utf-8")
    monkeypatch.setattr(validate23, "PLAN_BACKEND", plan)

    def correr(mundo: Mundo, *argumentos: str):
        sesion = Sesion(mundo)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate23.Contexto("dev")
        ctx.http, ctx.http_s3 = mundo, t22.HttpS3(mundo)
        ctx.dormir, ctx.ahora = mundo.dormir, mundo.ahora
        ctx.sello = "20261026-150000"
        informe = tmp_path / "informe.json"
        codigo = validate23.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8")), ctx

    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def _detalle(informe: dict, id_: str) -> str:
    return next(c["detalle"] for c in informe["precondiciones"] + informe["comprobaciones"] if c["id"] == id_)


def _comandos(sesion: Sesion) -> list[str]:
    return [p["overrides"]["containerOverrides"][0]["command"][3] for p in sesion.ecs.lanzadas]


ORDEN = ["P1", "P2", "P3", "P4", "P5", "C1a", "C1b", "C1c"]


def test_dev_completo_con_embedding_apagado_lo_enciende_y_lo_apaga(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=False)
    codigo, sesion, informe, _ = entorno_dev(mundo)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert list(_estados(informe)) == ORDEN and set(_estados(informe).values()) == {"pasa"}
    texto = salida.out + salida.err + json.dumps(informe)
    for secreto in (t22.FIRMA, t22.TOKEN, "s3.amazonaws.com"):
        assert secreto not in texto
    assert "embedding encendido en" in _detalle(informe, "P5")
    assert "total_fotos s0 = 40 · con 2 fotos registradas sin subir, igual" in _detalle(informe, "C1a")
    assert "s1 = 42 (+2)" in _detalle(informe, "C1a")
    assert "total_lugares 5 → 7 (+2, lugares a y b) → 6 (−1, b borrado)" in _detalle(informe, "C1b")
    assert "ultimo_video = numero 8, creado_en 2026-10-" in _detalle(informe, "C1c")
    assert "alertas_activas = 1" in _detalle(informe, "C1c")
    assert "[PREPARACION] sin restos validacion- de ejecuciones anteriores · sin lugares validacion-" in salida.out
    # limpieza: embedding apagado, video borrado con limpiar-validacion y lugar a borrado
    assert mundo.cambios_embedding == [1, 0] and mundo.rangos == {"embedding": (0, 0), "worker": (0, 0)}
    assert mundo.videos == {} and len(mundo.lugares) == 5
    assert _comandos(sesion) == ["limpiar-validacion"]
    assert "embedding apagado (lo encendió el validador)" in salida.out
    assert "lugares de prueba borrados: 1" in salida.out


def test_con_embedding_encendido_lo_deja_encendido(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=True)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 0, capsys.readouterr().out
    assert "ya encendido (latido publicado)" in _detalle(informe, "P5")
    assert mundo.cambios_embedding == [] and mundo.deseado["embedding"] == 1
    assert "embedding sigue encendido (como estaba)" in capsys.readouterr().out


def test_espera_a_que_ingesta_se_vacie_antes_de_leer_s0(entorno_dev):
    """Una foto ajena en `ingesta` subiría `total_fotos` de más si se procesara entre s0 y s1: C1a espera a que el
    `worker` vacíe la cola y lee s0 después (la foto ajena ya cuenta en s0)."""
    mundo = Mundo(embedding_encendido=True)
    mundo.foto_ajena_en_cola()
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 0, informe
    assert "ingesta vacía tras" in _detalle(informe, "C1a")
    assert "total_fotos s0 = 41" in _detalle(informe, "C1a") and "s1 = 43 (+2)" in _detalle(informe, "C1a")


def test_ingesta_que_no_se_vacia_falla_c1a_y_limpia(entorno_dev, monkeypatch):
    mundo = Mundo(embedding_encendido=True)
    monkeypatch.setattr(comun, "mensajes_cola", lambda sqs, url: (3, 1))
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 1 and _estados(informe)["C1a"] == "falla"
    assert "ingesta sigue con 3 visibles y 1 en vuelo tras 15 min" in _detalle(informe, "C1a")
    assert _estados(informe)["C1b"] == "pasa" and _estados(informe)["C1c"] == "pasa"
    assert mundo.videos == {} and len(mundo.lugares) == 5


@pytest.mark.parametrize(
    ("interruptor", "id_", "texto"),
    [
        ("cuenta_pendientes", "C1a", "con 2 fotos pendiente_subida, total_fotos pasó de 40 a 42"),
        ("lugares_fijos", "C1b", "total_lugares 5 → 5 al crear 2 lugares, se esperaba +2"),
        ("ultimo_viejo", "C1c", "se esperaba el del video de prueba"),
        ("fecha_con_fracciones", "C1c", "se esperaba UTC con Z y sin fracciones"),
        ("campo_de_mas", "C1a", "GET /v1/admin/stats (s0): campos ["),
    ],
)
def test_un_backend_defectuoso_falla_su_comprobacion(entorno_dev, interruptor, id_, texto):
    mundo = Mundo(embedding_encendido=True)
    setattr(mundo, interruptor, True)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 1
    assert _estados(informe)[id_] == "falla", informe
    assert texto in _detalle(informe, id_)
    assert mundo.videos == {} and len(mundo.lugares) == 5  # la limpieza borra igual


def test_sin_el_endpoint_desplegado_es_codigo_2_sin_encender_nada(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    mundo.desplegado = False
    codigo, sesion, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "BE-2.3 sin desplegar" in _detalle(informe, "P3")
    assert mundo.cambios_embedding == [] and mundo.videos == {} and sesion.ecs.lanzadas == []


@pytest.mark.parametrize("lote", ["BE-2.2", "BE-3.1"])
def test_sin_un_lote_hecho_es_codigo_2(entorno_dev, tmp_path, lote):
    texto = PLAN.replace(f"| {lote} | 2 | Hecho |", f"| {lote} | 2 | En curso |")
    texto = texto.replace(f"| {lote} | 3 | Hecho |", f"| {lote} | 3 | En curso |")
    (tmp_path / "PLAN.md").write_text(texto, encoding="utf-8")
    codigo, _, informe, _ = entorno_dev(Mundo())
    assert codigo == 2 and f"{lote} no está «Hecho»" in _detalle(informe, "P2")


def test_fuera_de_horario_es_codigo_3_salvo_sin_c1a(entorno_dev):
    mundo = Mundo(embedding_encendido=False, hora_bogota=21)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3 and "antes de las 21:00" in _detalle(informe, "P2")
    assert mundo.cambios_embedding == []
    # C1b y C1c no necesitan embedding: se pueden correr a cualquier hora y sin P5
    codigo, _, informe, _ = entorno_dev(Mundo(embedding_encendido=False, hora_bogota=21), "--solo", "C1b,C1c")
    assert codigo == 0, informe
    assert "P5" not in _estados(informe) and _estados(informe)["C1a"] == "omitida"


def test_solo_c1c_crea_el_video_sin_fotos_ni_embedding(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    codigo, sesion, informe, _ = entorno_dev(mundo, "--solo", "C1c")
    assert codigo == 0, informe
    assert mundo.cambios_embedding == [] and mundo.videos == {}
    assert _comandos(sesion) == ["limpiar-validacion"]
    assert "ultimo_video = numero 8" in _detalle(informe, "C1c")


def test_restos_de_una_ejecucion_anterior_se_borran_al_empezar(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=True)
    mundo.nuevo_video("validacion-23-20261025-100000", "validacion-23-20261025-100000")
    mundo.lugares["viejo"] = "validacion-23-20261025-100000 a"
    codigo, sesion, _, _ = entorno_dev(mundo, "--solo", "C1b")
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "restos borrados:" in salida and "lugares validacion- borrados: 1" in salida
    assert _comandos(sesion) == ["limpiar-validacion"]  # la preparación; C1b no crea videos
    assert "viejo" not in mundo.lugares and len(mundo.lugares) == 5


class _HttpFijo:
    def __init__(self, estado: int, cuerpo: Any) -> None:
        self.respuesta = t22.Respuesta(estado, cuerpo)

    def request(self, metodo: str, url: str, **_: Any) -> t22.Respuesta:
        assert (metodo, url) == ("GET", "https://x/v1/admin/stats")
        return self.respuesta

    def close(self) -> None:
        pass


BUENO = {"total_fotos": 3, "total_lugares": 0, "alertas_activas": 0, "ultimo_video": None}


@pytest.mark.parametrize(
    ("estado", "cuerpo", "texto"),
    [
        (404, {"error": {"codigo": "NO_ENCONTRADO", "mensaje": "…", "detalle": None}}, "404 NO_ENCONTRADO"),
        (200, BUENO | {"fotos_pendientes": 0}, "campos ["),
        (200, {k: v for k, v in BUENO.items() if k != "ultimo_video"}, "campos ["),
        (200, BUENO | {"total_fotos": -1}, "total_fotos = -1"),
        (200, BUENO | {"alertas_activas": True}, "alertas_activas = True"),
        (200, BUENO | {"total_lugares": 2.0}, "total_lugares = 2.0"),
    ],
)
def test_resumen_panel_de_comun_exige_la_forma_de_5_5(estado, cuerpo, texto):
    api = comun.ClienteApi("https://x/v1", http=_HttpFijo(estado, cuerpo))
    with pytest.raises(comun.Falla, match=r"^aquí: ") as error:
        comun.resumen_panel(api, "t", que="aquí")
    assert texto in str(error.value)


def test_resumen_panel_de_comun_devuelve_el_cuerpo():
    api = comun.ClienteApi("https://x/v1", http=_HttpFijo(200, BUENO))
    assert comun.resumen_panel(api, "t") == BUENO
    assert comun.PATRON_FECHA_UTC.match("2026-10-26T15:00:00Z") and not comun.PATRON_FECHA_UTC.match(
        "2026-10-26T15:00:00.123Z"
    )


@pytest.mark.parametrize(
    ("solo", "id_", "esperado"),
    [(None, "C1a", True), ("C1", "C1a", True), ("C1a", "C1a", True), ("C1b,C1c", "C1a", False)],
)
def test_incluida_sigue_la_regla_de_solo(solo, id_, esperado):
    assert validate23.incluida(solo, id_) is esperado
