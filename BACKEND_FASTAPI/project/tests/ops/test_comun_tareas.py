"""Ayudas de `comun` para tareas sueltas de ECS y procesos externos (backend ARCHITECTURE §5.11).

Necesitan botocore (grupo `ops`): sin él se omiten. CI instala el grupo (`uv sync --frozen --group ops`).
"""

from __future__ import annotations

import pytest

pytest.importorskip("botocore")

import comun
from comun import ErrorConfiguracion, Falla, PrecondicionNoCumplida


def _error_aws(codigo: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": codigo, "Message": codigo}}, "Operacion")


class LogsPaginados:
    """`get_log_events` que primero no tiene el stream, luego lo tiene vacío y después con dos páginas."""

    def __init__(self) -> None:
        self.llamadas = 0

    def get_log_events(self, logGroupName, logStreamName, startFromHead, nextToken=None):
        self.llamadas += 1
        if self.llamadas == 1:
            raise _error_aws("ResourceNotFoundException")
        if self.llamadas == 2:
            return {"events": [], "nextForwardToken": "f/0"}
        if self.llamadas == 3:
            return {"events": [], "nextForwardToken": "f/0"}  # mismo token: fin del intento vacío
        paginas = {None: (["a", "b"], "f/1"), "f/1": (["c"], "f/2"), "f/2": ([], "f/2")}
        mensajes, siguiente = paginas[nextToken]
        return {"events": [{"message": m} for m in mensajes], "nextForwardToken": siguiente}


def test_leer_log_espera_al_stream_y_pagina():
    esperas = []
    logs = LogsPaginados()
    assert comun.leer_log(logs, "/g", "s", dormir=esperas.append) == ["a", "b", "c"]
    assert len(esperas) == 2


def test_leer_log_sin_stream_devuelve_vacio():
    class SinStream:
        def get_log_events(self, **_):
            raise _error_aws("ResourceNotFoundException")

    esperas = []
    assert comun.leer_log(SinStream(), "/g", "s", intentos=3, dormir=esperas.append) == []
    assert len(esperas) == 2


def test_leer_log_sin_permiso_es_error_de_configuracion():
    class SinPermiso:
        def get_log_events(self, **_):
            raise _error_aws("AccessDeniedException")

    with pytest.raises(ErrorConfiguracion, match="sin permiso"):
        comun.leer_log(SinPermiso(), "/g", "s", dormir=lambda _s: None)


def test_red_tareas():
    red = comun.red_tareas({"subredes_tareas": "subnet-a,subnet-b", "sg_migrate": "sg-1"})
    assert red["awsvpcConfiguration"] == {
        "subnets": ["subnet-a", "subnet-b"],
        "securityGroups": ["sg-1"],
        "assignPublicIp": "ENABLED",
    }
    with pytest.raises(PrecondicionNoCumplida):
        comun.red_tareas({"subredes_tareas": ["subnet-a"]})


class EcsSinCapacidad:
    def run_task(self, **_):
        return {"tasks": [], "failures": [{"arn": "arn:…", "reason": "RESOURCE:CPU"}]}


class EcsQueNoPara:
    def run_task(self, **_):
        return {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:1:task/c/abc"}]}

    def get_waiter(self, _nombre):
        from botocore.exceptions import WaiterError

        class Espera:
            def wait(self, **_):
                raise WaiterError("TasksStopped", "Max attempts exceeded", {})

        return Espera()


def test_lanzar_tarea_sin_lanzar_es_falla():
    with pytest.raises(Falla, match="RESOURCE:CPU"):
        comun.lanzar_tarea(EcsSinCapacidad(), None, definicion="f", red={}, familia=comun.FAMILIA_MIGRATE)


def test_lanzar_tarea_que_no_se_detiene_es_falla():
    with pytest.raises(Falla, match="no se detuvo"):
        comun.lanzar_tarea(EcsQueNoPara(), None, definicion="f", red={}, familia=comun.FAMILIA_MIGRATE, espera_s=12)


def test_resultado_tarea_eventos():
    resultado = comun.ResultadoTarea(
        arn="arn:aws:ecs:us-east-1:1:task/c/abc123",
        definicion="d",
        codigo=0,
        motivo="",
        lineas=['{"evento": "a", "x": 1}', "texto suelto", '{"evento": "b"}', "[1, 2]"],
    )
    assert resultado.id == "abc123"
    assert [e["evento"] for e in resultado.eventos()] == ["a", "b"]
    assert resultado.eventos("b") == [{"evento": "b"}]


def test_ejecutar_proceso_devuelve_el_codigo(tmp_path):
    resultado = comun.ejecutar_proceso(["python3", "-c", "import sys; print('hola'); sys.exit(4)"], cwd=tmp_path)
    assert (resultado.returncode, resultado.stdout.strip()) == (4, "hola")
    with pytest.raises(ErrorConfiguracion):
        comun.ejecutar_proceso(["no-existe-este-programa"])
