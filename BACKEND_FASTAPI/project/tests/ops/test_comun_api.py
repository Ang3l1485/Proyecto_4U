"""Ayudas de BE-1.3 en `src/ops/comun.py`: secretos, credenciales, `ClienteApi`, `EntornoBackend` y el usuario de
prueba (ARCHITECTURE §5.11)."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import pytest

pytest.importorskip("botocore")

from botocore.exceptions import ClientError

import comun


class Respuesta:
    def __init__(self, estado: int, cuerpo: Any) -> None:
        self.status_code = estado
        self._cuerpo = cuerpo

    def json(self) -> Any:
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo


class Http:
    def __init__(self, respuestas: list[Respuesta]) -> None:
        self.respuestas = list(respuestas)
        self.peticiones: list[tuple[str, str, dict]] = []

    def request(self, metodo, url, headers=None, **kwargs):
        self.peticiones.append((metodo, url, dict(headers or {}) | kwargs))
        return self.respuestas.pop(0)

    def close(self):
        pass


class Reloj:
    def __init__(self) -> None:
        self.t = 100.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def dormir(self, segundos: float) -> None:
        self.esperas.append(round(segundos, 3))
        self.t += segundos


def _cliente(respuestas: list[Respuesta]) -> tuple[comun.ClienteApi, Http, Reloj]:
    http, reloj = Http(respuestas), Reloj()
    return comun.ClienteApi("https://x/v1/", http=http, dormir=reloj.dormir, reloj=reloj), http, reloj


GW_429 = Respuesta(429, {"message": "Too Many Requests"})


def test_un_429_de_api_gateway_se_reintenta_con_esperas_crecientes():
    cliente, http, reloj = _cliente([GW_429, GW_429, Respuesta(200, {"ok": True})])
    r = cliente.pedir("GET", "/health", token="t0k3n")
    assert r.status_code == 200
    assert reloj.esperas == [1.0, 2.0]
    assert cliente.reintentos_429 == 2
    assert http.peticiones[0][:2] == ("GET", "https://x/v1/health")
    assert http.peticiones[0][2]["Authorization"] == "Bearer t0k3n"


def test_los_reintentos_se_agotan_y_devuelve_el_ultimo_429():
    cliente, http, reloj = _cliente([GW_429] * 5)
    assert cliente.pedir("GET", "/health").status_code == 429
    assert reloj.esperas == [1.0, 2.0, 4.0, 8.0] and len(http.peticiones) == 5


def test_un_429_del_backend_no_se_reintenta():
    cliente, http, _ = _cliente([Respuesta(429, {"error": {"codigo": "X", "mensaje": "m", "detalle": None}})])
    assert cliente.pedir("POST", "/auth/login").status_code == 429
    assert len(http.peticiones) == 1


GW_500 = Respuesta(500, {"message": "Internal Server Error"})


def test_un_500_de_api_gateway_se_reintenta_pocas_veces():
    """`api` sin instancias (infra §5.13): la petición no llegó al backend, repetirla es seguro."""
    cliente, http, reloj = _cliente([GW_500, GW_429, GW_500, Respuesta(200, {"ok": True})])
    assert cliente.pedir("POST", "/auth/login").status_code == 200
    assert reloj.esperas == [2.0, 1.0, 4.0]
    assert (cliente.reintentos_500, cliente.reintentos_429) == (2, 1)
    cliente, http, reloj = _cliente([GW_500] * 4)
    assert cliente.pedir("GET", "/health").status_code == 500
    assert reloj.esperas == [2.0, 4.0, 8.0] and len(http.peticiones) == 4


def test_un_500_del_backend_no_se_reintenta():
    cliente, http, _ = _cliente(
        [Respuesta(500, {"error": {"codigo": "ERROR_INTERNO", "mensaje": "m", "detalle": None}})]
    )
    assert cliente.pedir("POST", "/auth/login").status_code == 500
    assert len(http.peticiones) == 1


def test_entre_dos_logins_espera_la_pausa_y_cuenta_resultados():
    cliente, http, reloj = _cliente([Respuesta(200, {"token": "a"}), Respuesta(401, {"error": {"codigo": "C"}})])
    cliente.login("a@b.co", "x")
    cliente.login("a@b.co", "y")
    assert reloj.esperas == [comun.PAUSA_LOGIN_S]
    assert (cliente.logins_ok, cliente.logins_fallidos) == (1, 1)
    assert http.peticiones[0][2]["json"] == {"identificador": "a@b.co", "password": "x"}


@pytest.mark.parametrize(
    ("respuesta", "mensaje"),
    [
        (Respuesta(404, {"error": {"codigo": "NO_ENCONTRADO"}}), "¿está desplegado BE-1.3?"),
        (Respuesta(401, {"error": {"codigo": "CREDENCIALES_INVALIDAS"}}), "401 CREDENCIALES_INVALIDAS"),
        (Respuesta(500, {"message": "Internal Server Error"}), "500 (API Gateway)"),
        (Respuesta(200, {}), "sin `token`"),
    ],
)
def test_token_falla_con_el_codigo(respuesta, mensaje):
    cliente, _, _ = _cliente([respuesta] * 4)  # el 500 de API Gateway se repite 3 veces antes de rendirse
    with pytest.raises(comun.Falla, match=re.escape(mensaje)):
        cliente.token("a@b.co", "x", quien="el admin")


def test_describir_respuesta_y_codigo():
    assert (
        comun.describir_respuesta(Respuesta(503, {"error": {"codigo": "BASE_NO_DISPONIBLE"}}))
        == "503 BASE_NO_DISPONIBLE"
    )
    assert comun.describir_respuesta(Respuesta(502, ValueError("no json"))) == "502"
    assert comun.codigo_error(Respuesta(200, [1, 2])) is None


# --- Secretos y credenciales ---------------------------------------------------------------------------------------
class Secretos:
    def __init__(self, valor: Any = None, error: str | None = None) -> None:
        self.valor, self.error = valor, error

    def get_secret_value(self, SecretId):
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "m"}}, "GetSecretValue")
        return {"SecretString": self.valor if isinstance(self.valor, str) else json.dumps(self.valor)}


class Sesion:
    def __init__(self, secretos: Secretos) -> None:
        self.secretos = secretos

    def client(self, servicio):
        assert servicio == "secretsmanager"
        return self.secretos


@pytest.mark.parametrize(
    ("secretos", "excepcion"),
    [
        (Secretos(error="AccessDeniedException"), comun.ErrorConfiguracion),
        (Secretos(error="ResourceNotFoundException"), comun.PrecondicionNoCumplida),
        (Secretos(valor="no es json"), comun.ErrorConfiguracion),
        (Secretos(valor=[1]), comun.ErrorConfiguracion),
    ],
)
def test_leer_secreto_traduce_errores(secretos, excepcion):
    with pytest.raises(excepcion):
        comun.leer_secreto(Sesion(secretos), "campus-locator/dev/jwt")


def test_credenciales_admin(monkeypatch):
    monkeypatch.delenv("VALIDACION_ADMIN_CORREO", raising=False)
    monkeypatch.delenv("VALIDACION_ADMIN_PASSWORD", raising=False)
    sesion = Sesion(Secretos({"correo": "admin@campus.edu.co", "password": "Secreto123"}))
    assert comun.credenciales_admin("dev", sesion) == ("admin@campus.edu.co", "Secreto123")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.credenciales_admin("local")
    with pytest.raises(comun.ErrorConfiguracion):
        comun.credenciales_admin("dev", Sesion(Secretos({"correo": "a@b.co"})))
    monkeypatch.setenv("VALIDACION_ADMIN_CORREO", " otro@campus.edu.co ")
    monkeypatch.setenv("VALIDACION_ADMIN_PASSWORD", "Otra")
    assert comun.credenciales_admin("local") == ("otro@campus.edu.co", "Otra")
    assert comun.credenciales_admin("dev", sesion) == ("otro@campus.edu.co", "Otra")


# --- EntornoBackend y usuario de prueba ----------------------------------------------------------------------------
def test_cli_en_local_pasa_las_variables_por_el_entorno(monkeypatch):
    llamadas = []

    def proceso(argumentos, *, cwd=None, timeout=600, entorno=None):
        llamadas.append((argumentos, entorno, cwd))
        salida = json.dumps({"evento": "usuario_guardado", "resultado": "creado"}) + "\n"
        return subprocess.CompletedProcess(argumentos, 0, salida, "Container x Creating\n")

    monkeypatch.setattr(comun, "ejecutar_proceso", proceso)
    password = comun.crear_usuario_validacion(comun.EntornoBackend("local"))
    [(argumentos, entorno, cwd)] = llamadas
    assert argumentos == [
        *["docker", "compose", "run", "--rm", "-T", "-e", "CREAR_USUARIO_PASSWORD", "api"],
        *["python", "-m", "app.cli", "crear-usuario", "--correo", "validacion+user@campus.edu.co"],
        *["--nombre", "validacion-usuario", "--rol", "user"],
    ]
    assert entorno == {"CREAR_USUARIO_PASSWORD": password} and password.startswith("validacion-pw-")
    assert cwd == comun.RAIZ_PROYECTO


def test_un_cli_que_falla_da_el_motivo_del_evento(monkeypatch):
    linea = json.dumps({"evento": "base_no_disponible", "motivo": "ConnectionRefusedError: …"})
    monkeypatch.setattr(comun, "ejecutar_proceso", lambda a, **k: subprocess.CompletedProcess(a, 2, linea + "\n", ""))
    with pytest.raises(comun.Falla, match="terminó con 2: base_no_disponible: ConnectionRefusedError"):
        comun.desactivar_usuario_validacion(comun.EntornoBackend("local"))


def test_desactivar_un_usuario_que_no_existe_solo_se_tolera_en_la_limpieza(monkeypatch):
    linea = json.dumps({"evento": "usuario_no_encontrado"})
    monkeypatch.setattr(comun, "ejecutar_proceso", lambda a, **k: subprocess.CompletedProcess(a, 1, linea + "\n", ""))
    backend = comun.EntornoBackend("local")
    assert "no existe" in comun.desactivar_usuario_validacion(backend, tolerar_inexistente=True)
    with pytest.raises(comun.Falla, match="usuario_no_encontrado"):
        comun.desactivar_usuario_validacion(backend)


def test_sql_en_local_y_fallo_de_psql(monkeypatch):
    respuestas = [
        subprocess.CompletedProcess([], 0, "3|2|0\n", ""),
        subprocess.CompletedProcess([], 2, "", 'psql: error: relation "x" does not exist\n'),
    ]
    monkeypatch.setattr(comun, "ejecutar_proceso", lambda a, **k: respuestas.pop(0))
    backend = comun.EntornoBackend("local")
    assert backend.sql("SELECT 1") == ["3|2|0"]
    with pytest.raises(comun.Falla, match='psql terminó con 2: psql: error: relation "x"'):
        backend.sql("SELECT 1")


def test_lanzar_tarea_con_entorno_lo_pone_en_el_override():
    lanzadas = []

    class Ecs:
        def run_task(self, **peticion):
            lanzadas.append(peticion)
            return {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:1:task/c/abc"}]}

        def get_waiter(self, nombre):
            return type("E", (), {"wait": lambda self, **_: None})()

        def describe_tasks(self, cluster, tasks):
            return {"tasks": [{"containers": [{"name": "app", "exitCode": 0}]}]}

    class Logs:
        def get_log_events(self, **_):
            return {"events": [{"message": "x"}], "nextForwardToken": "f"}

    red = {"awsvpcConfiguration": {}}
    comun.lanzar_tarea(Ecs(), Logs(), definicion="d", red=red, familia=comun.FAMILIA_MIGRATE, entorno={"A": "1"})
    comun.lanzar_tarea(
        Ecs(), Logs(), definicion="d", red=red, familia=comun.FAMILIA_MIGRATE, comando=["x"], entorno={"A": "1"}
    )
    comun.lanzar_tarea(Ecs(), Logs(), definicion="d", red=red, familia=comun.FAMILIA_MIGRATE)
    assert lanzadas[0]["overrides"] == {
        "containerOverrides": [{"name": "app", "environment": [{"name": "A", "value": "1"}]}]
    }
    assert lanzadas[1]["overrides"]["containerOverrides"][0]["command"] == ["x"]
    assert "overrides" not in lanzadas[2]


def test_ejecutar_proceso_anade_variables_al_entorno(monkeypatch):
    monkeypatch.setenv("VARIABLE_PREVIA", "sigue")
    resultado = comun.ejecutar_proceso(
        ["python", "-c", "import os; print(os.environ['NUEVA'], os.environ['VARIABLE_PREVIA'])"],
        entorno={"NUEVA": "va"},
    )
    assert resultado.stdout.split() == ["va", "sigue"]
