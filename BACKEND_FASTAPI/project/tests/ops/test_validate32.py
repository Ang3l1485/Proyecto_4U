"""Validador de BE-3.2 con AWS, HTTP, el conjunto `evaluacion/` de S3, la tarea `psql`, ECS Exec y `POST /v1/localize`
simulados (validation-3-2.md).

Reutiliza el mundo falso de `test_validate22.py` (ECS de `embedding` y `worker` con retraso, escalado, CloudWatch, Cloud
Map, reloj falso) y le añade: el conjunto `evaluacion/2026-11a/` (puntos con dataset cada 100 m, uno intermedio y uno
lejano, con sus fotos originales de 1200×900), la consulta de posiciones del dataset (`SQL_DATASET`), `GET /v1/places`,
`POST /v1/localize` (reconoce cada consulta por la foto ya reducida y responde a 4 m del punto con nivel `alta`, o
`sin_coincidencias` lejos del dataset), los access logs de API Gateway, los logs de `api` y `embedding`, el tamaño de la
tarea de `embedding`, la cola `ingesta` y ECS Exec. Interruptores para simular un backend defectuoso.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import math
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("botocore")
from PIL import Image

import comun
import validate32

_ruta = Path(__file__).with_name("test_validate22.py")
_spec = importlib.util.spec_from_file_location("falsos_validate22_32", _ruta)
t22 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t22)

VERSION = "2026-11a"
LAT0, LNG0 = 6.2, -75.58
M_POR_GRADO = validate32.RADIO_TIERRA_M * math.pi / 180
PLANES = {
    "backend": (
        "| BE-2.2 | 2 | Hecho | x |\n| BE-2.4 | 2 | Hecho | x |\n| BE-3.1 | 3 | Hecho | x |\n"
        "| BE-3.2 | 3 | En curso |\n"
    ),
    "embedding": "| EMB-3.1 | 3 | Hecho | x |\n| EMB-3.2 | 3 | Hecho | x |\n",
    "frontend": "| FE-2.1 | 2 | Hecho | x | — |\n",
}
ARQ_CALIBRADA = """| Versión del documento | **0.13.0** (historia en CHANGELOG) |

### 5.10 Parámetros operativos
| `LOC_SIM_MIN` / `LOC_SIM_ALTA` | 0,61 / 0,83 | Calibrados en BE-3.2 con el informe de EMB-3.2 |
| `LOC_NIVEL_ALTA_MIN` / `LOC_NIVEL_MEDIA_MIN` (cortes de nivel) | 0,72 / 0,50 | Calibrados en BE-3.2 |
### 5.11 Validadores
"""
CAMBIOS_CALIBRADOS = """## [0.13.0] — 2026-11-10
- **Lote que la motivó:** BE-3.2 (calibración de los umbrales con el informe de EMB-3.2)
## [0.12.0] — 2026-10-25
- **Lote que la motivó:** BE-3.2 (construcción)
"""


def norte(metros: float, lat: float = LAT0) -> float:
    return lat + metros / M_POR_GRADO


def original(semilla: int, ancho: int = 1200, alto: int = 900) -> bytes:
    salida = io.BytesIO()
    color = ((semilla * 37) % 256, (semilla * 91) % 256, (semilla * 13) % 256)
    Image.new("RGB", (ancho, alto), color).save(salida, format="JPEG", quality=90)
    return salida.getvalue()


def md5(datos: bytes) -> str:
    return hashlib.md5(datos, usedforsecurity=False).hexdigest()


class Mundo(t22.Mundo):
    def __init__(self, embedding_encendido: bool = False, hora_bogota: int = 15, n_con_dataset: int = 12) -> None:
        super().__init__(embedding_encendido=embedding_encendido, hora_bogota=hora_bogota)
        self.puntos: dict[str, dict[str, Any]] = {}
        self.dataset: list[tuple[float, float]] = []
        self.preparadas: dict[bytes, str] = {}
        definiciones = [(f"P{k + 1:02d}", norte(k * 100), True, 5) for k in range(n_con_dataset)]
        definiciones += [("P90", norte(-70), False, 5), ("P91", norte(-2000), False, 3)]  # intermedio y lejano
        fotos_json, semilla = [], 0
        for pid, lat, con_dataset, n_fotos in definiciones:
            self.puntos[pid] = {"id": pid, "lat": lat, "lng": LNG0, "dataset": con_dataset}
            if con_dataset:
                self.dataset.append((norte(10, lat), LNG0))
            for n in range(1, n_fotos + 1):
                semilla += 1
                datos = original(semilla)
                archivo = f"fotos/{pid}/{n}.jpg"
                self.objetos[f"evaluacion/{VERSION}/{archivo}"] = {"datos": datos, "etag": md5(datos), "tipo": "x"}
                self.preparadas[validate32.preparar_foto(datos)] = pid
                fotos_json.append({"archivo": archivo, "punto": pid, "rumbo": (n - 1) * 72.0, "hora": "manana"})
        fotos_json.append({"archivo": "fotos/P01/99.jpg", "punto": "P01", "rumbo": None})  # en puntos.json, no en S3
        conjunto = {
            "version_conjunto": VERSION,
            "puntos": [{k: p[k] for k in ("id", "lat", "lng")} for p in self.puntos.values()],
            "fotos": fotos_json,
        }
        self.objetos[f"evaluacion/{VERSION}/puntos.json"] = {"datos": json.dumps(conjunto).encode(), "etag": "pj"}
        self.versiones = ["evaluacion/2026-10a/", f"evaluacion/{VERSION}/", "evaluacion/borrador/"]
        self.localizaciones = 0
        self.log_api: list[tuple[Any, str]] = []
        self.log_embedding: list[tuple[Any, str]] = []
        self.log_apigw: list[tuple[Any, str]] = []
        self.exec_comandos: list[tuple[str, str]] = []
        self.plugin = True
        self.ecs_exec = True
        self.ingesta_visibles = 0
        # interruptores de un backend defectuoso
        self.desplegado = True
        self.error_grande = False  # todas las posiciones a 40 m
        self.alta_lejos = False  # P01 con nivel alta a 35 m (el resto bien)
        self.lento = False  # integrationLatency de 1500 ms
        self.guarda_consulta = False  # deja la foto en S3
        self.registra_foto = False  # la foto en base64 en el log de api
        self.deja_archivo = False  # un archivo nuevo en el disco de api
        self.coincide_lejos = False  # un punto sin dataset da `ok`

    # -- tareas sueltas -------------------------------------------------------------------------------------------
    def psql(self, consulta: str) -> list[str]:
        if consulta == validate32.SQL_DATASET:
            return [f"{lat:.5f}|{lng:.5f}" for lat, lng in self.dataset]
        return super().psql(consulta)

    # -- API ----------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, headers: dict | None = None, json: Any = None, params=None, **resto):
        ruta = url.split("/v1", 1)[1]
        if ruta == "/places" and metodo == "GET":
            return t22.Respuesta(200, {"items": [], "total": 3})
        if ruta == "/localize" and metodo == "POST":
            return self._localizar(resto.get("files") or [])
        return super().request(metodo, url, headers=headers, json=json, params=params, **resto)

    def _localizar(self, files: list) -> t22.Respuesta:
        if not self.desplegado:
            return t22._error(404, "NO_ENCONTRADO")
        fotos = [f[1][1] for f in files if f[0] == "fotos"]
        if not fotos:
            cuerpo = {"error": {"codigo": "FOTOS_INVALIDAS", "mensaje": "…", "detalle": {"indice": 0, "motivo": "x"}}}
            return t22.Respuesta(400, cuerpo)
        [metadatos] = [json.loads(f[1][1]) for f in files if f[0] == "metadatos"]
        assert metadatos["app_version"] == "validacion-32" and len(metadatos["rumbos"]) == len(fotos)
        if not self.sano():
            return t22._error(503, "EMBEDDING_NO_DISPONIBLE")
        self.localizaciones += 1
        self.t += timedelta(seconds=1)
        punto = self.puntos[self.preparadas[fotos[0]]]
        if punto["dataset"] or self.coincide_lejos:
            error = 40.0 if self.error_grande else (35.0 if self.alta_lejos and punto["id"] == "P01" else 4.0)
            cuerpo = {
                "resultado": "ok",
                "posicion": {"lat": round(norte(error, punto["lat"]), 6), "lng": punto["lng"], "radio_m": 6.0},
                "confianza": 0.9, "nivel": "alta", "correccion_rumbo_grados": None,
                "lugar_cercano": {"id": str(uuid.uuid4()), "nombre": "Biblioteca", "distancia_m": 12.0},
                "referencias": [], "fotos_usadas": len(fotos), "fotos_con_coincidencia": len(fotos),
                "version_vector": "dinov2-vits14/pp-v1", "latencia_ms": 380,
            }  # fmt: skip
        else:
            cuerpo = {
                "resultado": "sin_coincidencias", "posicion": None, "confianza": 0, "nivel": None,
                "correccion_rumbo_grados": None, "lugar_cercano": None, "referencias": [],
                "fotos_usadas": len(fotos), "fotos_con_coincidencia": 0, "version_vector": "dinov2-vits14/pp-v1",
                "latencia_ms": 300,
            }  # fmt: skip
        if self.guarda_consulta:
            self.objetos[f"consultas/{uuid.uuid4()}.jpg"] = {"datos": fotos[0], "etag": md5(fotos[0]), "tipo": "x"}
        if self.registra_foto:
            self.log_api.append((self.t, base64.b64encode(fotos[0][:600]).decode()))
        self.log_api.append(
            (self.t, json.dumps({"evento": "localizacion_calculada", "resultado": cuerpo["resultado"]}))
        )
        self.log_embedding.append((self.t, json.dumps({"evento": "peticion", "ruta": "/v1/embed"})))
        request_id = f"req{self.localizaciones:05d}"
        latencia = "1500" if self.lento else "420"
        linea = {"requestId": request_id, "routeKey": "ANY /{proxy+}", "status": "200", "integrationLatency": latencia}
        self.log_apigw.append((self.t, json.dumps(linea)))
        respuesta = t22.Respuesta(200, cuerpo)
        respuesta.headers["apigw-requestid"] = request_id
        return respuesta

    # -- ECS Exec -----------------------------------------------------------------------------------------------------
    def exec(self, tarea: str, comando: str) -> str:
        self.exec_comandos.append((tarea, comando))
        salida = "Starting session with SessionId: ecs-execute-command-0abc\r\nfind: '/proc/1/fd': Permission denied\n"
        salida += "/var/log/amazon/ssm/amazon-ssm-agent.log\n"  # el agente de ECS Exec: no cuenta
        if self.deja_archivo:
            salida += "/srv/consulta-k2j3h4.jpg\n"
        return salida + "\nExiting session with sessionId: ecs-execute-command-0abc.\n"


class S3(t22.S3):
    def list_objects_v2(self, **peticion):
        if peticion.get("Delimiter") == "/":
            assert peticion["Prefix"] == "evaluacion/"
            return {"CommonPrefixes": [{"Prefix": p} for p in self.mundo.versiones]}
        return {"KeyCount": 0}

    def get_paginator(self, nombre):
        assert nombre == "list_objects_v2"
        objetos = self.mundo.objetos

        class Paginador:
            def paginate(self, Bucket, Prefix):
                claves = sorted(c for c in objetos if c.startswith(Prefix))
                for i in range(0, max(len(claves), 1), 7):  # páginas de 7
                    yield {"Contents": [{"Key": c, "ETag": f'"{objetos[c]["etag"]}"'} for c in claves[i : i + 7]]}

        return Paginador()


class Ecs(t22.Ecs):
    def describe_services(self, cluster, services):
        if services[0] == "api":
            servicio = {
                "taskDefinition": f"{t22.ARN_TD}/campus-locator-dev-api:7",
                "enableExecuteCommand": self.mundo.ecs_exec,
            }
            return {"services": [servicio]}
        respuesta = super().describe_services(cluster, services)
        respuesta["services"][0]["taskDefinition"] = f"{t22.ARN_TD}/campus-locator-dev-embedding:5"
        return respuesta

    def describe_task_definition(self, taskDefinition):
        respuesta = super().describe_task_definition(taskDefinition)
        if "embedding" in taskDefinition:
            respuesta["taskDefinition"] |= {"cpu": "2048", "memory": "4096"}
        return respuesta

    def list_tasks(self, cluster, serviceName, desiredStatus):
        if serviceName == "api":
            return {"taskArns": [f"arn:aws:ecs:us-east-1:{t22.CUENTA}:task/campus-locator-dev/apitarea1"]}
        return super().list_tasks(cluster, serviceName, desiredStatus)


class Sqs(t22.Sqs):
    def get_queue_attributes(self, QueueUrl, AttributeNames):
        assert QueueUrl == t22.URL_INGESTA
        visibles = str(self.mundo.ingesta_visibles)
        return {"Attributes": {"ApproximateNumberOfMessages": visibles, "ApproximateNumberOfMessagesNotVisible": "0"}}


class Logs(t22.Logs):
    def filter_log_events(self, logGroupName, startTime, filterPattern=None, nextToken=None):
        if logGroupName == comun.LOG_WORKER:
            return super().filter_log_events(logGroupName, startTime, filterPattern, nextToken)
        fuente = {
            comun.LOG_API: self.mundo.log_api,
            comun.LOG_EMBEDDING: self.mundo.log_embedding,
            validate32.LOG_APIGW: self.mundo.log_apigw,
        }[logGroupName]
        mensajes = [m for momento, m in fuente if momento.timestamp() * 1000 >= startTime]
        inicio = int(nextToken or 0)
        pagina = {"events": [{"message": m} for m in mensajes[inicio : inicio + 7]]}
        if inicio + 7 < len(mensajes):
            pagina["nextToken"] = str(inicio + 7)
        return pagina


class Sesion(t22.Sesion):
    def __init__(self, mundo: Mundo) -> None:
        super().__init__(mundo)
        self.ecs = Ecs(mundo)
        self.clientes |= {"ecs": self.ecs, "logs": Logs(mundo, self.ecs), "s3": S3(mundo), "sqs": Sqs(mundo)}


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: t22.OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")
    rutas = {}
    for nombre, constante, texto in (
        ("backend", "PLAN_BACKEND", PLANES["backend"]),
        ("embedding", "PLAN_EMBEDDING", PLANES["embedding"]),
        ("frontend", "PLAN_FRONTEND", PLANES["frontend"]),
        ("arquitectura", "ARQUITECTURA", ARQ_CALIBRADA),
        ("cambios", "CAMBIOS", CAMBIOS_CALIBRADOS),
    ):
        ruta = tmp_path / f"{nombre}.md"
        ruta.write_text(texto, encoding="utf-8")
        monkeypatch.setattr(validate32, constante, ruta)
        rutas[nombre] = ruta

    def correr(mundo: Mundo, *argumentos: str):
        sesion = Sesion(mundo)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate32.Contexto("dev")
        ctx.http = mundo
        ctx.dormir, ctx.ahora = mundo.dormir, mundo.ahora
        ctx.exec = mundo.exec
        ctx.hay_plugin = lambda: mundo.plugin
        informe = tmp_path / "informe.json"
        codigo = validate32.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8")), ctx

    correr.rutas = rutas
    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def _detalle(informe: dict, id_: str) -> str:
    return next(c["detalle"] for c in informe["precondiciones"] + informe["comprobaciones"] if c["id"] == id_)


ORDEN = ["P1", "P2", "P3", "P4", "P5", "P6", "C1", "C3", "C5", "C2", "C4a", "C4b", "C4c", "C6"]


def test_dev_completo_con_embedding_apagado_lo_enciende_y_lo_apaga(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=False)
    codigo, sesion, informe, ctx = entorno_dev(mundo)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert list(_estados(informe)) == ORDEN and set(_estados(informe).values()) == {"pasa"}
    assert "conjunto 2026-11a: 14 puntos, 68 fotos (1 fotos de puntos.json no están en S3)" in _detalle(informe, "P4")
    assert "puntos con dataset (≤ 30 m): 12 · fuera de cobertura (> 150 m): 1 · intermedios: 1" in _detalle(
        informe, "P5"
    )
    assert "embedding encendido en" in _detalle(informe, "P6")
    assert "12 puntos con dataset · error mediano 4.0 m" in _detalle(informe, "C1")
    assert "con lugar_cercano: 12" in _detalle(informe, "C1")
    assert "100 × 200 · integrationLatency p50 420 ms, p95 420 ms" in _detalle(informe, "C3")
    assert "1 puntos fuera de cobertura → 200 sin_coincidencias" in _detalle(informe, "C5")
    assert "112 respuestas de nivel alta (de 112: C1 y C3) · error máximo 4." in _detalle(informe, "C2")
    assert "ningún ETag coincide" in _detalle(informe, "C4a") and "ninguno con /9j/" in _detalle(informe, "C4b")
    assert "CHANGELOG 0.13.0 (BE-3.2)" in _detalle(informe, "C6")
    # 12 de C1 + 3 de calentamiento + 100 de C3 + 1 de C5; el punto intermedio no se consulta
    assert mundo.localizaciones == 116
    [(tarea, comando)] = mundo.exec_comandos
    assert tarea.endswith("/apitarea1") and comando.startswith("find / -xdev -type f -newermt @") and "+50k" in comando
    lanzadas = [p["overrides"]["containerOverrides"][0]["command"] for p in sesion.ecs.lanzadas]
    assert lanzadas == [["psql", "-tAc", validate32.SQL_DATASET]]
    assert mundo.cambios_embedding == [1, 0] and mundo.rangos == {"embedding": (0, 0), "worker": (0, 0)}
    assert "embedding apagado (lo encendió el validador)" in salida.out
    assert ctx._preparadas == {}  # las fotos del conjunto no quedan en memoria
    assert "s3.amazonaws.com" not in salida.out + salida.err + json.dumps(informe)


def test_con_embedding_encendido_lo_deja_encendido(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=True)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 0, capsys.readouterr().out
    assert "ya encendido (latido publicado)" in _detalle(informe, "P6")
    assert mundo.cambios_embedding == [] and mundo.deseado["embedding"] == 1
    assert "embedding sigue encendido (como estaba)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("interruptor", "id_", "texto"),
    [
        ("error_grande", "C1", "error mediano 40.0 m"),
        ("alta_lejos", "C2", "punto P01 (C1) a 35.0 m"),
        ("lento", "C3", "p95 1500 ms"),
        ("guarda_consulta", "C4a", "fotos de consulta están en el bucket, p. ej. consultas/"),
        ("registra_foto", "C4b", "contienen /9j/"),
        ("deja_archivo", "C4c", "p. ej. /srv/consulta-k2j3h4.jpg"),
        ("coincide_lejos", "C5", "resultado = 'ok'"),
    ],
)
def test_un_backend_defectuoso_falla_su_comprobacion(entorno_dev, interruptor, id_, texto):
    mundo = Mundo(embedding_encendido=True)
    setattr(mundo, interruptor, True)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 1
    fallidas = {i for i, estado in _estados(informe).items() if estado == "falla"}
    assert id_ in fallidas, informe
    assert texto in _detalle(informe, id_)


def test_con_los_documentos_reales_c6_falla_hasta_calibrar(entorno_dev, monkeypatch):
    real = Path(validate32.comun.RAIZ_CARPETA) / "docs"
    if not (real / "ARCHITECTURE.md").is_file():
        pytest.skip("sin docs/ (project/ copiado solo)")
    monkeypatch.setattr(validate32, "ARQUITECTURA", real / "ARCHITECTURE.md")
    monkeypatch.setattr(validate32, "CAMBIOS", real / "CHANGELOG.md")
    codigo, _, informe, _ = entorno_dev(Mundo(embedding_encendido=True), "--solo", "C6")
    assert codigo == 1 and _estados(informe)["C6"] == "falla"
    assert "todavía dice «Iniciales»" in _detalle(informe, "C6")


def test_solo_c6_no_enciende_embedding_ni_localiza(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C6")
    assert codigo == 0, informe
    assert "no hace falta" in _detalle(informe, "P6")
    assert mundo.cambios_embedding == [] and mundo.localizaciones == 0
    assert _estados(informe)["C1"] == "omitida"


def test_solo_c2_hace_las_peticiones_de_c1_y_c3(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C2")
    assert codigo == 0, informe
    assert _estados(informe)["C1"] == "omitida" and _estados(informe)["C2"] == "pasa"
    assert mundo.localizaciones == 115 and "de 112: C1 y C3" in _detalle(informe, "C2")


def test_sin_be32_desplegado_es_codigo_2_sin_encender_nada(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    mundo.desplegado = False
    codigo, sesion, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "BE-3.2 sin desplegar" in _detalle(informe, "P3")
    assert mundo.cambios_embedding == [] and sesion.ecs.lanzadas == []


@pytest.mark.parametrize(
    ("plan", "texto", "id_"),
    [
        ("backend", "BE-2.4 no está «Hecho»", "P2"),
        ("embedding", "EMB-3.2 no está «Hecho»", "P4"),
        ("frontend", "FE-2.1 no está «Hecho»", "P5"),
    ],
)
def test_un_lote_sin_hacer_es_codigo_2(entorno_dev, plan, texto, id_):
    lote = texto.split()[0]
    entorno_dev.rutas[plan].write_text(PLANES[plan].replace(f"| {lote} | 2 | Hecho", f"| {lote} | 2 | En curso")
                                       .replace(f"| {lote} | 3 | Hecho", f"| {lote} | 3 | En curso"),
                                       encoding="utf-8")  # fmt: skip
    mundo = Mundo(embedding_encendido=False)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and texto in _detalle(informe, id_)
    assert mundo.cambios_embedding == []


def test_sin_conjunto_en_s3_es_codigo_2(entorno_dev):
    mundo = Mundo()
    mundo.versiones = ["evaluacion/borrador/"]
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "no hay ningún conjunto" in _detalle(informe, "P4")


def test_conjunto_con_pocos_puntos_es_codigo_2(entorno_dev):
    codigo, _, informe, _ = entorno_dev(Mundo(n_con_dataset=7))  # 7 + intermedio + lejano = 9 < 10
    assert codigo == 2 and "tiene 9 puntos con fotos en S3, se necesitan ≥ 10" in _detalle(informe, "P4")


def test_sin_dataset_indexado_es_codigo_2(entorno_dev):
    mundo = Mundo()
    mundo.dataset = []
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "no hay imágenes indexadas" in _detalle(informe, "P5")


def test_fuera_de_horario_es_codigo_3(entorno_dev):
    mundo = Mundo(embedding_encendido=False, hora_bogota=21)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3 and "antes de las 21:00" in _detalle(informe, "P2")
    assert mundo.cambios_embedding == []


def test_sin_session_manager_plugin_es_codigo_3_salvo_sin_c4c(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    mundo.plugin = False
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3 and "session-manager-plugin" in _detalle(informe, "P1")
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C1,C5")
    assert codigo == 0, informe


def test_api_sin_ecs_exec_es_codigo_2(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    mundo.ecs_exec = False
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "ECS Exec" in _detalle(informe, "P3")


def test_ingesta_con_mensajes_falla_c3(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    mundo.ingesta_visibles = 4
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C3")
    assert codigo == 1 and "ingesta tiene 4 mensajes visibles" in _detalle(informe, "C3")


# --- Funciones sueltas ------------------------------------------------------------------------------------------------
def test_preparar_foto_reduce_aplica_exif_y_no_deja_exif():
    salida = io.BytesIO()
    imagen = Image.new("RGB", (2000, 1500), (200, 10, 10))
    exif = imagen.getexif()
    exif[0x0112] = 6  # orientación: girar 90°
    imagen.save(salida, format="JPEG", exif=exif.tobytes())
    preparada = validate32.preparar_foto(salida.getvalue())
    with Image.open(io.BytesIO(preparada)) as resultado:
        assert resultado.size == (768, 1024) and resultado.format == "JPEG"
        assert not resultado.getexif()
    pequena = validate32.preparar_foto(original(1, 640, 480))
    with Image.open(io.BytesIO(pequena)) as resultado:
        assert resultado.size == (640, 480)  # no se amplía


def test_percentil_por_rango_mas_cercano():
    valores = list(range(1, 101))
    assert validate32.percentil(valores, 95) == 95 and validate32.percentil(valores, 50) == 50
    assert validate32.percentil([7.0], 95) == 7.0


def test_haversine_igual_que_el_backend():
    from app.dominio import geo

    args = (6.2, -75.58, 6.201, -75.579)
    assert validate32.haversine_m(*args) == pytest.approx(geo.distancia_m(*args), rel=1e-12)


def test_puntos_json_que_no_vale_es_precondicion():
    with pytest.raises(comun.PrecondicionNoCumplida, match=r"EMB-3.2"):
        validate32.puntos_de({"puntos": [{"id": "P01"}], "fotos": []})


@pytest.mark.parametrize(
    ("solo", "id_", "esperado"),
    [(None, "C4c", True), ("C4", "C4c", True), ("C4a", "C4c", False), ("C1,C5", "C4c", False)],
)
def test_incluida_sigue_la_regla_de_solo(solo, id_, esperado):
    assert validate32.incluida(solo, id_) is esperado


def test_sql_del_dataset_usa_la_version_activa_y_excluye_validacion():
    assert "version_vector = 'dinov2-vits14/pp-v1'" in validate32.SQL_DATASET
    assert "NOT LIKE 'validacion-%'" in validate32.SQL_DATASET and "<> 'eliminado'" in validate32.SQL_DATASET
