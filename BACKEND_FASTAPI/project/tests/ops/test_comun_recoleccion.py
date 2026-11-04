"""Ayudas de BE-2.1 en `src/ops/comun.py`: `jpeg_sintetico`, la CLI con la definición de `worker` y la `preparacion`
del `Validador` (backend ARCHITECTURE §5.11)."""

from __future__ import annotations

import json
import subprocess

import pytest

import comun
from comun import Validador


def _segmentos(datos: bytes) -> dict[int, bytes]:
    """Marcadores de cabecera de un JPEG hasta SOS: `{marcador: contenido}`."""
    assert datos[:2] == b"\xff\xd8" and datos[-2:] == b"\xff\xd9"
    segmentos, i = {}, 2
    while True:
        assert datos[i] == 0xFF
        marcador, largo = datos[i + 1], int.from_bytes(datos[i + 2 : i + 4], "big")
        segmentos.setdefault(marcador, datos[i + 4 : i + 2 + largo])
        i += 2 + largo
        if marcador == 0xDA:
            return segmentos


def test_jpeg_sintetico_baseline_con_sus_dimensiones():
    datos = comun.jpeg_sintetico(1024, 768, semilla=7)
    segmentos = _segmentos(datos)
    sof = segmentos[0xC0]
    assert sof[0] == 8 and int.from_bytes(sof[1:3], "big") == 768 and int.from_bytes(sof[3:5], "big") == 1024
    assert {0xE0, 0xDB, 0xC0, 0xC4, 0xDA} <= set(segmentos)
    assert 2_000 < len(datos) < 60_000
    assert comun.jpeg_sintetico(1024, 768, semilla=7) == datos
    assert comun.jpeg_sintetico(1024, 768, semilla=8) != datos
    # Dentro de los datos codificados, todo 0xFF va seguido de 0x00 (relleno) salvo el EOI final.
    cuerpo = datos[datos.index(b"\xff\xda") + 2 + int.from_bytes(datos[datos.index(b"\xff\xda") + 2 :][:2], "big") : -2]
    assert all(cuerpo[i + 1] == 0 for i in range(len(cuerpo) - 1) if cuerpo[i] == 0xFF)


def test_jpeg_sintetico_se_decodifica_con_pillow():
    imagen = pytest.importorskip("PIL.Image")
    import io

    foto = imagen.open(io.BytesIO(comun.jpeg_sintetico(1024, 768, semilla=3)))
    foto.load()
    assert (foto.format, foto.size, foto.mode) == ("JPEG", (1024, 768), "L")


def test_cli_con_la_familia_worker_en_local_usa_el_servicio_worker(monkeypatch):
    llamadas = []

    def proceso(argumentos, **kwargs):
        llamadas.append(argumentos)
        return subprocess.CompletedProcess(argumentos, 0, 'LIMPIEZA {"videos": 0, "objetos": 0}\n', "")

    monkeypatch.setattr(comun, "ejecutar_proceso", proceso)
    resultado = comun.EntornoBackend("local").cli(["limpiar-validacion"], familia=comun.FAMILIA_WORKER)
    assert llamadas == [
        ["docker", "compose", "run", "--rm", "-T", "worker", "python", "-m", "app.cli", "limpiar-validacion"]
    ]
    assert resultado.codigo == 0 and resultado.lineas == ['LIMPIEZA {"videos": 0, "objetos": 0}']


class _Ecs:
    def __init__(self, imagen_worker: str = "repo:sha") -> None:
        self.imagen_worker = imagen_worker
        self.lanzadas = []

    def describe_services(self, cluster, services):
        return {"services": [{"taskDefinition": "arn:td/campus-locator-dev-api:7"}]}

    def describe_task_definition(self, taskDefinition):
        familia = taskDefinition.rsplit("/", 1)[-1].split(":")[0]
        imagen = self.imagen_worker if familia == "campus-locator-dev-worker" else "repo:sha"
        return {
            "taskDefinition": {
                "taskDefinitionArn": f"arn:td/{familia}:7",
                "containerDefinitions": [{"name": "app", "image": imagen}],
            }
        }

    def run_task(self, **peticion):
        self.lanzadas.append(peticion)
        return {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:1:task/campus-locator-dev/abc"}]}

    def get_waiter(self, nombre):
        return type("Espera", (), {"wait": lambda self, **_: None})()

    def describe_tasks(self, cluster, tasks):
        return {"tasks": [{"containers": [{"name": "app", "exitCode": 0}]}]}


class _Logs:
    def __init__(self) -> None:
        self.pedidos = []

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        self.pedidos.append((logGroupName, logStreamName))
        return {"events": [{"message": json.dumps({"evento": "limpieza_validacion"})}], "nextForwardToken": None}


class _Sesion:
    def __init__(self, ecs, logs) -> None:
        self.clientes = {"ecs": ecs, "logs": logs}

    def client(self, servicio):
        return self.clientes[servicio]


OUTPUTS = {"subredes_tareas": ["subnet-a"], "sg_migrate": "sg-api"}


def test_cli_con_la_familia_worker_en_dev_lanza_la_revision_de_worker():
    ecs, logs = _Ecs(), _Logs()
    backend = comun.EntornoBackend("dev", sesion=_Sesion(ecs, logs), outputs=lambda: OUTPUTS, dormir=lambda _s: None)
    resultado = backend.cli(["limpiar-validacion", "--video", "x"], familia=comun.FAMILIA_WORKER)
    [peticion] = ecs.lanzadas
    assert peticion["taskDefinition"] == "arn:td/campus-locator-dev-worker:7"
    assert peticion["overrides"]["containerOverrides"][0]["command"][3:] == ["limpiar-validacion", "--video", "x"]
    assert logs.pedidos == [("/campus-locator/dev/worker", "worker/app/abc")]
    assert resultado.eventos("limpieza_validacion")


def test_cli_de_worker_con_otra_imagen_que_api_es_falla():
    backend = comun.EntornoBackend(
        "dev", sesion=_Sesion(_Ecs(imagen_worker="repo:viejo"), _Logs()), outputs=lambda: OUTPUTS
    )
    with pytest.raises(comun.Falla, match="imágenes distintas"):
        backend.cli(["limpiar-validacion"], familia=comun.FAMILIA_WORKER)


def test_motivo_cli_de_limpieza_rechazada():
    linea = json.dumps({"evento": "limpieza_rechazada", "motivo": "no existen: abc"})
    resultado = comun.ResultadoTarea(arn="x", definicion="d", codigo=1, motivo="", lineas=[linea])
    assert comun.motivo_cli(resultado) == "limpieza_rechazada: no existen: abc"


def test_preparacion_corre_tras_las_precondiciones_y_un_fallo_no_cambia_el_codigo(tmp_path, capsys):
    orden = []
    v = Validador(lote="BE-9.9", validacion="validation-9-9", entornos=("dev",))
    v.iniciar(["--entorno", "dev", "--informe", str(tmp_path / "i.json")])
    codigo = v.ejecutar(
        precondiciones=[("P1", lambda: orden.append("P1"))],
        preparacion=lambda: orden.append("prep") or "restos borrados",
        comprobaciones=[("C1", lambda: orden.append("C1"))],
    )
    assert (codigo, orden) == (0, ["P1", "prep", "C1"])
    assert "[PREPARACION] restos borrados" in capsys.readouterr().out

    def falla():
        raise RuntimeError("sin red")

    v = Validador(lote="BE-9.9", validacion="validation-9-9", entornos=("dev",))
    v.iniciar(["--entorno", "dev", "--informe", str(tmp_path / "j.json")])
    assert v.ejecutar(precondiciones=[], preparacion=falla, comprobaciones=[("C1", lambda: "ok")]) == 0
    assert "[PREPARACION] falló: RuntimeError: sin red" in capsys.readouterr().out


def test_sin_precondiciones_cumplidas_no_hay_preparacion(tmp_path):
    orden = []

    def bloqueo():
        raise comun.PrecondicionNoCumplida("otro lote")

    v = Validador(lote="BE-9.9", validacion="validation-9-9", entornos=("dev",))
    v.iniciar(["--entorno", "dev", "--informe", str(tmp_path / "i.json")])
    assert (
        v.ejecutar(precondiciones=[("P1", bloqueo)], preparacion=lambda: orden.append("prep"), comprobaciones=[]) == 2
    )
    assert orden == []


# --- Ayudas de recolección (BE-2.1) ----------------------------------------------------------------------------------
def _error_aws(codigo: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")


class _HttpQueRompe:
    def request(self, *a, **k):
        raise RuntimeError("fallo con https://bucket.s3.amazonaws.com/clave?X-Amz-Signature=secreta")


def test_put_prefirmado_no_deja_la_url_en_el_error():
    subida = {"url": "https://bucket.s3.amazonaws.com/clave?X-Amz-Signature=secreta", "encabezados": {"A": "b"}}
    with pytest.raises(comun.Falla) as error:
        comun.put_prefirmado(_HttpQueRompe(), subida, b"x", que="la foto 1")
    assert str(error.value) == "PUT de la foto 1: RuntimeError (sin respuesta de S3)"


class _S3:
    def __init__(self, *, head=None, listar=None, bucket=None, fecha="Sun, 25 Oct 2026 15:00:10 GMT") -> None:
        self.head, self.listar, self.bucket, self.fecha = head, listar, bucket, fecha
        self.objetos = {"dataset/v/1.jpg": {"ContentLength": 3}}

    def head_bucket(self, Bucket):
        if self.bucket:
            raise _error_aws(self.bucket)
        return {"ResponseMetadata": {"HTTPHeaders": {"date": self.fecha} if self.fecha else {}}}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        if self.listar:
            raise _error_aws(self.listar)
        return {}

    def head_object(self, Bucket, Key):
        if self.head:
            raise _error_aws(self.head)
        if Key not in self.objetos:
            raise _error_aws("404")
        return self.objetos[Key]

    def get_paginator(self, nombre):
        objetos, listar = self.objetos, self.listar

        class Paginador:
            def paginate(self, Bucket, Prefix):
                if listar:
                    raise _error_aws(listar)
                return [{"Contents": [{"Key": k} for k in objetos if k.startswith(Prefix)]}, {}]

        return Paginador()


def test_head_objeto_y_claves():
    assert comun.head_objeto(_S3(), "b", "dataset/v/1.jpg") == {"ContentLength": 3}
    assert comun.head_objeto(_S3(), "b", "dataset/v/2.jpg") is None
    with pytest.raises(comun.ErrorConfiguracion):
        comun.head_objeto(_S3(head="403"), "b", "dataset/v/1.jpg")
    with pytest.raises(comun.Falla):
        comun.head_objeto(_S3(head="SlowDown"), "b", "dataset/v/1.jpg")
    assert comun.claves_s3(_S3(), "b", "dataset/v/") == ["dataset/v/1.jpg"]
    with pytest.raises(comun.ErrorConfiguracion):
        comun.claves_s3(_S3(listar="AccessDenied"), "b", "dataset/")


def test_comprobar_bucket_distingue_bloqueo_y_permisos():
    assert "head-object (404)" in comun.comprobar_bucket(_S3(), "b")
    with pytest.raises(comun.PrecondicionNoCumplida):
        comun.comprobar_bucket(_S3(bucket="404"), "b")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.comprobar_bucket(_S3(bucket="403"), "b")
    with pytest.raises(comun.ErrorConfiguracion, match="list-objects-v2"):
        comun.comprobar_bucket(_S3(listar="AccessDenied"), "b")
    with pytest.raises(comun.ErrorConfiguracion, match="head-object"):
        comun.comprobar_bucket(_S3(head="403"), "b")


def test_hora_y_desfase_de_s3():
    from datetime import UTC, datetime

    assert comun.hora_s3(_S3(), "b") == datetime(2026, 10, 25, 15, 0, 10, tzinfo=UTC)
    local = datetime(2026, 10, 25, 14, 58, 10, tzinfo=UTC)  # dos minutos atrasado
    assert comun.desfase_s3_s(_S3(), "b", lambda: local) == 120
    with pytest.raises(comun.Falla, match="Date"):
        comun.hora_s3(_S3(fecha=None), "b")


def test_fin_limpieza_y_linea_limpieza():
    evento = json.dumps({"evento": "limpieza_validacion", "videos": 1})
    assert not comun.fin_limpieza(0, [evento])
    assert comun.fin_limpieza(0, [evento, 'LIMPIEZA {"videos": 1, "objetos": 2}'])
    assert comun.fin_limpieza(0, ['SIMULACION {"videos": 0, "objetos": 0}'])
    assert comun.fin_limpieza(1, [json.dumps({"evento": "limpieza_rechazada"})])
    assert not comun.fin_limpieza(1, [json.dumps({"evento": "log"})])
    assert comun.fin_limpieza(None, [])
    tarea = comun.ResultadoTarea(
        arn="x", definicion="d", codigo=0, motivo="", lineas=[evento, 'LIMPIEZA {"videos": 1}']
    )
    assert comun.linea_limpieza(tarea) == {"videos": 1}
    assert comun.linea_limpieza(tarea, comun.LINEA_SIMULACION) is None
    roto = comun.ResultadoTarea(arn="x", definicion="d", codigo=0, motivo="", lineas=["LIMPIEZA {roto"])
    assert comun.linea_limpieza(roto) is None


def test_limpiar_videos_arma_el_comando_y_una_lista_vacia_no_lanza_nada():
    class Backend:
        def __init__(self) -> None:
            self.llamadas = []

        def cli(self, argumentos, *, familia, log_completo):
            self.llamadas.append((argumentos, familia, log_completo))
            return comun.ResultadoTarea(arn="x", definicion="d", codigo=0, motivo="")

    backend = Backend()
    assert comun.limpiar_videos(backend, []).codigo == 0 and backend.llamadas == []
    comun.limpiar_videos(backend, None)
    comun.limpiar_videos(backend, ["a", "b"], simular=True)
    assert [a for a, _, _ in backend.llamadas] == [
        ["limpiar-validacion"],
        ["limpiar-validacion", "--video", "a", "--video", "b", "--simular"],
    ]
    assert all(f == comun.FAMILIA_WORKER and c is comun.fin_limpieza for _, f, c in backend.llamadas)


def test_leer_log_reintenta_hasta_que_esta_completo():
    class LogsPorTandas:
        def __init__(self) -> None:
            self.n = 0

        def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
            self.n += 1
            mensajes = ["evento"] if self.n < 3 else ["evento", "LIMPIEZA {}"]
            return {"events": [{"message": m} for m in mensajes], "nextForwardToken": None}

    logs, pausas = LogsPorTandas(), []
    lineas = comun.leer_log(logs, "g", "s", dormir=pausas.append, completo=lambda m: "LIMPIEZA {}" in m)
    assert lineas == ["evento", "LIMPIEZA {}"] and logs.n == 3 and len(pausas) == 2
    # Si nunca se completa, devuelve lo último leído tras agotar los intentos.
    logs = LogsPorTandas()
    assert comun.leer_log(logs, "g", "s", intentos=2, dormir=lambda _s: None, completo=lambda m: False) == ["evento"]


class _ApiFalsa:
    """Listado paginado de `GET /v1/admin/videos` y la recolección mínima para `RecorridoPrueba`."""

    def __init__(self, videos: list[dict]) -> None:
        self.videos = videos
        self.pedidos: list[tuple[str, str, dict]] = []
        self.registradas: dict[int, int] = {}

    def pedir(self, metodo, ruta, *, token=None, params=None, json=None):
        self.pedidos.append((metodo, ruta, params or json or {}))

        class R:
            def __init__(self, estado, cuerpo):
                self.status_code, self._c = estado, cuerpo

            def json(self):
                return self._c

        if ruta == "/admin/videos":
            pagina, por_pagina = params["pagina"], params["por_pagina"]
            items = self.videos[(pagina - 1) * por_pagina : pagina * por_pagina]
            return R(200, {"items": items, "total": len(self.videos), "pagina": pagina, "por_pagina": por_pagina})
        if ruta == "/collect/videos":
            return R(201, {"id": "v1", "nombre": json["nombre"]})
        if ruta.endswith("/images"):
            imagenes = []
            for elemento in json["imagenes"]:
                n = self.registradas[elemento["orden"]] = self.registradas.get(elemento["orden"], 0) + 1
                subida = {"metodo": "PUT", "url": f"https://x/{elemento['orden']}/{n}", "encabezados": {}}
                imagenes.append({"orden": elemento["orden"], "id": f"i{elemento['orden']}", "subida": subida})
            return R(200, {"imagenes": imagenes})
        raise AssertionError(ruta)


def test_videos_validacion_recorre_todas_las_paginas_y_exige_los_dos_prefijos():
    videos = [{"nombre": f"validacion-{n}", "ref_cliente": f"validacion-{n}"} for n in range(150)]
    videos.append({"nombre": "validacion-mixto", "ref_cliente": "rec_1"})
    api = _ApiFalsa(videos)
    encontrados = comun.videos_validacion(api, "t")
    assert len(encontrados) == 150 and [p[2]["pagina"] for p in api.pedidos] == [1, 2]


def test_recorrido_prueba_asegura_las_subidas_pidiendo_url_nueva():
    class Http:
        def __init__(self) -> None:
            self.urls = []

        def request(self, metodo, url, headers=None, content=b""):
            self.urls.append(url)
            return type("R", (), {"status_code": 200, "text": ""})()

        def close(self) -> None:
            pass

    api, http = _ApiFalsa([]), Http()
    with pytest.raises(comun.Falla, match="validacion-"):
        comun.RecorridoPrueba(api, lambda: "t", "otro-nombre")
    recorrido = comun.RecorridoPrueba(api, lambda: "t", "validacion-x", http_s3=http, semilla=7)
    assert recorrido.crear().status_code == 201 and recorrido.video_id == "v1"
    recorrido.registrar([1, 2])
    recorrido.subir(1)
    recorrido.asegurar_subidas([1, 2, 3])  # 2 y 3: se registran otra vez (URL nueva) y se suben
    assert recorrido.subidas == {1, 2, 3}
    assert http.urls == ["https://x/1/1", "https://x/2/2", "https://x/3/1"]
    assert recorrido.foto(1) == comun.jpeg_sintetico(1024, 768, semilla=7001)
    assert recorrido.elemento(2)["bytes"] == len(recorrido.foto(2)) and recorrido.elemento(2)["rumbo"] == 90.0
