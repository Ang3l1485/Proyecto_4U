"""Validador de BE-2.1 con AWS, HTTP y S3 simulados (validation-2-1.md).

El «mundo» falso implementa lo que el validador ve del contrato de ARCHITECTURE §5.4, §5.5 y §5.9: la API de
recolección, las URL prefirmadas (con su vencimiento según la hora de S3), los objetos de S3 y `limpiar-validacion`
(también `--simular`) como tarea de `worker`. El reloj es falso: la espera de C3a (900 s + 10 s) no tarda, y el reloj
local puede ir desfasado respecto al de S3.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("botocore")  # grupo `ops`

import comun
import validate21

CUENTA = "648617469176"
BUCKET = "campus-locator-dev-dataset-648617469176"
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = f"{CUENTA}.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend"
ARN_TD = f"arn:aws:ecs:us-east-1:{CUENTA}:task-definition"
OUTPUTS = {
    "api_base_url": "https://abc123.execute-api.us-east-1.amazonaws.com",
    "subredes_tareas": ["subnet-0a"],
    "sg_migrate": "sg-0api",
    "bucket_dataset": BUCKET,
}
TOKEN = "eyJ-token-falso-del-admin"
FIRMA = "X-Amz-Signature=firma-falsa-que-no-debe-imprimirse"
ESTADOS = ("pendiente_subida", "subida", "procesada", "error")


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


class Reloj:
    """Hora de S3 y de la API (servidores). El validador ve la local = servidor − `atraso_local_s`."""

    def __init__(self, atraso_local_s: float = 0.0) -> None:
        self.t = datetime(2026, 10, 25, 15, 0, 0, tzinfo=UTC)
        self.dormido = 0.0
        self.atraso_local_s = atraso_local_s

    def servidor(self) -> datetime:
        return self.t

    def local(self) -> datetime:
        return self.t - timedelta(seconds=self.atraso_local_s)

    def dormir(self, segundos: float) -> None:
        self.dormido += segundos
        self.t += timedelta(seconds=segundos)


class Mundo:
    """API de §5.4/§5.5, S3 y `limpiar-validacion`, en memoria. Los interruptores simulan backends defectuosos."""

    def __init__(self, atraso_local_s: float = 0.0) -> None:
        self.reloj = Reloj(atraso_local_s)
        self.admin_id = str(uuid.uuid4())
        self.videos: dict[str, dict[str, Any]] = {}
        self.objetos: dict[str, dict[str, Any]] = {}
        self.numero = 0
        self.firmas = 0
        self.head_en_images = True
        self.urls_vencen = True
        self.estado_fijo: str | None = None  # backend que devuelve siempre este estado en complete
        self.rutas: list[str] = []

    # -- datos ----------------------------------------------------------------------------------------------------
    def nuevo_video(self, nombre: str, ref: str, total: int = 0) -> dict[str, Any]:
        self.numero += 1
        video = {
            "id": str(uuid.uuid4()),
            "numero": self.numero,
            "nombre": nombre,
            "ref": ref,
            "total": total,
            "completa": False,
            "fotos": {},
        }
        self.videos[video["id"]] = video
        return video

    def _conteo(self, video: dict[str, Any]) -> dict[str, int]:
        conteo = dict.fromkeys(ESTADOS, 0)
        for foto in video["fotos"].values():
            conteo[foto["estado"]] += 1
        return conteo

    def _estado(self, video: dict[str, Any]) -> str:
        conteo = self._conteo(video)
        if not video["completa"] or conteo["pendiente_subida"]:
            return "pendiente"
        return "procesando" if conteo["subida"] else ("con_errores" if conteo["error"] else "procesado")

    def resumen(self, video: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": video["id"],
            "numero": video["numero"],
            "nombre": video["nombre"],
            "ref_cliente": video["ref"],
            "estado": self._estado(video),
            "creado_en": "2026-10-25T15:00:00Z",
            "iniciado_en": None,
            "finalizado_en": None,
            "duracion_s": None,
            "distancia_m": None,
            "pasos": None,
            "inicio": None,
            "total_fotos": video["total"],
            "conteo": self._conteo(video),
            "creado_por": {"id": self.admin_id, "nombre": "Administrador"},
        }

    def _subida(self, clave: str) -> dict[str, Any]:
        self.firmas += 1
        vence = self.reloj.servidor().replace(microsecond=0) + timedelta(seconds=900)
        return {
            "metodo": "PUT",
            "url": f"https://{BUCKET}.s3.amazonaws.com/{clave}?vence={vence.timestamp()}&{FIRMA}{self.firmas}",
            "encabezados": {"Content-Type": "image/jpeg"},
            "expira_en": vence.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    # -- API ----------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, headers: dict | None = None, json: Any = None, params=None, **_: Any):
        ruta = url.split("/v1", 1)[1]
        self.rutas.append(f"{metodo} {ruta}")
        if ruta == "/health":
            return Respuesta(200, {"estado": "ok", "version": "0.1.0", "commit": SHA[:7]})
        if ruta == "/auth/login":
            usuario = {"id": self.admin_id, "nombre": "Administrador", "correo": "admin@campus.edu.co", "rol": "admin"}
            return Respuesta(200, {"token": TOKEN, "expira_en": "2026-10-26T03:00:00Z", "usuario": usuario})
        if (headers or {}).get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, "NO_AUTENTICADO")
        partes = ruta.strip("/").split("/")
        if metodo == "POST" and ruta == "/collect/videos":
            for video in self.videos.values():
                if video["ref"] == json["ref_cliente"]:
                    return Respuesta(200, self.resumen(video))
            nuevo = self.nuevo_video(json["nombre"], json["ref_cliente"], json["total_fotos"])
            return Respuesta(201, self.resumen(nuevo))
        if metodo == "POST" and partes[:2] == ["collect", "videos"] and len(partes) == 4:
            video = self.videos.get(partes[2])
            if video is None:
                return _error(404, "NO_ENCONTRADO")
            if partes[3] == "images":
                return Respuesta(200, {"imagenes": [self._registrar(video, i) for i in json["imagenes"]]})
            for foto in video["fotos"].values():
                if foto["estado"] == "pendiente_subida" and foto["clave"] in self.objetos:
                    foto["estado"] = "subida"
            video["completa"] = True
            estado = self.estado_fijo or self._estado(video)
            return Respuesta(200, {"id": video["id"], "estado": estado, "conteo": self._conteo(video)})
        if metodo == "GET" and ruta == "/admin/videos":
            q = (params or {}).get("q", "").lower()
            pagina, por_pagina = int((params or {}).get("pagina", 1)), int((params or {}).get("por_pagina", 24))
            todos = [self.resumen(v) for v in self.videos.values() if q in v["nombre"].lower()]
            items = todos[(pagina - 1) * por_pagina : pagina * por_pagina]
            return Respuesta(200, {"items": items, "total": len(todos), "pagina": pagina, "por_pagina": por_pagina})
        if metodo == "GET" and partes[:2] == ["admin", "videos"] and len(partes) == 3:
            video = self.videos.get(partes[2])
            if video is None:
                return _error(404, "NO_ENCONTRADO")
            fotos = [self._imagen_admin(video, o) for o in sorted(video["fotos"])]
            return Respuesta(200, self.resumen(video) | {"fotos": fotos})
        return _error(404, "NO_ENCONTRADO")

    def _registrar(self, video: dict[str, Any], elemento: dict[str, Any]) -> dict[str, Any]:
        foto = video["fotos"].get(elemento["orden"])
        if foto is None:
            imagen_id = str(uuid.uuid4())
            foto = {"id": imagen_id, "estado": "pendiente_subida", "clave": f"dataset/{video['id']}/{imagen_id}.jpg"}
            video["fotos"][elemento["orden"]] = foto
        elif foto["estado"] == "pendiente_subida" and self.head_en_images and foto["clave"] in self.objetos:
            foto["estado"] = "subida"
        subida = self._subida(foto["clave"]) if foto["estado"] == "pendiente_subida" else None
        return {"orden": elemento["orden"], "id": foto["id"], "estado": foto["estado"], "subida": subida}

    def _imagen_admin(self, video: dict[str, Any], orden: int) -> dict[str, Any]:
        foto = video["fotos"][orden]
        return {
            "id": foto["id"],
            "video_id": video["id"],
            "orden": orden,
            "lat": 1.0,
            "lng": -100.0,
            "rumbo": 0.0,
            "capturada_en": "2026-10-20T14:00:01Z",
            "estado": foto["estado"],
            "error": None,
            "calidad": "normal",
            "lugar": None,
            "notas": None,
            "url": None,
            "url_miniatura": None,
            "url_expira_en": None,
        }

    def close(self) -> None:
        pass

    # -- limpiar-validacion (§5.9) ----------------------------------------------------------------------------------
    def limpiar(self, ids: list[str], simular: bool) -> tuple[list[str], int]:
        def de_validacion(video):
            return video["nombre"].startswith("validacion-") and video["ref"].startswith("validacion-")

        if ids:
            inexistentes = [i for i in ids if i not in self.videos]
            sin_prefijo = [i for i in ids if i in self.videos and not de_validacion(self.videos[i])]
            if inexistentes or sin_prefijo:
                evento = {"evento": "limpieza_rechazada", "inexistentes": inexistentes, "sin_prefijo": sin_prefijo}
                return [json.dumps(evento)], 1
            objetivo = ids
        else:
            objetivo = [i for i, v in self.videos.items() if de_validacion(v)]
        objetos = 0
        for video_id in objetivo:
            claves = [c for c in self.objetos if c.startswith(f"dataset/{video_id}/")]
            objetos += len(claves)
            if not simular:
                for clave in claves:
                    del self.objetos[clave]
                del self.videos[video_id]
        resumen = {"videos": len(objetivo), "objetos": objetos}
        if simular:
            return [json.dumps({"evento": "limpieza_simulada", **resumen}), f"SIMULACION {json.dumps(resumen)}"], 0
        return [json.dumps({"evento": "limpieza_validacion", **resumen}), f"LIMPIEZA {json.dumps(resumen)}"], 0


class HttpS3:
    """`PUT` a una URL prefirmada falsa: vence en `expira_en` (hora de S3) y exige `Content-Type: image/jpeg`."""

    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.puts: list[int] = []

    def request(self, metodo: str, url: str, headers: dict | None = None, content: bytes = b"", **_: Any):
        assert metodo == "PUT"
        partes = urlsplit(url)
        vence = float(parse_qs(partes.query)["vence"][0])
        if self.mundo.urls_vencen and self.mundo.reloj.servidor().timestamp() > vence:
            texto = (
                "<?xml version='1.0'?><Error><Code>AccessDenied</Code><Message>Request has expired</Message></Error>"
            )
            respuesta = Respuesta(403, texto=texto)
        elif headers != {"Content-Type": "image/jpeg"}:
            respuesta = Respuesta(403, texto="<Error><Code>SignatureDoesNotMatch</Code></Error>")
        else:
            self.mundo.objetos[partes.path.lstrip("/")] = {"ContentType": "image/jpeg", "ContentLength": len(content)}
            respuesta = Respuesta(200, texto="")
        self.puts.append(respuesta.status_code)
        return respuesta

    def close(self) -> None:
        pass


class S3:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.bucket_existe = True
        self.listar_denegado = False

    def _error(self, codigo: str):
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")

    def head_bucket(self, Bucket):
        if not self.bucket_existe:
            raise self._error("404")
        fecha = format_datetime(self.mundo.reloj.servidor(), usegmt=True)
        return {"ResponseMetadata": {"HTTPHeaders": {"date": fecha}}}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        if self.listar_denegado:
            raise self._error("AccessDenied")
        return {"KeyCount": 0}

    def head_object(self, Bucket, Key):
        if Key not in self.mundo.objetos:
            raise self._error("404")
        return dict(self.mundo.objetos[Key])

    def get_paginator(self, nombre):
        mundo = self.mundo

        class Paginador:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": c} for c in sorted(mundo.objetos) if c.startswith(Prefix)]}]

        return Paginador()


class Ecs:
    def __init__(self, mundo: Mundo) -> None:
        self.mundo = mundo
        self.lanzadas: list[dict[str, Any]] = []
        self.logs: dict[str, list[str]] = {}
        self._codigos: dict[str, int] = {}
        self.imagen_worker = f"{REPO}:{SHA}"

    def describe_services(self, cluster, services):
        return {"services": [{"taskDefinition": f"{ARN_TD}/campus-locator-dev-api:5"}]}

    def describe_task_definition(self, taskDefinition):
        familia = taskDefinition.rsplit("/", 1)[-1].split(":")[0]
        imagen = self.imagen_worker if familia == "campus-locator-dev-worker" else f"{REPO}:{SHA}"
        definicion = {
            "taskDefinitionArn": f"{ARN_TD}/{familia}:5",
            "containerDefinitions": [{"name": "app", "image": imagen}],
        }
        return {"taskDefinition": definicion}

    def run_task(self, **peticion):
        self.lanzadas.append(peticion)
        comando = peticion["overrides"]["containerOverrides"][0]["command"]
        assert comando[:4] == ["python", "-m", "app.cli", "limpiar-validacion"], comando
        ids = [comando[i + 1] for i, parte in enumerate(comando) if parte == "--video"]
        lineas, codigo = self.mundo.limpiar(ids, "--simular" in comando)
        id_tarea = f"tarea{len(self.lanzadas):028d}"
        familia = peticion["taskDefinition"].rsplit("/", 1)[-1].split(":")[0]
        self.logs[f"{comun.LOGS_TAREA[familia][1]}/app/{id_tarea}"] = lineas
        arn = f"arn:aws:ecs:us-east-1:{CUENTA}:task/campus-locator-dev/{id_tarea}"
        self._codigos[arn] = codigo
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def get_waiter(self, nombre):
        return type("Espera", (), {"wait": lambda self, **_: None})()

    def describe_tasks(self, cluster, tasks):
        contenedor = {"name": "app", "exitCode": self._codigos[tasks[0]]}
        return {"tasks": [{"taskDefinitionArn": "…", "containers": [contenedor]}]}

    def comandos(self) -> list[list[str]]:
        return [t["overrides"]["containerOverrides"][0]["command"][4:] for t in self.lanzadas]


class Logs:
    """CloudWatch falso: la primera lectura de cada stream llega sin la última línea (la de `LIMPIEZA`), como cuando
    el log aún no terminó de llegar."""

    def __init__(self, ecs: Ecs) -> None:
        self.ecs = ecs
        self.lecturas: dict[str, int] = {}

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        assert logGroupName == "/campus-locator/dev/worker"
        if nextToken:
            return {"events": [], "nextForwardToken": nextToken}
        self.lecturas[logStreamName] = self.lecturas.get(logStreamName, 0) + 1
        lineas = self.ecs.logs[logStreamName]
        if self.lecturas[logStreamName] == 1 and len(lineas) > 1:
            lineas = lineas[:-1]
        return {"events": [{"message": m} for m in lineas], "nextForwardToken": "f/1"}


class Sesion:
    def __init__(self, mundo: Mundo) -> None:
        self.ecs = Ecs(mundo)
        self.s3 = S3(mundo)
        self.logs = Logs(self.ecs)
        secreto = {"SecretString": json.dumps({"correo": "a@b.c", "password": "p"})}
        self.clientes = {
            "sts": type("Sts", (), {"get_caller_identity": lambda self: {"Account": CUENTA, "Arn": "arn:…/yo"}})(),
            "secretsmanager": type("Secretos", (), {"get_secret_value": lambda self, SecretId: secreto})(),
            "ecs": self.ecs,
            "logs": self.logs,
            "s3": self.s3,
        }

    def client(self, servicio):
        return self.clientes[servicio]


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    for variable in ("VALIDACION_API_URL", "VALIDACION_ADMIN_CORREO", "VALIDACION_ADMIN_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")

    def correr(mundo: Mundo, *argumentos: str, preparar=None) -> tuple[int, Sesion, dict, HttpS3]:
        sesion = Sesion(mundo)
        if preparar:
            preparar(sesion)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate21.Contexto("dev")
        http_s3 = HttpS3(mundo)
        ctx.http, ctx.http_s3 = mundo, http_s3
        ctx.dormir, ctx.ahora = mundo.reloj.dormir, mundo.reloj.local
        ctx.sello = "20261025-150000"
        informe = tmp_path / "informe.json"
        codigo = validate21.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8")), http_s3

    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def _detalle(informe: dict, id_: str) -> str:
    return next(c["detalle"] for c in informe["precondiciones"] + informe["comprobaciones"] if c["id"] == id_)


ORDEN = ["P1", "P2", "P3", "P4", "P5", "C1a", "C1b", "C1c", "C2a", "C2b", "C2c", "C3a", "C3b", "C4", "C5", "C6a", "C6b"]


def test_dev_completo_pasa_sin_imprimir_urls_ni_tokens(entorno_dev, capsys):
    mundo = Mundo()
    codigo, sesion, informe, http_s3 = entorno_dev(mundo)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert list(_estados(informe)) == ORDEN and set(_estados(informe).values()) == {"pasa"}
    texto = salida.out + salida.err + json.dumps(informe)
    for secreto in (FIRMA, TOKEN, "s3.amazonaws.com", "vence="):
        assert secreto not in texto
    assert "[PREPARACION] sin restos validacion- de ejecuciones anteriores" in salida.out
    assert '[LIMPIEZA] videos de prueba borrados: {"videos": 1, "objetos": 4}' in salida.out
    # C1b (3), C2c (1), C3a (403), C3b (1) y la foto del video -b (1)
    assert http_s3.puts == [200, 200, 200, 200, 403, 200, 200]
    assert mundo.reloj.dormido >= 900  # C3a esperó a que venciera la URL
    assert "estado procesando (el de §5.5)" in _detalle(informe, "C4")
    assert "head-object (404)" in _detalle(informe, "P4")
    comandos = sesion.ecs.comandos()
    assert len(comandos) == 3 and comandos[0][0] == "--video" and comandos[1][0] == "--video"
    assert all(t["taskDefinition"].endswith("campus-locator-dev-worker:5") for t in sesion.ecs.lanzadas)
    assert all(t["startedBy"] == "validate21" for t in sesion.ecs.lanzadas)
    # La línea LIMPIEZA llega en la segunda lectura del log: se reintentó.
    assert max(sesion.logs.lecturas.values()) == 2 and "LIMPIEZA" in _detalle(informe, "C6a")
    assert mundo.videos == {} and mundo.objetos == {}


def test_reloj_local_atrasado_no_adelanta_el_put_de_c3a(entorno_dev):
    mundo = Mundo(atraso_local_s=120)  # WSL dos minutos atrasado respecto a S3
    codigo, _, informe, http_s3 = entorno_dev(mundo)
    assert codigo == 0, informe
    assert "desfase local +120 s" in _detalle(informe, "C3a")
    assert http_s3.puts[4] == 403


def test_si_s3_acepta_la_url_vencida_c3a_falla_y_la_limpieza_borra_igual(entorno_dev, capsys):
    mundo = Mundo()
    mundo.urls_vencen = False
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 1
    assert _estados(informe)["C3a"] == "falla" and "dio 200" in _detalle(informe, "C3a")
    assert mundo.videos == {}
    assert "[LIMPIEZA] videos de prueba borrados" in capsys.readouterr().out


def test_restos_de_otra_ejecucion_se_borran_al_empezar(entorno_dev, capsys):
    mundo = Mundo()
    resto = mundo.nuevo_video("validacion-21-20261024-000000", "validacion-21-20261024-000000")
    mixto = mundo.nuevo_video("validacion-21-mixto", "rec_0002")  # sin el prefijo en ref_cliente: no es resto
    codigo, sesion, _, _ = entorno_dev(mundo)
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert '[PREPARACION] restos borrados: {"videos": 1, "objetos": 0}' in salida
    assert sesion.ecs.comandos()[0] == []  # sin --video
    assert resto["id"] not in mundo.videos and set(mundo.videos) == {mixto["id"]}
    # El mixto es «ajeno» para C6b: se prueba con --simular y sigue existiendo.
    assert ["--video", mixto["id"], "--simular"] in sesion.ecs.comandos()


def test_c6b_simula_con_un_video_ajeno_y_nunca_lanza_la_orden_real(entorno_dev):
    mundo = Mundo()
    real = mundo.nuevo_video("Entrada norte", "rec_0001")
    codigo, sesion, informe, _ = entorno_dev(mundo)
    assert codigo == 0, informe
    comandos = sesion.ecs.comandos()
    assert ["--video", real["id"], "--simular"] in comandos
    assert not [c for c in comandos if real["id"] in c and "--simular" not in c]
    assert "video ajeno n.º 1 con --simular → 1 y sigue existiendo" in _detalle(informe, "C6b")
    assert real["id"] in mundo.videos


def test_estado_de_complete_distinto_del_de_5_5_falla_c4(entorno_dev):
    mundo = Mundo()
    mundo.estado_fijo = "procesado"
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C4")
    assert codigo == 1
    assert "§5.5 exige 'procesando'" in _detalle(informe, "C4")


def test_sin_head_en_images_falla_c2b(entorno_dev):
    mundo = Mundo()
    mundo.head_en_images = False
    codigo, _, informe, _ = entorno_dev(mundo, "--solo", "C2")
    assert codigo == 1
    assert _estados(informe)["C2b"] == "falla"
    assert {_estados(informe)[c] for c in ("C2a", "C2c")} == {"pasa"}


def test_solo_c4_sube_la_foto_4_sin_esperar(entorno_dev):
    mundo = Mundo()
    codigo, _, informe, http_s3 = entorno_dev(mundo, "--solo", "C4,C5")
    assert codigo == 0, informe
    assert mundo.reloj.dormido < 60
    assert http_s3.puts == [200, 200, 200, 200]
    assert {_estados(informe)[c] for c in ORDEN if c.startswith("C") and c[:2] not in ("C4", "C5")} == {"omitida"}


def test_bucket_inexistente_es_codigo_2(entorno_dev):
    def sin_bucket(sesion):
        sesion.s3.bucket_existe = False

    codigo, sesion, informe, _ = entorno_dev(Mundo(), preparar=sin_bucket)
    assert codigo == 2
    assert _estados(informe)["P4"] == "falla" and not informe["comprobaciones"]
    assert sesion.ecs.lanzadas == []


def test_sin_permiso_para_listar_es_codigo_3_en_p4(entorno_dev):
    def sin_listar(sesion):
        sesion.s3.listar_denegado = True

    codigo, sesion, informe, _ = entorno_dev(Mundo(), preparar=sin_listar)
    assert codigo == 3
    assert "sin permiso para list-objects-v2" in _detalle(informe, "P4")
    assert sesion.ecs.lanzadas == [] and not informe["comprobaciones"]


def test_worker_con_otra_imagen_que_api_es_codigo_2_antes_de_crear_nada(entorno_dev):
    mundo = Mundo()

    def viejo(sesion):
        sesion.ecs.imagen_worker = f"{REPO}:viejo"

    codigo, sesion, informe, _ = entorno_dev(mundo, preparar=viejo)
    assert codigo == 2
    assert "imágenes distintas" in _detalle(informe, "P5")
    assert mundo.videos == {} and sesion.ecs.lanzadas == []


def test_estado_esperado_y_solo_avanzo_el_worker():
    conteo = {"pendiente_subida": 0, "subida": 4, "procesada": 0, "error": 0}
    assert validate21.estado_esperado(conteo) == "procesando"
    assert validate21.estado_esperado(conteo | {"subida": 0, "procesada": 4}) == "procesado"
    assert validate21.estado_esperado(conteo | {"subida": 0, "procesada": 3, "error": 1}) == "con_errores"
    assert validate21.estado_esperado(conteo | {"pendiente_subida": 1, "subida": 3}) == "pendiente"
    assert validate21.estado_esperado(conteo, subida_completa=False) == "pendiente"
    antes = conteo
    assert validate21._solo_avanzo_el_worker(antes, {"pendiente_subida": 0, "subida": 1, "procesada": 2, "error": 1})
    assert not validate21._solo_avanzo_el_worker(
        antes, {"pendiente_subida": 1, "subida": 3, "procesada": 0, "error": 0}
    )
    assert not validate21._solo_avanzo_el_worker(
        antes, {"pendiente_subida": 0, "subida": 4, "procesada": 1, "error": 0}
    )
