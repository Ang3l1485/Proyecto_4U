"""Validador de BE-1.3 con AWS, HTTP y Docker simulados (validation-1-3.md).

La API falsa implementa el contrato de ARCHITECTURE §5.2 y §5.3 firmando y comprobando con `app.seguridad.tokens`, así
el validador (que hace el HMAC a mano) se prueba contra la misma lógica que despliega el backend.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
import uuid
from typing import Any

import pytest

pytest.importorskip("botocore")  # grupo `ops`

import jwt
from pydantic import SecretStr

import comun
import validate13
from app.config import Settings
from app.seguridad import tokens

CUENTA = "648617469176"
SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = f"{CUENTA}.dkr.ecr.us-east-1.amazonaws.com/campus-locator/backend"
ARN_TD = f"arn:aws:ecs:us-east-1:{CUENTA}:task-definition"
OUTPUTS = {
    "api_base_url": "https://abc123.execute-api.us-east-1.amazonaws.com",
    "subredes_tareas": ["subnet-0a"],
    "sg_migrate": "sg-0api",
}
CLAVE = base64.b64encode(bytes(range(64))).decode()
ADMIN, PASSWORD_ADMIN = "admin@campus.edu.co", "SecretoAdmin1234567890ab"
CUERPO_401 = {
    "error": {"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "Correo o contraseña incorrectos.", "detalle": None}
}


class Respuesta:
    def __init__(self, estado: int, cuerpo: Any, encabezados: dict[str, str] | None = None) -> None:
        self.status_code = estado
        self._cuerpo = cuerpo
        self.headers = encabezados or {}

    def json(self) -> Any:
        return self._cuerpo


def _error(estado: int, codigo: str) -> Respuesta:
    return Respuesta(estado, {"error": {"codigo": codigo, "mensaje": "…", "detalle": None}})


class ApiFalsa:
    """`/health/ready`, `/auth/login` y `/admin/stats/uso` según §5.2 y §5.3."""

    def __init__(self, *, clave_firma: str | bytes = CLAVE, n_429: int = 0, mira_activo: bool = True) -> None:
        self.ajustes = Settings(jwt_secret=SecretStr(CLAVE))
        self.clave_firma = clave_firma
        self.usuarios: dict[str, dict[str, Any]] = {
            ADMIN: {
                "id": str(uuid.uuid4()),
                "nombre": "Administrador",
                "rol": "admin",
                "pw": PASSWORD_ADMIN,
                "activo": True,
            }
        }
        self.n_429 = n_429
        self.mira_activo = mira_activo
        self.cuerpo_401_inexistente = CUERPO_401
        self.auditoria: list[tuple[str | None, str]] = []
        self.rutas: list[str] = []

    def _por_id(self, usuario_id: str) -> dict[str, Any] | None:
        return next((u for u in self.usuarios.values() if u["id"] == usuario_id), None)

    def request(self, metodo: str, url: str, headers: dict | None = None, json: dict | None = None, **_: Any):
        ruta = url.split("/v1", 1)[1]
        self.rutas.append(f"{metodo} {ruta}")
        if ruta == "/health/ready":
            return Respuesta(
                200,
                {"estado": "ok", "db": "ok", "embedding": "no_disponible"},
                {"date": "Sun, 25 Oct 2026 15:00:00 GMT"},
            )
        if ruta == "/auth/login":
            if self.n_429:
                self.n_429 -= 1
                return Respuesta(429, {"message": "Too Many Requests"})
            correo = json["identificador"].strip().lower()
            usuario = self.usuarios.get(correo)
            if usuario and usuario["pw"] == json["password"] and usuario["activo"]:
                self.auditoria.append((usuario["id"], '{"resultado": "exito"}'))
                datos = {"iss": tokens.EMISOR, "sub": usuario["id"], "rol": usuario["rol"], "nombre": usuario["nombre"]}
                ahora = int(time.time())
                datos |= {"iat": ahora, "exp": ahora + 43200, "jti": str(uuid.uuid4())}
                token = jwt.encode(datos, self.clave_firma, algorithm="HS256")
                expira = validate13._iso(datos["exp"])
                cuerpo = {"id": usuario["id"], "nombre": usuario["nombre"], "correo": correo, "rol": usuario["rol"]}
                return Respuesta(200, {"token": token, "expira_en": expira, "usuario": cuerpo})
            self.auditoria.append((None, '{"motivo": "x", "resultado": "fallo"}'))
            return Respuesta(401, CUERPO_401 if usuario else self.cuerpo_401_inexistente)
        if ruta == "/admin/stats/uso":
            token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
            try:
                claims = tokens.decodificar(token, self.ajustes)
            except tokens.TokenExpirado:
                return _error(401, "TOKEN_EXPIRADO")
            except tokens.TokenInvalido:
                return _error(401, "TOKEN_INVALIDO")
            usuario = self._por_id(str(claims.sub))
            if usuario is None or (self.mira_activo and not usuario["activo"]):
                return _error(401, "TOKEN_INVALIDO")
            if usuario["rol"] != "admin":
                return _error(403, "SIN_PERMISOS")
            return _error(501, "NO_IMPLEMENTADO")
        return _error(404, "NO_ENCONTRADO")

    def close(self) -> None:
        pass


def _linea(evento: str, **campos: Any) -> str:
    return json.dumps(
        {"ts": "…", "nivel": "INFO", "proceso": "migrate", "request_id": None, "evento": evento, **campos}
    )


class Ecs:
    """ECS falso: `crear-usuario` y `desactivar-usuario` cambian el usuario de la API falsa; `psql` cuenta la
    auditoría."""

    def __init__(self, api: ApiFalsa) -> None:
        self.api = api
        self.lanzadas: list[dict[str, Any]] = []
        self.logs: dict[str, list[str]] = {}
        self._codigos: dict[str, int] = {}

    def describe_services(self, cluster, services):
        return {"services": [{"taskDefinition": f"{ARN_TD}/campus-locator-dev-api:3"}]}

    def describe_task_definition(self, taskDefinition):
        imagenes = {
            "campus-locator-dev-api": (f"{ARN_TD}/campus-locator-dev-api:3", f"{REPO}:{SHA}"),
            "campus-locator-dev-migrate": (f"{ARN_TD}/campus-locator-dev-migrate:4", f"{REPO}:{SHA}"),
            "campus-locator-dev-validacion": (f"{ARN_TD}/campus-locator-dev-validacion:1", "postgres:17-alpine"),
        }
        arn, imagen = imagenes[taskDefinition.rsplit("/", 1)[-1].split(":")[0]]
        return {
            "taskDefinition": {"taskDefinitionArn": arn, "containerDefinitions": [{"name": "app", "image": imagen}]}
        }

    def run_task(self, **peticion):
        self.lanzadas.append(peticion)
        sobrescritura = peticion["overrides"]["containerOverrides"][0]
        comando = sobrescritura["command"]
        entorno = {v["name"]: v["value"] for v in sobrescritura.get("environment", [])}
        if comando[0] == "psql":
            fallos = sum(1 for actor, _ in self.api.auditoria if actor is None)
            exitos = len(self.api.auditoria) - fallos
            lineas, codigo = [f"{fallos}|{exitos}|0"], 0
        elif comando[3] == "crear-usuario":
            correo = comando[comando.index("--correo") + 1]
            previo = self.api.usuarios.get(correo, {"id": str(uuid.uuid4())})
            self.api.usuarios[correo] = previo | {
                "nombre": "validacion-usuario",
                "rol": "user",
                "pw": entorno["CREAR_USUARIO_PASSWORD"],
                "activo": True,
            }
            lineas, codigo = [_linea("usuario_guardado", resultado="creado", usuario_id=previo["id"])], 0
        elif comando[3] == "desactivar-usuario" and comando[comando.index("--correo") + 1] not in self.api.usuarios:
            lineas, codigo = [_linea("usuario_no_encontrado")], 1
        elif comando[3] == "desactivar-usuario":
            usuario = self.api.usuarios[comando[comando.index("--correo") + 1]]
            ya = not usuario["activo"]
            usuario["activo"] = False
            lineas, codigo = [_linea("usuario_desactivado", usuario_id=usuario["id"], ya_estaba_inactivo=ya)], 0
        else:
            raise AssertionError(comando)
        id_tarea = f"tarea{len(self.lanzadas):028d}"
        familia = peticion["taskDefinition"].rsplit("/", 1)[-1].split(":")[0]
        self.logs[f"{comun.LOGS_TAREA[familia][1]}/app/{id_tarea}"] = lineas
        arn = f"arn:aws:ecs:us-east-1:{CUENTA}:task/campus-locator-dev/{id_tarea}"
        self._codigos[arn] = codigo
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def get_waiter(self, nombre):
        return type("Espera", (), {"wait": lambda self, **_: None})()

    def describe_tasks(self, cluster, tasks):
        return {
            "tasks": [{"taskDefinitionArn": "…", "containers": [{"name": "app", "exitCode": self._codigos[tasks[0]]}]}]
        }


class Logs:
    def __init__(self, ecs: Ecs) -> None:
        self.ecs = ecs

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        if nextToken:
            return {"events": [], "nextForwardToken": nextToken}
        return {"events": [{"message": m} for m in self.ecs.logs[logStreamName]], "nextForwardToken": "f/1"}


class Secretos:
    def get_secret_value(self, SecretId):
        valores = {
            "campus-locator/dev/admin-inicial": {"correo": ADMIN, "password": PASSWORD_ADMIN},
            "campus-locator/dev/jwt": {"secret": CLAVE},
        }
        return {"SecretString": json.dumps(valores[SecretId])}


class Sesion:
    def __init__(self, api: ApiFalsa) -> None:
        self.ecs = Ecs(api)
        self.clientes = {
            "sts": type("Sts", (), {"get_caller_identity": lambda self: {"Account": CUENTA, "Arn": "arn:…/yo"}})(),
            "secretsmanager": Secretos(),
            "ecs": self.ecs,
            "logs": Logs(self.ecs),
        }

    def client(self, servicio):
        return self.clientes[servicio]


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    for variable in ("VALIDACION_API_URL", "VALIDACION_ADMIN_CORREO", "VALIDACION_ADMIN_PASSWORD", "JWT_SECRET"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")

    def correr(api: ApiFalsa, *argumentos: str) -> tuple[int, Sesion, dict]:
        sesion = Sesion(api)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate13.Contexto("dev")
        ctx.http, ctx.dormir = api, lambda _s: None
        informe = tmp_path / "informe.json"
        codigo = validate13.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8"))

    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def test_dev_completo_pasa_sin_imprimir_secretos(entorno_dev, capsys):
    api = ApiFalsa()
    codigo, sesion, informe = entorno_dev(api)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert set(_estados(informe).values()) == {"pasa"}
    assert list(_estados(informe)) == ["P1", "P2", "P3", "P4", "P5", "C1", "C2", "C5", "C3", "C4a", "C4b", "C6"]
    comandos = [t["overrides"]["containerOverrides"][0]["command"] for t in sesion.ecs.lanzadas]
    assert [c[3] if c[0] == "python" else c[0] for c in comandos] == ["crear-usuario", "desactivar-usuario", "psql"]
    # La contraseña del usuario va como variable de la tarea, no en el comando; la tarea es la revisión de migrate.
    crear = sesion.ecs.lanzadas[0]
    password = crear["overrides"]["containerOverrides"][0]["environment"][0]
    assert password["name"] == "CREAR_USUARIO_PASSWORD" and password["value"].startswith("validacion-pw-")
    assert crear["taskDefinition"].endswith("campus-locator-dev-migrate:4") and crear["startedBy"] == "validate13"
    assert "creado_en >= '2026-10-25 14:59:55+00'" in comandos[2][2]
    assert api.usuarios[comun.USUARIO_VALIDACION]["activo"] is False
    texto = salida.out + salida.err + json.dumps(informe)
    for secreto in (PASSWORD_ADMIN, CLAVE, password["value"], "eyJ"):
        assert secreto not in texto
    assert "[LIMPIEZA] nada que limpiar" in salida.out


def test_429_de_api_gateway_se_reintenta(entorno_dev):
    codigo, _, informe = entorno_dev(ApiFalsa(n_429=3))
    assert codigo == 0, informe


def test_429_que_no_cede_falla_c1_con_el_motivo(entorno_dev):
    codigo, _, informe = entorno_dev(ApiFalsa(n_429=50), "--solo", "C1")
    assert codigo == 1
    [c1] = [c for c in informe["comprobaciones"] if c["id"] == "C1"]
    assert "429 (API Gateway)" in c1["detalle"]


def test_cuerpos_401_distintos_fallan_c2(entorno_dev):
    api = ApiFalsa()
    api.cuerpo_401_inexistente = {
        "error": {"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "No existe.", "detalle": None}
    }
    codigo, _, informe = entorno_dev(api)
    assert codigo == 1
    assert _estados(informe)["C2"] == "falla"


def test_backend_que_no_mira_si_el_usuario_esta_activo_falla_c3(entorno_dev):
    codigo, _, informe = entorno_dev(ApiFalsa(mira_activo=False))
    assert codigo == 1
    [c3] = [c for c in informe["comprobaciones"] if c["id"] == "C3"]
    assert c3["estado"] == "falla" and "403 SIN_PERMISOS" in c3["detalle"]


def test_firma_con_la_clave_decodificada_falla_c1(entorno_dev):
    codigo, _, informe = entorno_dev(ApiFalsa(clave_firma=base64.b64decode(CLAVE)), "--solo", "C1")
    assert codigo == 1
    [c1] = [c for c in informe["comprobaciones"] if c["id"] == "C1"]
    assert "JWT_SECRET usada como texto" in c1["detalle"]


def test_solo_c5_desactiva_al_usuario_en_la_limpieza(entorno_dev, capsys):
    api = ApiFalsa()
    codigo, sesion, _ = entorno_dev(api, "--solo", "C5")
    assert codigo == 0
    assert api.usuarios[comun.USUARIO_VALIDACION]["activo"] is False
    comandos = [t["overrides"]["containerOverrides"][0]["command"][3] for t in sesion.ecs.lanzadas]
    assert comandos == ["crear-usuario", "desactivar-usuario"]  # el segundo es la limpieza
    assert f"[LIMPIEZA] {comun.USUARIO_VALIDACION} desactivado" in capsys.readouterr().out


def test_si_crear_usuario_falla_tras_reactivarlo_la_limpieza_lo_desactiva(entorno_dev, monkeypatch, capsys):
    """El CLI ya reactivó al usuario, pero esperar la tarea o leer su log falló: no debe quedar activo."""
    api = ApiFalsa()

    def crear_y_fallar(_backend):
        api.usuarios[comun.USUARIO_VALIDACION] = {
            "id": str(uuid.uuid4()),
            "nombre": "v",
            "rol": "user",
            "pw": "x",
            "activo": True,
        }
        raise comun.Falla("la tarea no se detuvo en 900 s")

    monkeypatch.setattr(comun, "crear_usuario_validacion", crear_y_fallar)
    codigo, _, informe = entorno_dev(api, "--solo", "C5")
    assert codigo == 1 and _estados(informe)["C5"] == "falla"
    assert api.usuarios[comun.USUARIO_VALIDACION]["activo"] is False
    assert f"[LIMPIEZA] {comun.USUARIO_VALIDACION} desactivado" in capsys.readouterr().out


def test_si_crear_usuario_falla_antes_de_crearlo_la_limpieza_lo_tolera(entorno_dev, monkeypatch, capsys):
    def fallar(_backend):
        raise comun.Falla("crear-usuario terminó con 2: base_no_disponible")

    monkeypatch.setattr(comun, "crear_usuario_validacion", fallar)
    codigo, _, _ = entorno_dev(ApiFalsa(), "--solo", "C5")
    assert codigo == 1
    assert "no existe: nada que desactivar" in capsys.readouterr().out


def test_ready_con_503_bloquea(entorno_dev):
    api = ApiFalsa()
    original = api.request
    api.request = lambda m, u, **k: _error(503, "BASE_NO_DISPONIBLE") if u.endswith("/ready") else original(m, u, **k)
    codigo, _, informe = entorno_dev(api)
    assert codigo == 2
    assert informe["resultado"] == "bloqueado"


# --- local ---------------------------------------------------------------------------------------------------------
def test_local_usa_docker_compose_y_no_pone_la_contrasena_en_el_comando(monkeypatch, tmp_path, capsys):
    api = ApiFalsa()
    ejecutados: list[tuple[list[str], dict | None]] = []

    def proceso(argumentos, *, cwd=None, timeout=600, entorno=None):
        ejecutados.append((list(argumentos), dict(entorno) if entorno else None))
        if argumentos[:3] == ["docker", "compose", "ps"]:
            salida = "\n".join(json.dumps({"Service": s, "State": "running"}) for s in ("db", "api", "worker"))
        elif "psql" in argumentos:
            fallos = sum(1 for actor, _ in api.auditoria if actor is None)
            salida = f"{fallos}|{len(api.auditoria) - fallos}|0\n"
        elif "crear-usuario" in argumentos:
            correo = argumentos[argumentos.index("--correo") + 1]
            api.usuarios[correo] = {
                "id": str(uuid.uuid4()),
                "nombre": "v",
                "rol": "user",
                "pw": entorno["CREAR_USUARIO_PASSWORD"],
                "activo": True,
            }
            salida = _linea("usuario_guardado", resultado="creado") + "\n"
        elif "desactivar-usuario" in argumentos:
            api.usuarios[comun.USUARIO_VALIDACION]["activo"] = False
            salida = _linea("usuario_desactivado", ya_estaba_inactivo=False) + "\n"
        else:
            raise AssertionError(argumentos)
        return subprocess.CompletedProcess(argumentos, 0, salida, "")

    monkeypatch.setattr(comun, "ejecutar_proceso", proceso)
    monkeypatch.setenv("VALIDACION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)
    monkeypatch.setenv("JWT_SECRET", CLAVE)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")
    ctx = validate13.Contexto("local")
    ctx.http, ctx.dormir = api, lambda _s: None
    codigo = validate13.main(["--entorno", "local", "--informe", str(tmp_path / "i.json")], ctx=ctx)
    assert codigo == 0, capsys.readouterr().out
    [crear] = [(a, e) for a, e in ejecutados if "crear-usuario" in a]
    argumentos, entorno = crear
    assert argumentos[:7] == ["docker", "compose", "run", "--rm", "-T", "-e", "CREAR_USUARIO_PASSWORD"]
    assert argumentos[7:11] == ["api", "python", "-m", "app.cli"]
    assert not any(a.startswith("validacion-pw-") for a in argumentos)
    assert entorno["CREAR_USUARIO_PASSWORD"].startswith("validacion-pw-")
    [psql] = [a for a, _ in ejecutados if "psql" in a]
    assert psql[:6] == ["docker", "compose", "exec", "-T", "db", "psql"]


def test_local_sin_jwt_secret_termina_con_3(monkeypatch, tmp_path):
    monkeypatch.setenv("VALIDACION_API_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", ADMIN)
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", PASSWORD_ADMIN)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(comun, "commit_local", lambda: None)
    ctx = validate13.Contexto("local")
    ctx.http = ApiFalsa()
    assert validate13.main(["--entorno", "local", "--informe", str(tmp_path / "i.json")], ctx=ctx) == 3


# --- JWT a mano ----------------------------------------------------------------------------------------------------
def test_firmar_es_compatible_con_pyjwt():
    token = validate13.firmar({"alg": "HS256", "typ": "JWT"}, {"a": 1}, CLAVE)
    assert jwt.decode(token, CLAVE, algorithms=["HS256"]) == {"a": 1}
    assert validate13.firma_valida(token, CLAVE)
    assert not validate13.firma_valida(token, CLAVE + "x")


def test_alterar_firma_siempre_cambia_la_firma():
    for n in range(200):
        token = validate13.firmar({"alg": "HS256"}, {"n": n}, CLAVE)
        alterado = validate13.alterar_firma(token)
        assert alterado != token
        assert not validate13.firma_valida(alterado, CLAVE)
