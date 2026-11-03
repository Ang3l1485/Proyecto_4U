"""Validador de BE-1.2 con AWS, HTTP y Docker simulados (validation-1-2.md)."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

pytest.importorskip("botocore")  # grupo `ops`; CI lo instala (`uv sync --frozen --group ops`)

import comun
import validate12

CUENTA = "648617469176"
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = f"{CUENTA}.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend"
ARN_TD = f"arn:aws:ecs:us-east-1:{CUENTA}:task-definition"
OUTPUTS = {
    "api_base_url": "https://abc123.execute-api.us-east-1.amazonaws.com",
    "subredes_tareas": ["subnet-0a"],
    "sg_migrate": "sg-0api",
}
CORREO = "admin@campus.edu.co"
SESION_AWS_REAL = comun.sesion_aws
PASSWORD_SECRETO = "NoDebeAparecer-123"


def _linea(evento: str, **campos: Any) -> str:
    return json.dumps(
        {"ts": "…", "nivel": "INFO", "proceso": "migrate", "request_id": None, "evento": evento, **campos}
    )


MIGRAR_OK = [
    _linea("migracion_iniciada", revision_objetivo="0001"),
    _linea(
        "migracion_terminada", revision_anterior="0001", revision="0001", aplicada=False, admin_inicial="ya_habia_admin"
    ),
]
VERIFICAR_OK = [
    _linea(
        "esquema_verificado", resultado="coincide", diferencias=0, revision="0001", servidor="17.9", pgvector="0.8.1"
    )
]


class Respuesta:
    def __init__(self, estado: int, cuerpo: Any) -> None:
        self.status_code = estado
        self._cuerpo = cuerpo

    def json(self) -> Any:
        return self._cuerpo


class Http:
    def __init__(self, ready: Respuesta | None = None) -> None:
        self.ready = ready or Respuesta(200, {"estado": "ok", "db": "ok", "embedding": "no_disponible"})

    def get(self, url: str, **_: Any) -> Respuesta:
        if url.endswith("/health"):
            return Respuesta(200, {"estado": "ok", "version": "0.1.0", "commit": SHA[:7]})
        if url.endswith("/health/ready"):
            return self.ready
        return Respuesta(404, {})

    def close(self) -> None:
        pass


class Ecs:
    """ECS falso: cada `run_task` se clasifica (migrar, verificar o psql) y responde según `salidas`."""

    def __init__(self, salidas: dict[str, list[tuple[int | None, list[str]]]], imagen_migrate: str | None = None):
        self.salidas = {tipo: list(lista) for tipo, lista in salidas.items()}
        self.imagen_migrate = imagen_migrate or f"{REPO}:{SHA}"
        self.lanzadas: list[dict[str, Any]] = []
        self.logs: dict[str, list[str]] = {}
        self._codigos: dict[str, tuple[int | None, str]] = {}

    def describe_services(self, cluster, services):
        return {"services": [{"taskDefinition": f"{ARN_TD}/campus-locator-dev-api:3"}]}

    def describe_task_definition(self, taskDefinition):
        imagenes = {
            "campus-locator-dev-api": (f"{ARN_TD}/campus-locator-dev-api:3", f"{REPO}:{SHA}"),
            "campus-locator-dev-migrate": (f"{ARN_TD}/campus-locator-dev-migrate:4", self.imagen_migrate),
            "campus-locator-dev-validacion": (f"{ARN_TD}/campus-locator-dev-validacion:1", "postgres:17-alpine"),
        }
        familia = taskDefinition.rsplit("/", 1)[-1].split(":")[0]
        arn, imagen = imagenes[familia]
        return {
            "taskDefinition": {"taskDefinitionArn": arn, "containerDefinitions": [{"name": "app", "image": imagen}]}
        }

    def run_task(self, **peticion):
        self.lanzadas.append(peticion)
        comando = (peticion.get("overrides") or {}).get("containerOverrides", [{}])[0].get("command")
        tipo = "migrar" if comando is None else ("psql" if comando[0] == "psql" else "verificar")
        codigo, lineas = self.salidas[tipo].pop(0)
        id_tarea = f"tarea{len(self.lanzadas):028d}"
        familia = peticion["taskDefinition"].rsplit("/", 1)[-1].split(":")[0]
        prefijo = comun.LOGS_TAREA[familia][1]
        self.logs[f"{prefijo}/app/{id_tarea}"] = lineas
        arn = f"arn:aws:ecs:us-east-1:{CUENTA}:task/campus-locator-dev/{id_tarea}"
        self._codigos[arn] = (codigo, "Essential container in task exited" if codigo is not None else "")
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def get_waiter(self, nombre):
        assert nombre == "tasks_stopped"
        return type("Espera", (), {"wait": lambda self, **_: None})()

    def describe_tasks(self, cluster, tasks):
        codigo, motivo = self._codigos[tasks[0]]
        contenedor = {"name": "app"}
        if codigo is not None:
            contenedor["exitCode"] = codigo
        else:
            contenedor["reason"] = "CannotPullContainerError: imagen no encontrada"
        return {"tasks": [{"taskDefinitionArn": "…", "containers": [contenedor], "stoppedReason": motivo}]}


class Logs:
    def __init__(self, ecs: Ecs) -> None:
        self.ecs = ecs

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        if nextToken:
            return {"events": [], "nextForwardToken": nextToken}
        mensajes = self.ecs.logs[logStreamName]
        return {"events": [{"message": m} for m in mensajes], "nextForwardToken": "f/1"}


class Rds:
    def __init__(self, version: str = "17.9", estado: str = "available") -> None:
        self.version, self.estado = version, estado

    def describe_db_instances(self, DBInstanceIdentifier):
        return {"DBInstances": [{"DBInstanceStatus": self.estado, "EngineVersion": self.version}]}


class Secretos:
    def describe_secret(self, SecretId):
        return {"Name": SecretId}

    def get_secret_value(self, SecretId):
        assert SecretId == "campus-locator/dev/admin-inicial"
        return {"SecretString": json.dumps({"correo": "Admin@Campus.edu.co", "password": PASSWORD_SECRETO})}


def _contexto(ecs: Ecs, rds: Rds | None = None, http: Http | None = None, outputs=None) -> validate12.Contexto:
    ctx = validate12.Contexto("dev")
    ctx._clientes = {"ecs": ecs, "logs": Logs(ecs), "rds": rds or Rds(), "secretsmanager": Secretos()}
    ctx._http = http or Http()
    ctx._outputs = OUTPUTS if outputs is None else outputs
    ctx.dormir = lambda _s: None
    return ctx


@pytest.fixture(autouse=True)
def aws_simulado(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.delenv("VALIDACION_API_URL", raising=False)
    monkeypatch.setattr(comun, "sesion_aws", lambda: object())
    monkeypatch.setattr(comun, "verificar_cuenta", lambda _s: f"arn:aws:iam::{CUENTA}:user/validacion")


def _salidas(**cambios):
    salidas = {
        "migrar": [(0, MIGRAR_OK), (0, MIGRAR_OK)],
        "verificar": [(0, VERIFICAR_OK)],
        "psql": [(0, ["1"])],
    }
    salidas.update(cambios)
    return salidas


def _correr(tmp_path, ctx, *argumentos):
    informe = tmp_path / "informe.json"
    codigo = validate12.main(["--entorno", ctx.entorno, "--informe", str(informe), *argumentos], ctx=ctx)
    return codigo, json.loads(informe.read_text(encoding="utf-8"))


def _detalle(informe, id_):
    return next(c for c in informe["comprobaciones"] if c["id"] == id_)


def test_dev_todo_pasa(tmp_path, capsys):
    ecs = Ecs(_salidas())
    codigo, informe = _correr(tmp_path, _contexto(ecs))
    assert codigo == 0, informe
    assert [p["id"] for p in informe["precondiciones"]] == ["P1", "P2", "P3", "P4"]
    assert [c["estado"] for c in informe["comprobaciones"]] == ["pasa"] * 4
    tipos = [
        (p["taskDefinition"], (p.get("overrides") or {}).get("containerOverrides", [{}])[0].get("command"))
        for p in ecs.lanzadas
    ]
    revision = f"{ARN_TD}/campus-locator-dev-migrate:4"
    assert tipos[:3] == [(revision, None), (revision, None), (revision, validate12.COMANDO_VERIFICAR)]
    assert tipos[3][0] == "campus-locator-dev-validacion"
    assert tipos[3][1][:2] == ["psql", "-tAc"]
    assert f"correo = '{CORREO}'" in tipos[3][1][2]  # normalizado a minúsculas
    for peticion in ecs.lanzadas:
        assert peticion["launchType"] == "FARGATE"
        assert peticion["cluster"] == "campus-locator-dev"
        assert peticion["startedBy"] == "validate12"
        assert peticion["networkConfiguration"] == {
            "awsvpcConfiguration": {
                "subnets": ["subnet-0a"],
                "securityGroups": ["sg-0api"],
                "assignPublicIp": "ENABLED",
            }
        }
    assert "pgvector 0.8.1" in _detalle(informe, "C2")["detalle"]
    salida = capsys.readouterr().out
    assert PASSWORD_SECRETO not in salida
    assert PASSWORD_SECRETO not in json.dumps(informe)


def test_c2_difiere_copia_las_diferencias(tmp_path):
    diferencias = [
        _linea(
            "esquema_diferencia", objeto="columna alertas.radio_m", aspecto="defecto", esperado="15", encontrado=None
        ),
        _linea("esquema_diferencia", objeto="tabla sobrante", aspecto="sobra", esperado=None, encontrado="sobrante"),
        _linea("esquema_verificado", resultado="difiere", diferencias=2),
    ]
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(verificar=[(1, diferencias)]))))
    assert codigo == 1
    detalle = _detalle(informe, "C2")
    assert detalle["estado"] == "falla"
    assert "difiere en 2" in detalle["detalle"]
    assert "columna alertas.radio_m defecto (15 → None)" in detalle["detalle"]
    assert "tabla sobrante sobra" in detalle["detalle"]


def test_c2_sin_conexion_no_es_difiere(tmp_path):
    caida = [_linea("base_no_disponible", motivo="TimeoutError")]
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(verificar=[(2, caida)]))))
    assert codigo == 1
    assert _detalle(informe, "C2")["detalle"] == "verificar-esquema terminó con 2: base_no_disponible: TimeoutError"


def test_c1_falla_si_migrar_falla_con_su_motivo(tmp_path):
    fallo = [_linea("migracion_fallida", motivo="DuplicateObjectError: type rol_usuario already exists")]
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(migrar=[(1, fallo)]))), "--solo", "C1")
    assert codigo == 1
    assert "migrar #1" in _detalle(informe, "C1")["detalle"]
    assert "DuplicateObjectError" in _detalle(informe, "C1")["detalle"]


def test_c1_falla_si_el_segundo_migrar_aplica_algo(tmp_path):
    aplica = [_linea("migracion_terminada", revision_anterior=None, revision="0001", aplicada=True)]
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(migrar=[(0, aplica), (0, aplica)]))), "--solo", "C1")
    assert codigo == 1
    assert "volvió a aplicar" in _detalle(informe, "C1")["detalle"]


def test_c1_contenedor_que_no_arranca(tmp_path):
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(migrar=[(None, [])]))), "--solo", "C1")
    assert codigo == 1
    assert "CannotPullContainerError" in _detalle(informe, "C1")["detalle"]


def test_migrate_con_otra_imagen_que_api(tmp_path):
    ecs = Ecs(_salidas(), imagen_migrate=f"{REPO}:bootstrap")
    codigo, informe = _correr(tmp_path, _contexto(ecs), "--solo", "C1,C2")
    assert codigo == 1
    assert "bootstrap" in _detalle(informe, "C1")["detalle"]
    assert _detalle(informe, "C2")["estado"] == "falla"
    assert ecs.lanzadas == []


def test_c3_falla_sin_admin(tmp_path):
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas(psql=[(0, ["0"])]))), "--solo", "C3")
    assert codigo == 1
    assert "hay 0 admin(s)" in _detalle(informe, "C3")["detalle"]


def test_c4_falla_con_503(tmp_path):
    ready = Respuesta(503, {"error": {"codigo": "BASE_NO_DISPONIBLE", "mensaje": "…", "detalle": None}})
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas()), http=Http(ready)), "--solo", "C4")
    assert codigo == 1
    assert _detalle(informe, "C4")["detalle"] == "/v1/health/ready respondió 503 BASE_NO_DISPONIBLE"


@pytest.mark.parametrize(("version", "estado"), [("16.4", "available"), ("17.9", "modifying")])
def test_p3_rds_no_listo_bloquea(tmp_path, version, estado):
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas()), rds=Rds(version, estado)))
    assert codigo == 2
    assert informe["resultado"] == "bloqueado"
    assert informe["comprobaciones"] == []


def test_p4_sin_outputs_de_red_bloquea(tmp_path):
    outputs = {"api_base_url": OUTPUTS["api_base_url"]}
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas()), outputs=outputs))
    assert codigo == 2
    assert "subredes_tareas" in informe["precondiciones"][-1]["detalle"]


def test_sin_aws_profile_termina_con_3(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_PROFILE")
    monkeypatch.setattr(comun, "sesion_aws", SESION_AWS_REAL)
    codigo, informe = _correr(tmp_path, _contexto(Ecs(_salidas())))
    assert codigo == 3
    assert "AWS_PROFILE" in informe["precondiciones"][0]["detalle"]


# --- local -------------------------------------------------------------------------------------------------------
@pytest.fixture
def compose(monkeypatch):
    """`docker compose` falso: registra los comandos y responde según `respuestas`."""
    llamadas: list[list[str]] = []
    respuestas = {
        "ps": json.dumps({"Service": "db", "State": "running"})
        + "\n"
        + json.dumps({"Service": "api", "State": "running"}),
        "migrar": "\n".join(MIGRAR_OK),
        "verificar-esquema": "\n".join(VERIFICAR_OK),
        "psql": "1\n",
    }
    codigos = {"migrar": 0, "verificar-esquema": 0, "psql": 0, "ps": 0}

    def ejecutar(argumentos, *, cwd=None, timeout=600):
        llamadas.append(list(argumentos))
        assert cwd == comun.RAIZ_PROYECTO
        clave = "ps" if argumentos[2] == "ps" else ("psql" if "psql" in argumentos else argumentos[-1])
        return subprocess.CompletedProcess(argumentos, codigos[clave], respuestas[clave], "")

    monkeypatch.setattr(comun, "ejecutar_proceso", ejecutar)
    monkeypatch.setenv("VALIDACION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", CORREO)
    return llamadas, respuestas, codigos


def _contexto_local() -> validate12.Contexto:
    ctx = validate12.Contexto("local")
    ctx._http = Http()
    return ctx


def test_local_todo_pasa(tmp_path, compose):
    llamadas, _, _ = compose
    codigo, informe = _correr(tmp_path, _contexto_local())
    assert codigo == 0, informe
    assert [p["id"] for p in informe["precondiciones"]] == ["P2", "P5"]
    comandos = [" ".join(c) for c in llamadas]
    assert comandos[1:3] == ["docker compose run --rm -T api python -m app.cli migrar"] * 2
    assert comandos[3] == "docker compose run --rm -T api python -m app.cli verificar-esquema"
    assert comandos[4].startswith("docker compose exec -T db psql -U campus_app -d campus_locator -tAc SELECT")


def test_local_verificar_difiere(tmp_path, compose):
    _, respuestas, codigos = compose
    codigos["verificar-esquema"] = 1
    respuestas["verificar-esquema"] = _linea(
        "esquema_diferencia", objeto="tabla usuarios", aspecto="falta", esperado="usuarios", encontrado=None
    )
    codigo, informe = _correr(tmp_path, _contexto_local())
    assert codigo == 1
    assert "tabla usuarios falta" in _detalle(informe, "C2")["detalle"]


def test_local_sin_compose_en_marcha_bloquea(tmp_path, compose):
    _, respuestas, _ = compose
    respuestas["ps"] = json.dumps({"Service": "db", "State": "running"})
    codigo, informe = _correr(tmp_path, _contexto_local())
    assert codigo == 2
    assert "api" in informe["precondiciones"][-1]["detalle"]


def test_local_sin_url_termina_con_3(tmp_path, compose, monkeypatch):
    monkeypatch.delenv("VALIDACION_API_URL")
    codigo, _ = _correr(tmp_path, _contexto_local())
    assert codigo == 3
