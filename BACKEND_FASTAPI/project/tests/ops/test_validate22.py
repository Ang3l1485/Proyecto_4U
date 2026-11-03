"""Validador de BE-2.2 con AWS, HTTP, S3, SQS y el `worker` simulados (validation-2-2.md).

El «mundo» falso implementa lo que el validador ve: la API de §5.4/§5.5 y `/v1/health/ready`, S3 (los `PUT`
prefirmados generan eventos en `ingesta`), SQS (contadores de `ingesta` y de la DLQ), ECS (`embedding` y `worker`, que
arrancan y paran con retraso), Application Auto Scaling, CloudWatch (métrica `EmbeddingEncendidos` y la alarma de
inactividad), Cloud Map, CloudWatch Logs del `worker` y las tareas sueltas (`psql` y `limpiar-validacion`). Un `worker`
simulado consume `ingesta` cuando `embedding` está sano, con las reglas de ARCHITECTURE §4.6. El reloj es falso.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlsplit

import pytest

pytest.importorskip("botocore")
from PIL import Image

import comun
import validate22

CUENTA = "648617469176"
BUCKET = "campus-locator-dev-dataset-648617469176"
URL_INGESTA = f"https://sqs.us-east-1.amazonaws.com/{CUENTA}/campus-locator-dev-ingesta"
URL_DLQ = f"https://sqs.us-east-1.amazonaws.com/{CUENTA}/campus-locator-dev-ingesta-dlq"
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = f"{CUENTA}.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend"
ARN_TD = f"arn:aws:ecs:us-east-1:{CUENTA}:task-definition"
OUTPUTS = {
    "api_base_url": "https://abc123.execute-api.us-east-1.amazonaws.com",
    "subredes_tareas": ["subnet-0a"],
    "sg_migrate": "sg-0api",
    "bucket_dataset": BUCKET,
    "sqs_ingesta_url": URL_INGESTA,
    "sqs_ingesta_dlq_url": URL_DLQ,
}
TOKEN = "eyJ-token-falso-del-admin"
FIRMA = "X-Amz-Signature=firma-falsa-que-no-debe-imprimirse"
IP_TAREA = "10.0.1.57"  # IP privada de la tarea de embedding (ENI de describe-tasks)


class Respuesta:
    def __init__(self, estado: int, cuerpo: Any = None, texto: str = "") -> None:
        self.status_code = estado
        self._cuerpo = cuerpo
        self.text = texto or (json.dumps(cuerpo) if cuerpo is not None else "")
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


def _error(estado: int, codigo: str) -> Respuesta:
    return Respuesta(estado, {"error": {"codigo": codigo, "mensaje": "…", "detalle": None}})


def _miniatura() -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (320, 240), (10, 20, 30)).save(salida, format="JPEG")
    return salida.getvalue()


class Mundo:
    def __init__(self, embedding_encendido: bool = False, hora_bogota: int = 15) -> None:
        self.t = datetime(2026, 10, 25, tzinfo=UTC) + timedelta(hours=hora_bogota + 5)  # Bogotá = UTC−5
        self.admin_id = str(uuid.uuid4())
        self.videos: dict[str, dict[str, Any]] = {}
        self.objetos: dict[str, dict[str, Any]] = {}
        self.vectores: dict[str, list[float]] = {}  # imagen_id → [creado_en (epoch)]
        self.cola: list[dict[str, Any]] = []  # mensajes visibles de `ingesta`
        self.dlq = 0
        self.log_worker: list[tuple[datetime, dict[str, Any]]] = []
        self.numero = 0
        self.etags = 0
        # ECS: deseado y en marcha (con retraso) de embedding y worker
        self.deseado = {"embedding": int(embedding_encendido), "worker": int(embedding_encendido)}
        self.corriendo = dict(self.deseado)
        self.cambio: dict[str, datetime] = {}
        maximo = 1 if embedding_encendido else 0
        self.rangos = {"embedding": (0, maximo), "worker": (0, maximo)}
        self.metricas: list[datetime] = []
        self.alarma = "OK" if embedding_encendido else "ALARM"
        self.cambios_embedding: list[int] = []
        # interruptores de backends defectuosos
        self.worker_duplica = False  # crea un segundo vector con un evento repetido
        self.worker_consume_sin_embedding = False
        self.inf21 = True
        self.cloud_map_sin_instancia = 0  # llamadas a list-instances sin instancias (tarea aún sin registrar)
        self.cloud_map_ip = IP_TAREA  # IP de la instancia registrada (otra = registro viejo de una tarea parada)
        self.cloud_map_error: str | None = None

    # -- reloj y simulación ----------------------------------------------------------------------------------------
    def ahora(self) -> datetime:
        return self.t

    def dormir(self, segundos: float) -> None:
        fin = self.t + timedelta(seconds=segundos)
        while self.t < fin:
            self.t = min(fin, self.t + timedelta(seconds=5))
            self._tick()

    def _tick(self) -> None:
        for servicio in ("embedding", "worker"):
            retraso = 60 if servicio == "embedding" else 30
            if self.corriendo[servicio] != self.deseado[servicio] and self.t - self.cambio.get(
                servicio, self.t
            ) >= timedelta(seconds=retraso):
                self.corriendo[servicio] = self.deseado[servicio]
        if self.metricas and self.t - self.metricas[-1] > timedelta(seconds=60):
            self.alarma = "OK"
        # escalado de worker: sube con mensajes visibles y embedding en marcha
        if self.cola and self.corriendo["embedding"] and self.deseado["worker"] == 0 and self.rangos["worker"][1]:
            self._poner("worker", 1)
        if self.corriendo["worker"] and (self.corriendo["embedding"] or self.worker_consume_sin_embedding):
            self._consumir()

    def _poner(self, servicio: str, n: int) -> None:
        if self.deseado[servicio] != n:
            self.deseado[servicio] = n
            self.cambio[servicio] = self.t

    def sano(self) -> bool:
        return bool(self.corriendo["embedding"])

    def log(self, **campos: Any) -> None:
        self.log_worker.append((self.t, campos))

    def _foto_de(self, imagen_id: str) -> tuple[dict, dict] | None:
        for video in self.videos.values():
            for foto in video["fotos"].values():
                if foto["id"] == imagen_id:
                    return video, foto
        return None

    def _consumir(self) -> None:
        while self.cola:
            cuerpo = self.cola.pop(0)
            if "Records" in cuerpo:
                objeto = cuerpo["Records"][0]["s3"]["object"]
                imagen_id = objeto["key"].rsplit("/", 1)[-1].removesuffix(".jpg")
                encontrada = self._foto_de(imagen_id)
                if encontrada is None:
                    self.log(evento="mensaje_descartado", motivo="imagen_no_existe", imagen_id=imagen_id)
                    continue
                _, foto = encontrada
                if foto["estado"] in ("procesada", "error") and foto.get("etag") == objeto["eTag"]:
                    self.log(evento="mensaje_descartado", motivo="duplicado", imagen_id=imagen_id)
                    if self.worker_duplica:
                        self.vectores[imagen_id].append(self.t.timestamp())
                    continue
                self._procesar(foto, "s3")
            else:
                encontrada = self._foto_de(cuerpo["imagen_id"])
                if encontrada:
                    self._procesar(encontrada[1], "reprocesar")

    def _procesar(self, foto: dict, origen: str) -> None:
        objeto = self.objetos.get(foto["clave"])
        if objeto is None:
            return
        foto["etag"] = objeto["etag"]
        if not objeto["datos"].startswith(b"\xff\xd8"):
            foto["estado"], foto["error"] = "error", "no es un JPEG decodificable"
            self.log(evento="imagen_con_error", imagen_id=foto["id"], motivo=foto["error"])
            return
        thumb = foto["clave"].replace("dataset/", "thumbs/", 1)
        self.objetos[thumb] = {"datos": _miniatura(), "etag": "mini", "tipo": "image/jpeg"}
        if foto["id"] in self.vectores and not self.worker_duplica:
            self.vectores[foto["id"]] = [self.t.timestamp()]
        else:
            self.vectores.setdefault(foto["id"], []).append(self.t.timestamp())
        foto["estado"], foto["error"] = "procesada", None
        self.log(evento="imagen_procesada", imagen_id=foto["id"], origen=origen)

    # -- API ----------------------------------------------------------------------------------------------------------
    def nuevo_video(self, nombre: str, ref: str) -> dict[str, Any]:
        self.numero += 1
        video = {"id": str(uuid.uuid4()), "numero": self.numero, "nombre": nombre, "ref": ref, "fotos": {}}
        self.videos[video["id"]] = video
        return video

    def _resumen(self, video: dict[str, Any]) -> dict[str, Any]:
        conteo = dict.fromkeys(("pendiente_subida", "subida", "procesada", "error"), 0)
        for foto in video["fotos"].values():
            conteo[foto["estado"]] += 1
        return {"id": video["id"], "numero": video["numero"], "nombre": video["nombre"], "ref_cliente": video["ref"]}

    def request(self, metodo: str, url: str, headers: dict | None = None, json: Any = None, params=None, **_: Any):
        ruta = url.split("/v1", 1)[1]
        if ruta == "/health":
            return Respuesta(200, {"estado": "ok", "version": "0.1.0", "commit": SHA[:7]})
        if ruta == "/health/ready":
            return Respuesta(200, {"estado": "ok", "db": "ok", "embedding": "ok" if self.sano() else "no_disponible"})
        if ruta == "/auth/login":
            usuario = {"id": self.admin_id, "nombre": "Administrador", "correo": "admin@campus.edu.co", "rol": "admin"}
            return Respuesta(200, {"token": TOKEN, "expira_en": "2026-10-26T03:00:00Z", "usuario": usuario})
        if (headers or {}).get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, "NO_AUTENTICADO")
        partes = ruta.strip("/").split("/")
        if metodo == "POST" and ruta == "/collect/videos":
            nuevo = self.nuevo_video(json["nombre"], json["ref_cliente"])
            return Respuesta(201, self._resumen(nuevo))
        if metodo == "POST" and partes[:2] == ["collect", "videos"] and partes[3:] == ["images"]:
            video = self.videos.get(partes[2])
            if video is None:
                return _error(404, "NO_ENCONTRADO")
            return Respuesta(200, {"imagenes": [self._registrar(video, i) for i in json["imagenes"]]})
        if metodo == "GET" and ruta == "/admin/videos":
            q = (params or {}).get("q", "")
            items = [self._resumen(v) for v in self.videos.values() if q in v["nombre"]]
            return Respuesta(200, {"items": items, "total": len(items), "pagina": 1, "por_pagina": 100})
        if metodo == "GET" and partes[:2] == ["admin", "videos"] and len(partes) == 3:
            video = self.videos.get(partes[2])
            if video is None:
                return _error(404, "NO_ENCONTRADO")
            fotos = [
                {"id": f["id"], "orden": o, "estado": f["estado"], "error": f.get("error")}
                for o, f in sorted(video["fotos"].items())
            ]
            return Respuesta(200, self._resumen(video) | {"fotos": fotos})
        return _error(404, "NO_ENCONTRADO")

    def _registrar(self, video: dict[str, Any], elemento: dict[str, Any]) -> dict[str, Any]:
        foto = video["fotos"].get(elemento["orden"])
        if foto is None:
            imagen_id = str(uuid.uuid4())
            foto = {"id": imagen_id, "estado": "pendiente_subida", "clave": f"dataset/{video['id']}/{imagen_id}.jpg"}
            video["fotos"][elemento["orden"]] = foto
        subida = None
        if foto["estado"] == "pendiente_subida":
            subida = {
                "metodo": "PUT",
                "url": f"https://{BUCKET}.s3.amazonaws.com/{foto['clave']}?{FIRMA}",
                "encabezados": {"Content-Type": "image/jpeg"},
                "expira_en": (self.t + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        return {"orden": elemento["orden"], "id": foto["id"], "estado": foto["estado"], "subida": subida}

    def close(self) -> None:
        pass

    def put(self, clave: str, datos: bytes) -> None:
        self.etags += 1
        self.objetos[clave] = {"datos": datos, "etag": f"etag{self.etags}", "tipo": "image/jpeg"}
        self.cola.append(
            {
                "Records": [
                    {"eventName": "ObjectCreated:Put", "s3": {"object": {"key": clave, "eTag": f"etag{self.etags}"}}}
                ]
            }
        )

    # -- tareas sueltas -------------------------------------------------------------------------------------------
    def psql(self, consulta: str) -> list[str]:
        ids = [i for i in self._ids_en(consulta)]
        if "JOIN imagenes" in consulta:
            imagen_id = ids[0]
            foto = self._foto_de(imagen_id)[1]
            return [f"{creado}|{foto['estado']}" for creado in self.vectores.get(imagen_id, [])]
        lineas = []
        for imagen_id in sorted(ids):
            lineas += [f"{imagen_id}|dinov2-vits14/pp-v1|{c}" for c in self.vectores.get(imagen_id, [])]
        return lineas

    @staticmethod
    def _ids_en(consulta: str) -> list[str]:
        import re

        return re.findall(r"'([0-9a-f-]{36})'", consulta)

    def limpiar(self, ids: list[str]) -> list[str]:
        objetos = 0
        for video_id in ids or [i for i, v in self.videos.items() if v["nombre"].startswith("validacion-")]:
            for clave in [c for c in self.objetos if f"/{video_id}/" in c]:
                del self.objetos[clave]
                objetos += 1
            del self.videos[video_id]
        resumen = {"videos": len(ids), "objetos": objetos}
        return [json.dumps({"evento": "limpieza_validacion", **resumen}), f"LIMPIEZA {json.dumps(resumen)}"]


class HttpS3:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.puts: list[int] = []

    def request(self, metodo: str, url: str, headers: dict | None = None, content: bytes = b"", **_: Any):
        assert metodo == "PUT" and headers == {"Content-Type": "image/jpeg"}
        self.mundo.put(urlsplit(url).path.lstrip("/"), content)
        self.puts.append(200)
        return Respuesta(200, texto="")

    def close(self) -> None:
        pass


def _client_error(codigo: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")


class S3:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo

    def head_bucket(self, Bucket):
        return {"ResponseMetadata": {"HTTPHeaders": {"date": format_datetime(self.mundo.t, usegmt=True)}}}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        return {"KeyCount": 0}

    def head_object(self, Bucket, Key):
        objeto = self.mundo.objetos.get(Key)
        if objeto is None:
            raise _client_error("404")
        return {"ContentLength": len(objeto["datos"]), "ETag": f'"{objeto["etag"]}"', "ContentType": objeto["tipo"]}

    def get_object(self, Bucket, Key):
        objeto = self.mundo.objetos.get(Key)
        if objeto is None:
            raise _client_error("NoSuchKey")
        return {"Body": io.BytesIO(objeto["datos"])}


class Sqs:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.enviados: list[dict] = []

    def get_queue_attributes(self, QueueUrl, AttributeNames):
        if QueueUrl == URL_DLQ:
            visibles, en_vuelo = self.mundo.dlq, 0
        else:
            visibles, en_vuelo = len(self.mundo.cola), 0
        return {
            "Attributes": {
                "ApproximateNumberOfMessages": str(visibles),
                "ApproximateNumberOfMessagesNotVisible": str(en_vuelo),
            }
        }

    def send_message(self, QueueUrl, MessageBody):
        assert QueueUrl == URL_INGESTA
        cuerpo = json.loads(MessageBody)
        self.enviados.append(cuerpo)
        self.mundo.cola.append(cuerpo)
        return {"MessageId": f"m{len(self.enviados)}"}


class Ecs:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.lanzadas: list[dict[str, Any]] = []
        self.logs: dict[str, list[str]] = {}
        self._codigos: dict[str, int] = {}

    def describe_services(self, cluster, services):
        nombre = services[0]
        if nombre == "api":
            return {"services": [{"taskDefinition": f"{ARN_TD}/campus-locator-dev-api:7"}]}
        rollout = "COMPLETED" if self.mundo.corriendo[nombre] == self.mundo.deseado[nombre] else "IN_PROGRESS"
        servicio = {
            "serviceName": nombre,
            "desiredCount": self.mundo.deseado[nombre],
            "runningCount": self.mundo.corriendo[nombre],
            "deployments": [{"status": "PRIMARY", "rolloutState": rollout}],
            "serviceRegistries": [{"registryArn": "arn:aws:servicediscovery:us-east-1:1:service/srv-emb"}],
        }
        return {"services": [servicio]}

    def update_service(self, cluster, service, desiredCount):
        if service == "embedding":
            self.mundo.cambios_embedding.append(desiredCount)
        self.mundo._poner(service, desiredCount)
        return {}

    def list_tasks(self, cluster, serviceName, desiredStatus):
        return {"taskArns": ["arn:emb/1"] if self.mundo.corriendo[serviceName] else []}

    def describe_task_definition(self, taskDefinition):
        familia = taskDefinition.rsplit("/", 1)[-1].split(":")[0]
        definicion = {
            "taskDefinitionArn": f"{ARN_TD}/{familia}:7",
            "containerDefinitions": [{"name": "app", "image": f"{REPO}:{SHA}"}],
        }
        return {"taskDefinition": definicion}

    def run_task(self, **peticion):
        self.lanzadas.append(peticion)
        comando = peticion["overrides"]["containerOverrides"][0]["command"]
        familia = peticion["taskDefinition"].rsplit("/", 1)[-1].split(":")[0]
        if comando[0] == "psql":
            lineas = self.mundo.psql(comando[2])
        else:
            assert comando[:4] == ["python", "-m", "app.cli", "limpiar-validacion"], comando
            lineas = self.mundo.limpiar([comando[i + 1] for i, p in enumerate(comando) if p == "--video"])
        id_tarea = f"tarea{len(self.lanzadas):028d}"
        self.logs[f"{comun.LOGS_TAREA[familia][1]}/app/{id_tarea}"] = lineas
        arn = f"arn:aws:ecs:us-east-1:{CUENTA}:task/campus-locator-dev/{id_tarea}"
        self._codigos[arn] = 0
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def get_waiter(self, nombre):
        return type("Espera", (), {"wait": lambda self, **_: None})()

    def describe_tasks(self, cluster, tasks):
        if tasks[0] == "arn:emb/1":
            eni = {"type": "ElasticNetworkInterface", "details": [{"name": "privateIPv4Address", "value": IP_TAREA}]}
            return {"tasks": [{"healthStatus": "HEALTHY", "attachments": [eni]}]}
        contenedor = {"name": "app", "exitCode": self._codigos[tasks[0]]}
        return {"tasks": [{"taskDefinitionArn": "…", "containers": [contenedor]}]}


class Logs:
    def __init__(self, mundo: Mundo, ecs: Ecs) -> None:
        self.mundo, self.ecs = mundo, ecs

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        if nextToken:
            return {"events": [], "nextForwardToken": nextToken}
        return {"events": [{"message": m} for m in self.ecs.logs[logStreamName]], "nextForwardToken": "f/1"}

    def filter_log_events(self, logGroupName, startTime, filterPattern, nextToken=None):
        assert logGroupName == "/campus-locator/dev/worker"
        buscado = filterPattern.strip('"')
        eventos = [
            {"message": json.dumps(campos)}
            for momento, campos in self.mundo.log_worker
            if momento.timestamp() * 1000 >= startTime and buscado in json.dumps(campos)
        ]
        return {"events": eventos}


class Escalado:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo

    def describe_scalable_targets(self, ServiceNamespace, ResourceIds):
        if not self.mundo.inf21:
            return {"ScalableTargets": []}
        return {"ScalableTargets": [{"ResourceId": r} for r in ResourceIds]}

    def describe_scaling_policies(self, ServiceNamespace, ResourceId):
        return {"ScalingPolicies": [{"PolicyName": "campus-locator-dev-worker-cola"}]}

    def describe_scheduled_actions(self, ServiceNamespace, ResourceId):
        return {"ScheduledActions": [{"ScheduledActionName": "campus-locator-dev-embedding-apagar-noche"}]}

    def register_scalable_target(self, ServiceNamespace, ResourceId, ScalableDimension, MinCapacity, MaxCapacity):
        self.mundo.rangos[ResourceId.rsplit("/", 1)[-1]] = (MinCapacity, MaxCapacity)
        return {}


class CloudWatch:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo

    def put_metric_data(self, Namespace, MetricData):
        assert Namespace == "campus-locator/dev" and MetricData[0]["MetricName"] == "EmbeddingEncendidos"
        self.mundo.metricas.append(MetricData[0]["Timestamp"])
        return {}

    def get_metric_statistics(self, **_: Any):
        visto = self.mundo.metricas and self.mundo.t - self.mundo.metricas[-1] >= timedelta(seconds=30)
        return {"Datapoints": [{"Sum": 1.0}] if visto else []}

    def describe_alarms(self, AlarmNames):
        return {"MetricAlarms": [{"AlarmName": AlarmNames[0], "StateValue": self.mundo.alarma}]}


class Sesion:
    def __init__(self, mundo: Mundo) -> None:
        self.ecs = Ecs(mundo)
        self.sqs = Sqs(mundo)
        secreto = {"SecretString": json.dumps({"correo": "a@b.c", "password": "p"})}
        self.clientes = {
            "sts": type("Sts", (), {"get_caller_identity": lambda self: {"Account": CUENTA, "Arn": "arn:…/yo"}})(),
            "secretsmanager": type("Secretos", (), {"get_secret_value": lambda self, SecretId: secreto})(),
            "ecs": self.ecs,
            "logs": Logs(mundo, self.ecs),
            "s3": S3(mundo),
            "sqs": self.sqs,
            "application-autoscaling": Escalado(mundo),
            "cloudwatch": CloudWatch(mundo),
            "servicediscovery": CloudMap(mundo),
        }

    def client(self, servicio):
        return self.clientes[servicio]


class CloudMap:
    """Cloud Map como en `dev` (servicio sin configuración de salud): `get-instances-health-status` responde siempre
    `InstanceNotFound`; `list-instances` da una lista vacía las primeras `mundo.cloud_map_sin_instancia` llamadas (ECS
    aún no registró la tarea) y después la instancia con `AWS_INSTANCE_IPV4 = mundo.cloud_map_ip`; o el error fijo
    `mundo.cloud_map_error`."""

    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.llamadas = 0

    def get_instances_health_status(self, ServiceId):
        raise _client_error("InstanceNotFound")  # lo que se vio en dev, 2026-10-25 (54fdf18)

    def list_instances(self, ServiceId):
        assert ServiceId == "srv-emb"
        self.llamadas += 1
        if self.mundo.cloud_map_error:
            raise _client_error(self.mundo.cloud_map_error)
        if self.llamadas <= self.mundo.cloud_map_sin_instancia:
            return {"Instances": []}
        instancia = {"Id": "053f7ed5", "Attributes": {"AWS_INSTANCE_IPV4": self.mundo.cloud_map_ip}}
        return {"Instances": [instancia]}


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    for variable in ("VALIDACION_API_URL", "VALIDACION_ADMIN_CORREO", "VALIDACION_ADMIN_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")

    def correr(mundo: Mundo, *argumentos: str) -> tuple[int, Sesion, dict, str]:
        sesion = Sesion(mundo)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate22.Contexto("dev")
        ctx.http, ctx.http_s3 = mundo, HttpS3(mundo)
        ctx.dormir, ctx.ahora = mundo.dormir, mundo.ahora
        ctx.sello = "20261025-150000"
        informe = tmp_path / "informe.json"
        codigo = validate22.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8")), ctx

    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def _detalle(informe: dict, id_: str) -> str:
    return next(c["detalle"] for c in informe["precondiciones"] + informe["comprobaciones"] if c["id"] == id_)


ORDEN = ["P1", "P2", "P3", "P4", "P5", "P6", "C1a", "C1b", "C1c", "C2", "C4", "C5", "C3a", "C3b"]


def test_dev_completo_con_embedding_apagado_lo_enciende_y_lo_apaga(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=False)
    codigo, sesion, informe, _ = entorno_dev(mundo)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert list(_estados(informe)) == ORDEN and set(_estados(informe).values()) == {"pasa"}
    texto = salida.out + salida.err + json.dumps(informe)
    for secreto in (FIRMA, TOKEN, "s3.amazonaws.com"):
        assert secreto not in texto
    assert "embedding encendido en" in _detalle(informe, "P6")
    assert mundo.metricas  # latido de EmbeddingEncendidos antes de poner 1
    # C3a lo pone a 0, C3b lo vuelve a encender y la limpieza lo apaga (lo encendió el validador)
    assert mundo.cambios_embedding == [1, 0, 1, 0]
    assert mundo.rangos == {"embedding": (0, 0), "worker": (0, 0)}
    assert "embedding apagado (lo encendió el validador)" in salida.out
    assert mundo.videos == {}  # limpiar-validacion
    assert len(sesion.sqs.enviados) == 2  # el evento repetido (C4) y reprocesar_imagen (C5)
    assert "no es un JPEG decodificable" in _detalle(informe, "C2")


def test_con_embedding_encendido_solo_publica_un_latido_y_lo_deja_encendido(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=True)
    codigo, _, informe, _ = entorno_dev(mundo)
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "ya encendido (latido publicado)" in _detalle(informe, "P6")
    assert mundo.cambios_embedding == [0, 1]  # C3a y C3b; la limpieza no lo apaga
    assert mundo.deseado["embedding"] == 1
    assert "embedding sigue encendido (como estaba)" in salida


def test_un_evento_duplicado_que_crea_otro_vector_falla_c4(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    mundo.worker_duplica = True
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C4")
    assert codigo == 1
    assert _estados(informe)["C4"] == "falla" and "2 vectores" in _detalle(informe, "C4")


def test_worker_que_consume_sin_embedding_falla_c3a(entorno_dev):
    mundo = Mundo(embedding_encendido=True)
    mundo.worker_consume_sin_embedding = True
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C3")
    assert codigo == 1
    assert _estados(informe)["C3a"] == "falla"
    assert mundo.deseado["embedding"] == 1  # C3b (y la limpieza) lo dejan encendido, como estaba


def test_fuera_de_horario_es_codigo_3_sin_encender_nada(entorno_dev):
    mundo = Mundo(embedding_encendido=False, hora_bogota=21)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3
    assert "antes de las 21:00" in _detalle(informe, "P4")
    assert mundo.cambios_embedding == [] and mundo.videos == {}


def test_cloud_map_sin_health_config_usa_list_instances_y_espera_el_registro(entorno_dev):
    """`dev`, 2026-10-25: sobre c5917bd, `get-instances-health-status` dio `InstanceNotFound` y P6 terminó con 3; sobre
    54fdf18 (que lo esperaba) dio `InstanceNotFound` durante 10 min y P6 terminó con 2, con `embedding` sano: el
    servicio de Cloud Map no tiene configuración de salud y esa llamada nunca da un estado. Desde 0.9.2 se mira
    `list-instances` (vacía hasta que ECS registra la tarea) y la IP de la tarea sana."""
    mundo = Mundo(embedding_encendido=False)
    mundo.cloud_map_sin_instancia = 3
    codigo, sesion, informe, _ = entorno_dev(mundo, "--solo", "C1a")
    assert codigo == 0, informe
    assert _estados(informe)["P6"] == "pasa" and "embedding encendido en" in _detalle(informe, "P6")
    assert sesion.clientes["servicediscovery"].llamadas > 3  # volvió a mirar tras las listas vacías


def test_instancia_de_cloud_map_con_otra_ip_no_cuenta(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    mundo.cloud_map_ip = "10.0.9.9"  # registro viejo de una tarea que ya paró
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2
    assert "Cloud Map sin la IP de la tarea sana" in _detalle(informe, "P6")
    assert mundo.deseado["embedding"] == 0  # la limpieza lo apagó


def test_cloud_map_sin_permiso_es_codigo_3_y_apaga_lo_encendido(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=False)
    mundo.cloud_map_error = "AccessDeniedException"
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3
    assert "sin permiso para servicediscovery list-instances" in _detalle(informe, "P6")
    assert "embedding apagado (lo encendió el validador)" in capsys.readouterr().out
    assert mundo.deseado["embedding"] == 0


def test_sin_inf21_es_codigo_2(entorno_dev):
    mundo = Mundo()
    mundo.inf21 = False
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "INF-2.1" in _detalle(informe, "P4")
    assert mundo.cambios_embedding == []


def test_lote_hecho_lee_la_tabla_de_estado():
    tabla = "| EMB-2.1 | 2 | Hecho | [2-1](x) | `f2ddc42` |\n| EMB-3.1 | 3 | Pendiente | … |"
    assert validate22.lote_hecho(tabla, "EMB-2.1")
    assert not validate22.lote_hecho(tabla, "EMB-3.1")
    assert not validate22.lote_hecho("| EMB-2.1 | Vectorización | EMB-1.1 | EMB-1.1 |", "EMB-2.1")
