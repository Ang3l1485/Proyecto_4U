"""`validate51.py` contra un mundo falso (sin AWS ni base): la recolección de §5.4 (con un `worker` que procesa al
subir), `GET`/`DELETE` de videos, `POST /v1/localize/frame` con el contrato de §5.3 (similitud 0,999 con la foto
idéntica, 0,3 con las demás; solo cuentan las imágenes del radio) y `eventos_localizacion`. Interruptores de backend
defectuoso: `sin_radio` (C2), `ignora_radio_m` (C3), `acepta_todo` (C4), `sin_evento` y `evento_de_error` (C5),
`lento` (C6), `no_encuentra` (C1), `desplegado` (P3 → 2)."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

import comun
import validate51
from app.dominio import geo

PASSWORD = "contraseña-de-prueba"
INICIO = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)  # 15:00 en Bogotá
SELLO = "20261028-200000"


def _error(estado: int, codigo: str, detalle: Any = None) -> httpx.Response:
    return httpx.Response(estado, json={"error": {"codigo": codigo, "mensaje": "…", "detalle": detalle}})


class Mundo:
    def __init__(self) -> None:
        self.ahora = INICIO
        self.videos: dict[str, dict[str, Any]] = {}
        self.imagenes: dict[str, dict[str, Any]] = {}
        self.s3: dict[str, bytes] = {}
        self.vectores: set[str] = set()
        self.eventos: list[tuple[str, str, int, int, str | None]] = []
        self.peticiones_frame = 0
        self.sin_radio = self.ignora_radio_m = self.acepta_todo = self.sin_evento = self.evento_de_error = False
        self.lento = self.no_encuentra = False
        self.desplegado = True

    def dormir(self, segundos: float) -> None:
        self.ahora += timedelta(seconds=segundos)

    # -- POST /v1/localize/frame (§5.3) ------------------------------------------------------------------------------
    def _frame(self, files: list[Any]) -> httpx.Response:
        if not self.desplegado:
            return _error(501, "NO_IMPLEMENTADO")
        self.peticiones_frame += 1
        fotos = [datos for nombre, datos in files if nombre == "foto"]
        metas = [datos for nombre, datos in files if nombre == "metadatos"]
        if not fotos:
            return _error(400, "FOTOS_INVALIDAS", {"indice": 0, "motivo": "falta la parte foto"})
        if len(fotos) > 1:
            return _error(400, "FOTOS_INVALIDAS", {"indice": 1, "motivo": "solo se admite una parte foto"})
        _archivo, foto, tipo = fotos[0]
        if tipo != "image/jpeg":
            return _error(400, "FOTOS_INVALIDAS", {"indice": 0, "motivo": f"tipo {tipo}: se espera image/jpeg"})
        if not metas:
            return _error(422, "VALIDACION", {"campos": [{"campo": "metadatos", "motivo": "Falta."}]})
        m = json.loads(metas[0][1])
        campos = []
        previa = m.get("posicion_previa")
        if not self.acepta_todo:
            if "rumbo" not in m or (m["rumbo"] is not None and not 0 <= m["rumbo"] < 360):
                campos.append("metadatos.rumbo")
            if not isinstance(previa, dict):
                campos.append("metadatos.posicion_previa")
            elif not -90 <= previa.get("lat", 999) <= 90:
                campos.append("metadatos.posicion_previa.lat")
            if m.get("radio_m") is not None and not 10 <= m["radio_m"] <= 100:
                campos.append("metadatos.radio_m")
        if campos:
            return _error(422, "VALIDACION", {"campos": [{"campo": c, "motivo": "…"} for c in campos]})
        radio = 40.0 if self.ignora_radio_m or m.get("radio_m") is None else float(m["radio_m"])
        lat0, lng0 = float(previa["lat"]), float(previa["lng"])
        en_radio = [
            i for i in self.imagenes.values()
            if i["id"] in self.vectores and (self.sin_radio or geo.distancia_m(lat0, lng0, i["lat"], i["lng"]) <= radio)
        ]  # fmt: skip
        coincidencias = [i for i in en_radio if self.s3.get(i["clave"]) == foto and not self.no_encuentra]
        cuerpo: dict[str, Any] = {
            "resultado": "sin_coincidencias", "posicion": None, "confianza": 0.0, "nivel": None,
            "distancia_previa_m": None, "radio_busqueda_m": radio, "imagenes_en_radio": len(en_radio),
            "lugar_cercano": None, "referencias": [], "version_vector": "dinov2-vits14/pp-v1",
            "latencia_ms": 1500 if self.lento else 240,
        }  # fmt: skip
        if coincidencias:
            lat = sum(i["lat"] for i in coincidencias) / len(coincidencias)
            lng = sum(i["lng"] for i in coincidencias) / len(coincidencias)
            distancia = round(geo.distancia_m(lat0, lng0, lat, lng), 1)
            cuerpo |= {
                "resultado": "ok", "posicion": {"lat": round(lat, 6), "lng": round(lng, 6), "radio_m": 5.0},
                "confianza": 1.0, "nivel": "alta", "distancia_previa_m": distancia,
            }  # fmt: skip
        if not self.sin_evento:
            ok = cuerpo["resultado"] == "ok"
            self.eventos.append(("frame", cuerpo["resultado"], 1, 1 if ok else 0, m.get("app_version")))
        return httpx.Response(200, json=cuerpo)

    # -- API -------------------------------------------------------------------------------------------------------
    def _resumen(self, video: dict[str, Any]) -> dict[str, Any]:
        return {"id": video["id"], "nombre": video["nombre"], "ref_cliente": video["nombre"], "estado": video["estado"]}

    def request(self, metodo: str, url: str, **kwargs: Any) -> httpx.Response:
        partes = urlsplit(url)
        if partes.netloc == "s3.falso":
            clave = partes.path.lstrip("/")
            self.s3[clave] = kwargs["content"]
            imagen = self.imagenes[clave.rsplit("/", 1)[-1].removesuffix(".jpg")]
            imagen["estado"] = "procesada"  # el worker procesa enseguida
            self.vectores.add(imagen["id"])
            return httpx.Response(200)
        ruta, cuerpo = partes.path.removeprefix("/v1"), kwargs.get("json")
        trozos = ruta.strip("/").split("/")
        if ruta == "/health/ready":
            return httpx.Response(200, json={"estado": "ok", "db": "ok", "embedding": "ok"})
        if ruta == "/auth/login":
            if (cuerpo or {}).get("password") != PASSWORD:
                return _error(401, "CREDENCIALES_INVALIDAS")
            return httpx.Response(200, json={"token": "tok", "usuario": {"id": str(uuid.uuid4()), "rol": "admin"}})
        if ruta == "/localize/frame":
            return self._frame(kwargs.get("files") or [])
        if ruta == "/collect/videos":
            video_id = str(uuid.uuid4())
            self.videos[video_id] = {"id": video_id, "nombre": cuerpo["nombre"], "estado": "pendiente"}
            return httpx.Response(201, json=self._resumen(self.videos[video_id]))
        if trozos[:2] == ["collect", "videos"] and trozos[-1] == "images":
            video_id, salida = trozos[2], []
            for elemento in cuerpo["imagenes"]:
                imagen = next(
                    (
                        i
                        for i in self.imagenes.values()
                        if i["video_id"] == video_id and i["orden"] == elemento["orden"]
                    ),
                    None,
                ) or {
                    "id": str(uuid.uuid4()),
                    "video_id": video_id,
                    "orden": elemento["orden"],
                    "estado": "pendiente_subida",
                }
                imagen |= {"lat": elemento["lat"], "lng": elemento["lng"]}
                imagen["clave"] = f"dataset/{video_id}/{imagen['id']}.jpg"
                self.imagenes[imagen["id"]] = imagen
                subida = {"metodo": "PUT", "url": f"https://s3.falso/{imagen['clave']}",
                          "encabezados": {"Content-Type": "image/jpeg"}, "expira_en": "…"}  # fmt: skip
                salida.append(
                    {"orden": imagen["orden"], "id": imagen["id"], "estado": imagen["estado"], "subida": subida}
                )
            return httpx.Response(200, json={"imagenes": salida})
        if trozos[:2] == ["collect", "videos"] and trozos[-1] == "complete":
            return httpx.Response(200, json={"id": trozos[2], "estado": "procesado", "conteo": {}})
        if ruta == "/admin/videos":
            vivos = [self._resumen(v) for v in self.videos.values() if v["estado"] != "eliminado"]
            return httpx.Response(200, json={"items": vivos, "total": len(vivos), "pagina": 1, "por_pagina": 100})
        if trozos[:2] == ["admin", "videos"] and len(trozos) == 3:
            video = self.videos.get(trozos[2])
            if video is None or (video["estado"] == "eliminado" and metodo == "GET"):
                return _error(404, "NO_ENCONTRADO")
            if metodo == "DELETE":
                video["estado"] = "eliminado"
                self.vectores -= {i for i, f in self.imagenes.items() if f["video_id"] == video["id"]}
                return httpx.Response(202, json={"id": video["id"], "estado": "eliminado", "fotos_retiradas": 4,
                                                 "purga": "programada"})  # fmt: skip
            fotos = [{"orden": i["orden"], "estado": i["estado"]} for i in self.imagenes.values()
                     if i["video_id"] == video["id"]]  # fmt: skip
            return httpx.Response(200, json=self._resumen(video) | {"fotos": fotos})
        return _error(404, "NO_ENCONTRADO")

    def close(self) -> None:
        pass


class EmbFalso:
    def __init__(self) -> None:
        self.latidos = 0

    def servicio(self, nombre: str) -> dict[str, Any]:
        return {"desiredCount": 1, "runningCount": 1}

    def latido(self) -> None:
        self.latidos += 1

    def apagar(self) -> None:
        raise AssertionError("no debe apagar un embedding que ya estaba encendido")


class BackendFalso:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo

    def imagen(self, familia: str) -> tuple[str, str]:
        return f"arn:aws:ecs:us-east-1:1:task-definition/{familia}:3", "postgres:17-alpine"

    def sql(self, consulta: str) -> list[str]:
        app_version = consulta.split("app_version = '")[1].split("'")[0]
        filas = [e for e in self.mundo.eventos if e[4] == app_version]
        if self.mundo.evento_de_error:
            filas.append(("frame", "ok", 1, 1, app_version))
        return [f"{o}|{r}|{u}|{c}" for o, r, u, c, _ in filas]


class ContextoFalso(validate51.Contexto):
    def __init__(self, mundo: Mundo) -> None:
        super().__init__("dev")
        self.mundo = mundo
        self.http = self.http_s3 = mundo
        self.dormir = mundo.dormir
        self.ahora = lambda: mundo.ahora
        self.sello = SELLO
        self._outputs = {"api_base_url": "https://api.falsa"}

    def preparar(self, url: str) -> None:
        self.api = comun.ClienteApi(url, http=self.http, dormir=lambda s: None)
        self.backend = BackendFalso(self.mundo)


@pytest.fixture
def mundo(monkeypatch) -> Mundo:
    m = Mundo()

    class Sesion:
        def client(self, nombre: str) -> object:
            return object()

    monkeypatch.setattr(comun, "sesion_aws", lambda: Sesion())
    monkeypatch.setattr(comun, "verificar_cuenta", lambda sesion: "arn:aws:iam::1:user/prueba")
    monkeypatch.setattr(comun, "EmbeddingDev", lambda *a, **k: EmbFalso())
    monkeypatch.setattr(comun, "red_tareas", lambda outputs: {})
    monkeypatch.setattr(comun, "credenciales_admin", lambda entorno, sesion=None: ("admin@campus.edu.co", PASSWORD))
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    return m


def _correr(mundo: Mundo, tmp_path, *argumentos: str) -> tuple[int, dict[str, Any]]:
    informe = tmp_path / "informe.json"
    codigo = validate51.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ContextoFalso(mundo))
    return codigo, json.loads(informe.read_text(encoding="utf-8"))


def _estados(informe: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["comprobaciones"]}


def test_camino_feliz(mundo, tmp_path, capsys):
    codigo, informe = _correr(mundo, tmp_path)
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert _estados(informe) == {c: "pasa" for c in ("C4", "C1", "C2", "C3", "C6", "C5")}
    assert all(v["estado"] == "eliminado" for v in mundo.videos.values())  # la limpieza borra el video
    assert [e[1] for e in mundo.eventos] == ["ok", "sin_coincidencias", "sin_coincidencias", "ok"]
    assert all(e[4] == f"validacion-51-{SELLO}" for e in mundo.eventos)
    assert "s3.falso" not in salida and "tok" not in salida.split()


@pytest.mark.parametrize(
    ("interruptor", "falla"),
    [
        ("sin_radio", "C2"),
        ("ignora_radio_m", "C3"),
        ("acepta_todo", "C4"),
        ("sin_evento", "C5"),
        ("evento_de_error", "C5"),
        ("lento", "C6"),
        ("no_encuentra", "C1"),
    ],
)
def test_backends_defectuosos(mundo, tmp_path, interruptor, falla):
    setattr(mundo, interruptor, True)
    codigo, informe = _correr(mundo, tmp_path)
    assert codigo == 1
    assert _estados(informe)[falla] == "falla"


def test_sin_desplegar_es_codigo_2_sin_crear_nada(mundo, tmp_path):
    mundo.desplegado = False
    codigo, _ = _correr(mundo, tmp_path)
    assert codigo == 2 and mundo.videos == {}


def test_contrasena_mala_es_codigo_3(mundo, tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "credenciales_admin", lambda entorno, sesion=None: ("admin@campus.edu.co", "mala"))
    codigo, _ = _correr(mundo, tmp_path)
    assert codigo == 3


def test_despues_de_las_21_es_codigo_3(mundo, tmp_path):
    mundo.ahora = INICIO + timedelta(hours=6, minutes=30)  # 21:30 en Bogotá
    codigo, _ = _correr(mundo, tmp_path)
    assert codigo == 3


def test_solo_c4_no_crea_datos(mundo, tmp_path):
    codigo, informe = _correr(mundo, tmp_path, "--solo", "C4")
    assert codigo == 0 and _estados(informe)["C4"] == "pasa" and mundo.videos == {}
    assert mundo.eventos == []  # las peticiones mal formadas no dejan evento


def test_solo_c5_hace_antes_la_peticion_de_c1(mundo, tmp_path):
    codigo, informe = _correr(mundo, tmp_path, "--solo", "C5")
    assert codigo == 0 and _estados(informe)["C5"] == "pasa" and len(mundo.eventos) == 1


def test_la_preparacion_borra_solo_los_restos_51(mundo, tmp_path):
    for nombre in ("validacion-51-20261027-100000", "validacion-41-20261027-100000", "Recorrido real del campus"):
        mundo.videos[nombre] = {"id": nombre, "nombre": nombre, "estado": "procesado"}
    codigo, _ = _correr(mundo, tmp_path, "--solo", "C4")
    assert codigo == 0
    assert mundo.videos["validacion-51-20261027-100000"]["estado"] == "eliminado"
    assert mundo.videos["validacion-41-20261027-100000"]["estado"] == "procesado"
    assert mundo.videos["Recorrido real del campus"]["estado"] == "procesado"


def test_haversine_es_la_del_backend():
    assert validate51.RADIO_TIERRA_M == geo.RADIO_TIERRA_M
    for puntos in [(2.0, -101.0, 2.0027, -101.0001), (6.2001, -75.5786, 6.2, -75.5787), (0, 0, 0, 0)]:
        assert validate51.haversine_m(*puntos) == pytest.approx(geo.distancia_m(*puntos), abs=1e-9)


def test_desplazar_y_los_puntos_de_prueba():
    ctx = validate51.Contexto()
    ctx.sello = SELLO
    a, b = ctx.punto_a(), ctx.punto_b()
    assert geo.distancia_m(*a, *b) == pytest.approx(validate51.DISTANCIA_B_M, abs=0.05)
    este = validate51.desplazar(*a, este_m=15)
    assert geo.distancia_m(*a, *este) == pytest.approx(15, abs=0.01)
    assert not math.isclose(a[1], -100.0)  # lejos de los datos de validate41 (1.x, −100)
    assert ctx.app_version == f"validacion-51-{SELLO}" and len(ctx.app_version) <= 40
