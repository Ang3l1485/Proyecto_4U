"""`validate41.py` contra un mundo falso (sin AWS ni base): una API de videos e imágenes en memoria con el contrato de
§5.5, S3, la cola `purga`, el `worker` (procesa al subir y purga si está en marcha), el reconciliador (un evento
`purgas_reencoladas` cada 10 min de reloj falso) y la auditoría. Interruptores de backend defectuoso: `no_retira`
(C1b), `no_purga` (C2), `sin_reconciliador` (C3), `sin_auditoria` (C4b), `campo_de_mas` (C5a), `desplegado` (P3)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

import comun
import validate41

PASSWORD = "contraseña-de-prueba"
ADMIN_ID = str(uuid.uuid4())
INICIO = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)  # 15:00 en Bogotá


def _error(estado: int, codigo: str) -> httpx.Response:
    return httpx.Response(estado, json={"error": {"codigo": codigo, "mensaje": "…", "detalle": None}})


class Mundo:
    def __init__(self) -> None:
        self.ahora = INICIO
        self.videos: dict[str, dict[str, Any]] = {}
        self.imagenes: dict[str, dict[str, Any]] = {}
        self.lugares: dict[str, str] = {}
        self.s3: dict[str, bytes] = {}
        self.vectores: set[str] = set()
        self.purga: list[str] = []  # video_ids encolados
        self.auditoria: list[tuple[str, str, str]] = []
        self.eventos: list[dict[str, Any]] = []
        self.worker = 1
        self.suspendido = False
        self.numero = 10
        self.ultimo_reconciliador = INICIO
        self.no_retira = self.no_purga = self.sin_reconciliador = self.sin_auditoria = self.campo_de_mas = False
        self.desplegado = True

    # -- reloj: el worker y el reconciliador avanzan con él ---------------------------------------------------------
    def dormir(self, segundos: float) -> None:
        self.ahora += timedelta(seconds=segundos)
        if self.worker and not self.no_purga:
            for video_id in list(dict.fromkeys(self.purga)):
                for clave in [c for c in self.s3 if f"/{video_id}/" in c]:
                    del self.s3[clave]
                self.videos[video_id]["purgado"] = True
            self.purga.clear()
        if (self.ahora - self.ultimo_reconciliador).total_seconds() >= 600:
            self.ultimo_reconciliador = self.ahora
            pendientes = [
                v for v in self.videos.values()
                if v["estado"] == "eliminado" and not v["purgado"]
                and (self.ahora - v["eliminado_en"]).total_seconds() > 600
            ]  # fmt: skip
            if pendientes and not self.sin_reconciliador:
                self.purga.extend(v["id"] for v in pendientes)
                self.eventos.append({"evento": "purgas_reencoladas", "enviados": len(pendientes), "ts": self.ahora})

    # -- representación --------------------------------------------------------------------------------------------
    def _imagen(self, imagen: dict[str, Any]) -> dict[str, Any]:
        procesada = imagen["estado"] == "procesada"
        return {
            "id": imagen["id"], "video_id": imagen["video_id"], "orden": imagen["orden"], "lat": imagen["lat"],
            "lng": imagen["lng"], "rumbo": None, "capturada_en": "2026-10-20T14:00:01Z", "estado": imagen["estado"],
            "error": None, "calidad": imagen["calidad"], "notas": imagen["notas"],
            "lugar": {"id": imagen["lugar_id"], "nombre": "x"} if imagen["lugar_id"] else None,
            "url": f"https://s3.falso/dataset/{imagen['video_id']}/{imagen['id']}.jpg?X-Amz-Signature=FIRMA",
            "url_miniatura": f"https://s3.falso/thumbs/{imagen['video_id']}/{imagen['id']}.jpg?X-Amz-Signature=FIRMA"
            if procesada else None,
            "url_expira_en": "2026-10-27T21:00:00Z",
        }  # fmt: skip

    def _video(self, video: dict[str, Any], fotos: bool = False) -> dict[str, Any]:
        propias = sorted((i for i in self.imagenes.values() if i["video_id"] == video["id"]), key=lambda i: i["orden"])
        conteo = {e: sum(1 for i in propias if i["estado"] == e) for e in validate41.ESTADOS_IMAGEN}
        cuerpo = {
            "id": video["id"], "numero": video["numero"], "nombre": video["nombre"], "ref_cliente": video["ref"],
            "estado": video["estado"], "creado_en": "2026-10-27T20:00:00Z", "iniciado_en": None, "finalizado_en": None,
            "duracion_s": None, "distancia_m": None, "pasos": None, "inicio": None, "total_fotos": len(propias),
            "conteo": conteo, "creado_por": {"id": ADMIN_ID, "nombre": "Admin"},
        }  # fmt: skip
        if self.campo_de_mas:
            cuerpo["sobra"] = 1
        if fotos:
            cuerpo["fotos"] = [self._imagen(i) for i in propias]
        return cuerpo

    def _viva(self, imagen_id: str) -> dict[str, Any] | None:
        imagen = self.imagenes.get(imagen_id)
        if imagen is None or self.videos[imagen["video_id"]]["estado"] == "eliminado":
            return None
        return imagen

    def _borrar_imagen(self, imagen_id: str) -> bool:
        if self._viva(imagen_id) is None:
            return False
        self.imagenes.pop(imagen_id)
        self.vectores.discard(imagen_id)
        for clave in [c for c in self.s3 if imagen_id in c]:
            if self.worker:
                del self.s3[clave]
        return True

    # -- API -------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, **kwargs: Any) -> httpx.Response:
        partes = urlsplit(url)
        if partes.netloc == "s3.falso":
            clave = partes.path.lstrip("/")
            if metodo == "PUT":
                self.s3[clave] = kwargs["content"]
                imagen = self.imagenes[clave.rsplit("/", 1)[-1].removesuffix(".jpg")]
                imagen["estado"] = "procesada"  # el worker procesa enseguida
                self.vectores.add(imagen["id"])
                self.s3[clave.replace("dataset/", "thumbs/", 1)] = b"miniatura"
                return httpx.Response(200)
            existe = clave in self.s3
            return httpx.Response(200 if existe else 404, headers={"content-type": "image/jpeg"})
        ruta, params, cuerpo = partes.path.removeprefix("/v1"), kwargs.get("params") or {}, kwargs.get("json")
        if ruta == "/health/ready":
            return httpx.Response(200, json={"estado": "ok", "db": "ok", "embedding": "ok"})
        if ruta == "/auth/login":
            if (cuerpo or {}).get("password") != PASSWORD:
                return _error(401, "CREDENCIALES_INVALIDAS")
            return httpx.Response(
                200, json={"token": "tok", "expira_en": "…", "usuario": {"id": ADMIN_ID, "rol": "admin"}}
            )
        trozos = ruta.strip("/").split("/")
        if trozos[:2] == ["admin", "images"] and not self.desplegado:
            return _error(404, "NO_ENCONTRADO")
        if ruta == "/collect/videos":
            video_id = str(uuid.uuid4())
            self.numero += 1
            self.videos[video_id] = {
                "id": video_id, "numero": self.numero, "nombre": cuerpo["nombre"], "ref": cuerpo["ref_cliente"],
                "estado": "pendiente", "purgado": False, "eliminado_en": None,
            }  # fmt: skip
            return httpx.Response(201, json=self._video(self.videos[video_id]))
        if trozos[:2] == ["collect", "videos"] and trozos[-1] == "images":
            video_id, salida = trozos[2], []
            for elemento in cuerpo["imagenes"]:
                existente = next(
                    (
                        i
                        for i in self.imagenes.values()
                        if i["video_id"] == video_id and i["orden"] == elemento["orden"]
                    ),
                    None,
                )
                imagen = existente or {
                    "id": str(uuid.uuid4()), "video_id": video_id, "orden": elemento["orden"], "lat": elemento["lat"],
                    "lng": elemento["lng"], "estado": "pendiente_subida", "calidad": "normal", "notas": None,
                    "lugar_id": None,
                }  # fmt: skip
                self.imagenes[imagen["id"]] = imagen
                subida = {
                    "metodo": "PUT", "url": f"https://s3.falso/dataset/{video_id}/{imagen['id']}.jpg",
                    "encabezados": {"Content-Type": "image/jpeg"}, "expira_en": "2026-10-27T21:00:00Z",
                }  # fmt: skip
                salida.append(
                    {"orden": imagen["orden"], "id": imagen["id"], "estado": imagen["estado"], "subida": subida}
                )
            return httpx.Response(200, json={"imagenes": salida})
        if trozos[:2] == ["collect", "videos"] and trozos[-1] == "complete":
            self.videos[trozos[2]]["estado"] = "procesado"
            return httpx.Response(200, json={"id": trozos[2], "estado": "procesado", "conteo": {}})
        if ruta == "/admin/videos":
            vivos = [self._video(v) for v in self.videos.values() if v["estado"] != "eliminado"]
            vivos = [v for v in vivos if params.get("q", "") in v["nombre"]]
            return httpx.Response(200, json={"items": vivos, "total": len(vivos), "pagina": 1, "por_pagina": 24})
        if trozos[:2] == ["admin", "videos"] and len(trozos) == 3:
            video = self.videos.get(trozos[2])
            if metodo == "DELETE":
                if video is None:
                    return _error(404, "NO_ENCONTRADO")
                if video["estado"] != "eliminado":
                    video["retiradas"] = sum(1 for i in self.imagenes.values() if i["video_id"] == video["id"])
                    video.update(estado="eliminado", eliminado_en=self.ahora)
                    if not self.no_retira:
                        self.vectores -= {i for i, f in self.imagenes.items() if f["video_id"] == video["id"]}
                    self.purga.append(video["id"])
                    self._auditar("video.eliminar", video["id"])
                cuerpo_borrado = {"id": video["id"], "estado": "eliminado", "fotos_retiradas": video["retiradas"]}
                return httpx.Response(202, json={**cuerpo_borrado, "purga": "programada"})
            if video is None or video["estado"] == "eliminado":
                return _error(404, "NO_ENCONTRADO")
            if metodo == "PATCH":
                video["nombre"] = cuerpo["nombre"]
                self._auditar("video.renombrar", video["id"])
            return httpx.Response(200, json=self._video(video, fotos=metodo == "GET"))
        if ruta == "/admin/images":
            items = [
                self._imagen(i) for i in sorted(self.imagenes.values(), key=lambda i: i["orden"])
                if self._viva(i["id"]) and params.get("video_id") in (None, i["video_id"])
            ]  # fmt: skip
            return httpx.Response(200, json={"items": items, "total": len(items), "pagina": 1, "por_pagina": 24})
        if ruta == "/admin/images/lote":
            procesadas, fallidas = 0, []
            for imagen_id in cuerpo["ids"]:
                if cuerpo["accion"] == "eliminar" and self._borrar_imagen(imagen_id):
                    procesadas += 1
                elif cuerpo["accion"] == "reasignar" and self._viva(imagen_id):
                    self.imagenes[imagen_id]["lugar_id"] = cuerpo["lugar_id"]
                    procesadas += 1
                else:
                    fallidas.append({"id": imagen_id, "codigo": "NO_ENCONTRADO"})
            return httpx.Response(200, json={"procesadas": procesadas, "fallidas": fallidas})
        if trozos[:2] == ["admin", "images"]:
            imagen = self._viva(trozos[2])
            if metodo == "DELETE":
                return httpx.Response(204) if self._borrar_imagen(trozos[2]) else _error(404, "NO_ENCONTRADO")
            if imagen is None:
                return _error(404, "NO_ENCONTRADO")
            if trozos[-1] == "reprocesar":
                imagen["estado"] = "subida"
                return httpx.Response(202)
            if metodo == "PATCH":
                imagen.update({k: v for k, v in cuerpo.items() if k in ("lat", "lng", "lugar_id", "calidad", "notas")})
                return httpx.Response(200, json=self._imagen(imagen))
            vector = (
                {"version_vector": "dinov2-vits14/pp-v1", "creado_en": "…"} if imagen["id"] in self.vectores else None
            )
            video = self.videos[imagen["video_id"]]
            referencia = {"id": video["id"], "numero": video["numero"], "nombre": video["nombre"]}
            return httpx.Response(200, json={**self._imagen(imagen), "video": referencia, "vector": vector})
        if ruta == "/admin/diagnostico/vecinos":
            foto = kwargs["files"][0][1][1]
            clave = next((c for c, datos in self.s3.items() if datos == foto), None)
            vecinos = []
            if clave is not None:
                video_id, imagen_id = clave.split("/")[1], clave.split("/")[2].removesuffix(".jpg")
                if imagen_id in self.vectores:
                    vecinos.append({"imagen_id": imagen_id, "video_id": video_id, "similitud": 0.999})
            return httpx.Response(200, json={"version_vector": "dinov2-vits14/pp-v1", "k": 5, "vecinos": vecinos})
        if ruta == "/admin/places":
            if metodo == "POST":
                lugar_id = str(uuid.uuid4())
                self.lugares[lugar_id] = cuerpo["nombre"]
                return httpx.Response(201, json={"id": lugar_id, "nombre": cuerpo["nombre"]})
            items = [{"id": i, "nombre": n} for i, n in self.lugares.items() if n.startswith("validacion-")]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        if trozos[:2] == ["admin", "places"]:
            self.lugares.pop(trozos[2], None)
            return httpx.Response(204)
        return _error(404, "NO_ENCONTRADO")

    def close(self) -> None:
        pass

    def _auditar(self, accion: str, video_id: str) -> None:
        if not self.sin_auditoria:
            self.auditoria.append((accion, video_id, ADMIN_ID))


class EmbFalso:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.latidos = 0

    def servicio(self, nombre: str) -> dict[str, Any]:
        n = 1 if nombre == comun.SERVICIO_EMBEDDING else self.mundo.worker
        return {"desiredCount": n, "runningCount": n}

    def latido(self) -> None:
        self.latidos += 1

    def comprobar_inf21(self) -> str:
        return "INF-2.1 en orden"

    def poner(self, servicio: str, replicas: int) -> None:
        if servicio == comun.SERVICIO_WORKER:
            self.mundo.worker = replicas

    def apagar(self) -> None:
        raise AssertionError("no debe apagar un embedding que ya estaba encendido")


class BackendFalso:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo

    def imagen(self, familia: str) -> tuple[str, str]:
        return "arn", "imagen"

    def revision(self, familia: str) -> str:
        return f"arn:aws:ecs:us-east-1:1:task-definition/{familia}:7"

    def sql(self, consulta: str) -> list[str]:
        video_id = consulta.split("'")[1]
        if "purgado_en" in consulta:
            return ["t" if self.mundo.videos[video_id]["purgado"] else "f"]
        return [f"{a}|{actor}" for a, v, actor in self.mundo.auditoria if v == video_id]


class ContextoFalso(validate41.Contexto):
    def __init__(self, mundo: Mundo) -> None:
        super().__init__("dev")
        self.mundo = mundo
        self.http = self.http_s3 = mundo
        self.dormir = mundo.dormir
        self.ahora = lambda: mundo.ahora
        self.sello = "20261027-200000"
        self._outputs = {
            "bucket_dataset": "b",
            "sqs_purga_url": "q",
            "sqs_purga_dlq_url": "dlq",
            "api_base_url": "https://api.falsa",
        }

    def preparar(self, url: str) -> None:
        self.api = comun.ClienteApi(url, http=self.http, dormir=lambda s: None)
        self.backend = BackendFalso(self.mundo)

    def claves(self, prefijo: str) -> list[str]:
        return [c for c in self.mundo.s3 if c.startswith(prefijo)]

    def mensajes_purga(self) -> int:
        return len(self.mundo.purga)

    def mensajes_dlq(self) -> int:
        return 0

    def eventos_api(self, evento: str, desde: datetime) -> list[dict[str, Any]]:
        return [e for e in self.mundo.eventos if e["evento"] == evento and e["ts"] >= desde]

    def escalado_worker_suspendido(self) -> bool:
        return self.mundo.suspendido

    def suspender_escalado_worker(self, suspender: bool) -> None:
        self.mundo.suspendido = suspender


@pytest.fixture
def mundo(monkeypatch) -> Mundo:
    m = Mundo()

    class Sesion:
        def client(self, nombre: str) -> object:
            return object()

    monkeypatch.setattr(comun, "sesion_aws", lambda: Sesion())
    monkeypatch.setattr(comun, "verificar_cuenta", lambda sesion: "arn:aws:iam::1:user/prueba")
    monkeypatch.setattr(comun, "EmbeddingDev", lambda *a, **k: EmbFalso(m))
    monkeypatch.setattr(comun, "comprobar_bucket", lambda s3, bucket: "ok")
    monkeypatch.setattr(comun, "red_tareas", lambda outputs: {})
    monkeypatch.setattr(comun, "credenciales_admin", lambda entorno, sesion=None: ("admin@campus.edu.co", PASSWORD))
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    return m


def _correr(mundo: Mundo, tmp_path, *argumentos: str) -> tuple[int, dict[str, Any]]:
    informe = tmp_path / "informe.json"
    codigo = validate41.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ContextoFalso(mundo))
    return codigo, json.loads(informe.read_text(encoding="utf-8"))


def _estados(informe: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["comprobaciones"]}


def test_camino_feliz(mundo, tmp_path, capsys):
    codigo, informe = _correr(mundo, tmp_path)
    assert codigo == 0, capsys.readouterr().out
    assert set(_estados(informe).values()) == {"pasa"}
    assert not mundo.suspendido and mundo.worker == 1  # la limpieza lo deja como estaba
    assert mundo.lugares == {} and all(v["estado"] == "eliminado" for v in mundo.videos.values())
    salida = capsys.readouterr().out
    assert "FIRMA" not in salida


@pytest.mark.parametrize(
    ("interruptor", "falla"),
    [("no_retira", "C1b"), ("no_purga", "C2"), ("sin_auditoria", "C4b"), ("campo_de_mas", "C5a")],
)
def test_backends_defectuosos(mundo, tmp_path, interruptor, falla):
    setattr(mundo, interruptor, True)
    codigo, informe = _correr(mundo, tmp_path)
    assert codigo == 1
    assert _estados(informe)[falla] == "falla"


def test_sin_reconciliador_c3_falla_y_la_limpieza_reanuda_el_escalado(mundo, tmp_path):
    mundo.sin_reconciliador = True
    codigo, informe = _correr(mundo, tmp_path, "--solo", "C3")
    assert codigo == 1 and _estados(informe)["C3"] == "falla"
    assert not mundo.suspendido and mundo.worker == 1


def test_sin_desplegar_es_codigo_2(mundo, tmp_path):
    mundo.desplegado = False
    codigo, _ = _correr(mundo, tmp_path)
    assert codigo == 2


def test_la_preparacion_reanuda_un_escalado_suspendido(mundo, tmp_path):
    mundo.suspendido = True
    codigo, _ = _correr(mundo, tmp_path, "--solo", "C4a")
    assert codigo == 0 and not mundo.suspendido


def test_incluida():
    assert validate41.incluida(None, "C3") and validate41.incluida("C1", "C1b") and not validate41.incluida("C2", "C3")
