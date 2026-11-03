"""Validador de BE-2.4 con AWS, HTTP, S3, SQS, el `worker` y el endpoint de vecinos simulados (validation-2-4.md).

Reutiliza el mundo falso de `test_validate22.py` (API de §5.4/§5.5, `/v1/health/ready`, S3 con eventos a `ingesta`, ECS
de `embedding` y `worker` con retraso, escalado, CloudWatch, Cloud Map y un `worker` que procesa las fotos) y le añade:
`POST /v1/admin/diagnostico/vecinos` (la misma foto → similitud 0,99; el resto, por debajo de 0,95), el usuario
`validacion+user@campus.edu.co` (`crear-usuario`/`desactivar-usuario` como tareas de `migrate` y su login), los conteos
de `psql`, el listado paginado de S3 y los logs de `api` y `embedding`. Interruptores para simular un backend
defectuoso. El reloj es falso.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("botocore")

import comun
import validate24

_ruta = Path(__file__).with_name("test_validate22.py")
_spec = importlib.util.spec_from_file_location("falsos_validate22", _ruta)
t22 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t22)

TOKEN_USER = "eyJ-token-falso-del-usuario-user"
PLAN = "| BE-2.2 | 2 | Hecho | [2-2](x) | `3b01b68` |\n| BE-2.4 | 2 | En curso | [2-4](x) | — |\n"


class Mundo(t22.Mundo):
    def __init__(self, embedding_encendido: bool = False, hora_bogota: int = 15, n_base: int = 4) -> None:
        super().__init__(embedding_encendido=embedding_encendido, hora_bogota=hora_bogota)
        # índice «real» previo: N0 vectores de otro video, con similitudes fijas con cualquier consulta (dos por encima
        # de LOC_SIM_MIN y el resto por debajo); las fotos de C1 dan 0,9931 consigo mismas y < 0,5 con las demás
        self.base = [str(uuid.uuid4()) for _ in range(n_base)]
        self.similitud_base = dict(zip(self.base, (0.81, 0.62, 0.41, 0.30, 0.25, 0.2), strict=False))
        self.video_base = str(uuid.uuid4())
        self.objetos.update({f"lugares/{uuid.uuid4()}.jpg": {"datos": b"x", "etag": "l", "tipo": "image/jpeg"}})
        self.eventos_localizacion = 7
        self.log_api: list[tuple[Any, str]] = []
        self.log_embedding: list[tuple[Any, str]] = []
        self.usuario: dict[str, Any] | None = None
        self.consultas = 0
        # interruptores de un backend defectuoso
        self.desplegado = True
        self.filtra_umbral = False  # aplica LOC_SIM_MIN
        self.guarda_consulta = False  # deja la foto en S3
        self.registra_evento = False  # escribe en eventos_localizacion
        self.registra_foto = False  # la foto en base64 en el log de api
        self.user_entra = False  # un token `user` pasa
        self.otro_primero = False  # el primer vecino no es la propia foto

    # -- tareas sueltas -------------------------------------------------------------------------------------------
    def psql(self, consulta: str) -> list[str]:
        if consulta == validate24.SQL_CONTEOS:
            vivos = [i for i in self.vectores if self._foto_de(i) is not None]
            return [f"{self.eventos_localizacion}|{len(self.base) + len(vivos)}"]
        return super().psql(consulta)

    # -- API ----------------------------------------------------------------------------------------------------------
    def request(self, metodo: str, url: str, headers: dict | None = None, json: Any = None, params=None, **resto):
        ruta = url.split("/v1", 1)[1]
        if ruta == "/auth/login" and json and json.get("identificador") == comun.USUARIO_VALIDACION:
            usuario = self.usuario or {}
            if not usuario.get("activo") or json.get("password") != usuario.get("password"):
                return t22._error(401, "CREDENCIALES_INVALIDAS")
            datos = {"id": "u1", "nombre": "validacion-usuario", "correo": comun.USUARIO_VALIDACION, "rol": "user"}
            return t22.Respuesta(200, {"token": TOKEN_USER, "expira_en": "2026-10-26T03:00:00Z", "usuario": datos})
        if ruta == "/admin/diagnostico/vecinos" and metodo == "POST":
            return self._vecinos(headers or {}, params or {}, resto.get("files") or [])
        return super().request(metodo, url, headers=headers, json=json, params=params, **resto)

    def _similitud(self, imagen_id: str, datos: bytes) -> float:
        if imagen_id in self.similitud_base:
            return self.similitud_base[imagen_id]
        encontrada = self._foto_de(imagen_id)
        if encontrada is not None:
            objeto = self.objetos.get(encontrada[1]["clave"])
            if objeto is not None and objeto["datos"] == datos:
                return 0.9931
        semilla = zlib.crc32(imagen_id.encode() + datos[:64])
        return round(0.2 + (semilla % 300) / 1000, 4)  # [0,2; 0,5)

    def _vecinos(self, headers: dict, params: dict, files: list) -> t22.Respuesta:
        if not self.desplegado:
            return t22._error(404, "NO_ENCONTRADO")
        autorizacion = headers.get("Authorization")
        if autorizacion is None:
            return t22._error(401, "NO_AUTENTICADO")
        if autorizacion == f"Bearer {TOKEN_USER}" and not self.user_entra:
            return t22._error(403, "SIN_PERMISOS")
        if autorizacion not in (f"Bearer {t22.TOKEN}", f"Bearer {TOKEN_USER}"):
            return t22._error(401, "TOKEN_INVALIDO")
        try:
            k = int(params.get("k", 5))
        except ValueError:
            k = -1
        if not 1 <= k <= 50:
            cuerpo = {"error": {"codigo": "VALIDACION", "mensaje": "…", "detalle": {"campos": [{"campo": "k"}]}}}
            return t22.Respuesta(422, cuerpo)
        fotos = [f for f in files if f[0] == "foto"]
        if not fotos:
            return self._foto_invalida("falta la parte foto")
        _, (_, datos, tipo) = fotos[0]
        if tipo != "image/jpeg" or len(datos) > 1_572_864 or not datos.startswith(b"\xff\xd8\xff"):
            return self._foto_invalida("tipo o tamaño")
        if not self.sano():
            return t22._error(503, "EMBEDDING_NO_DISPONIBLE")
        self.consultas += 1
        ids = [*self.base, *(i for i in self.vectores if self._foto_de(i) is not None)]
        vecinos = []
        for imagen_id in ids:
            encontrada = self._foto_de(imagen_id)
            video_id = self.video_base if encontrada is None else encontrada[0]["id"]
            vecinos.append({"imagen_id": imagen_id, "video_id": video_id, "lat": 1.0, "lng": -100.0, "rumbo": 0.0,
                            "lugar_id": None, "similitud": self._similitud(imagen_id, datos)})  # fmt: skip
        vecinos.sort(key=lambda v: (-v["similitud"], v["imagen_id"]))
        if self.otro_primero and len(vecinos) > 1:
            vecinos[0]["similitud"] = vecinos[1]["similitud"]
            vecinos[0], vecinos[1] = vecinos[1], vecinos[0]
        if self.filtra_umbral:
            vecinos = [v for v in vecinos if v["similitud"] >= 0.55]
        if self.guarda_consulta:
            self.objetos[f"consultas/{uuid.uuid4()}.jpg"] = {"datos": datos, "etag": "c", "tipo": "image/jpeg"}
        if self.registra_evento:
            self.eventos_localizacion += 1
        if self.registra_foto:
            self.log_api.append((self.t, base64.b64encode(datos[:600]).decode()))
        self.log_api.append((self.t, json.dumps({"evento": "vecinos_consultados", "k": k})))
        self.log_embedding.append((self.t, json.dumps({"evento": "peticion", "ruta": "/v1/embed"})))
        cuerpo = {"version_vector": "dinov2-vits14/pp-v1", "k": k, "vecinos": vecinos[:k], "latencia_ms": 120}
        return t22.Respuesta(200, cuerpo)

    @staticmethod
    def _foto_invalida(motivo: str) -> t22.Respuesta:
        detalle = {"indice": 0, "motivo": motivo}
        return t22.Respuesta(400, {"error": {"codigo": "FOTOS_INVALIDAS", "mensaje": "…", "detalle": detalle}})


class Ecs(t22.Ecs):
    def run_task(self, **peticion):
        sobrescritura = peticion["overrides"]["containerOverrides"][0]
        comando = sobrescritura["command"]
        if comando[:3] == ["python", "-m", "app.cli"] and comando[3] in ("crear-usuario", "desactivar-usuario"):
            self.lanzadas.append(peticion)
            if comando[3] == "crear-usuario":
                entorno = {e["name"]: e["value"] for e in sobrescritura.get("environment", [])}
                self.mundo.usuario = {"activo": True, "password": entorno["CREAR_USUARIO_PASSWORD"]}
                lineas = [json.dumps({"evento": "usuario_guardado", "resultado": "creado"})]
            else:
                ya = not (self.mundo.usuario or {}).get("activo")
                if self.mundo.usuario:
                    self.mundo.usuario["activo"] = False
                lineas = [json.dumps({"evento": "usuario_desactivado", "ya_estaba_inactivo": ya})]
            id_tarea = f"tarea{len(self.lanzadas):028d}"
            self.logs[f"migrate/app/{id_tarea}"] = lineas
            arn = f"arn:aws:ecs:us-east-1:{t22.CUENTA}:task/campus-locator-dev/{id_tarea}"
            self._codigos[arn] = 0
            return {"tasks": [{"taskArn": arn}], "failures": []}
        return super().run_task(**peticion)


class Logs(t22.Logs):
    def filter_log_events(self, logGroupName, startTime, filterPattern=None, nextToken=None):
        if logGroupName == comun.LOG_WORKER:
            return super().filter_log_events(logGroupName, startTime, filterPattern, nextToken)
        fuente = {comun.LOG_API: self.mundo.log_api, comun.LOG_EMBEDDING: self.mundo.log_embedding}[logGroupName]
        mensajes = [m for momento, m in fuente if momento.timestamp() * 1000 >= startTime]
        inicio = int(nextToken or 0)
        pagina = {"events": [{"message": m} for m in mensajes[inicio : inicio + 2]]}  # páginas de 2
        if inicio + 2 < len(mensajes):
            pagina["nextToken"] = str(inicio + 2)
        return pagina


class S3(t22.S3):
    def get_paginator(self, nombre):
        assert nombre == "list_objects_v2"
        claves = sorted(self.mundo.objetos)

        class Paginador:
            def paginate(self, Bucket, Prefix):
                elegidas = [c for c in claves if c.startswith(Prefix)]
                for i in range(0, max(len(elegidas), 1), 3):  # páginas de 3
                    yield {"Contents": [{"Key": c} for c in elegidas[i : i + 3]]}

        return Paginador()


class Sesion(t22.Sesion):
    def __init__(self, mundo: Mundo) -> None:
        super().__init__(mundo)
        self.ecs = Ecs(mundo)
        self.clientes |= {"ecs": self.ecs, "logs": Logs(mundo, self.ecs), "s3": S3(mundo)}


@pytest.fixture
def entorno_dev(monkeypatch, tmp_path):
    for variable in ("VALIDACION_API_URL", "VALIDACION_ADMIN_CORREO", "VALIDACION_ADMIN_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_PROFILE", "pruebas")
    monkeypatch.setattr(comun, "outputs_terraform", lambda *a, **k: t22.OUTPUTS)
    monkeypatch.setattr(comun, "commit_local", lambda: "abc1234")
    plan = tmp_path / "PLAN.md"
    plan.write_text(PLAN, encoding="utf-8")
    monkeypatch.setattr(validate24, "PLAN_BACKEND", plan)

    def correr(mundo: Mundo, *argumentos: str):
        sesion = Sesion(mundo)
        monkeypatch.setattr(comun, "sesion_aws", lambda: sesion)
        ctx = validate24.Contexto("dev")
        ctx.http, ctx.http_s3 = mundo, t22.HttpS3(mundo)
        ctx.dormir, ctx.ahora = mundo.dormir, mundo.ahora
        ctx.sello = "20261025-150000"
        informe = tmp_path / "informe.json"
        codigo = validate24.main(["--entorno", "dev", "--informe", str(informe), *argumentos], ctx=ctx)
        return codigo, sesion, json.loads(informe.read_text(encoding="utf-8")), ctx

    return correr


def _estados(informe: dict) -> dict[str, str]:
    return {c["id"]: c["estado"] for c in informe["precondiciones"] + informe["comprobaciones"]}


def _detalle(informe: dict, id_: str) -> str:
    return next(c["detalle"] for c in informe["precondiciones"] + informe["comprobaciones"] if c["id"] == id_)


def _comandos(sesion: Sesion) -> list[str]:
    """La consulta de cada tarea `psql` o el subcomando de cada `python -m app.cli`, en orden."""
    resultado = []
    for peticion in sesion.ecs.lanzadas:
        comando = peticion["overrides"]["containerOverrides"][0]["command"]
        resultado.append(comando[2] if comando[0] == "psql" else comando[3])
    return resultado


ORDEN = ["P1", "P2", "P3", "P4", "P5", "C1", "C2a", "C2b", "C3a", "C3b", "C3c", "C4a", "C4b"]


def test_dev_completo_con_embedding_apagado_lo_enciende_y_lo_apaga(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=False)
    codigo, sesion, informe, _ = entorno_dev(mundo)
    salida = capsys.readouterr()
    assert codigo == 0, salida.out
    assert list(_estados(informe)) == ORDEN and set(_estados(informe).values()) == {"pasa"}
    texto = salida.out + salida.err + json.dumps(informe)
    for secreto in (t22.FIRMA, t22.TOKEN, TOKEN_USER, "validacion-pw-", "s3.amazonaws.com"):
        assert secreto not in texto
    assert "embedding encendido en" in _detalle(informe, "P5")
    assert "cada una es su primer vecino (similitud 0.9931, 0.9931, 0.9931)" in _detalle(informe, "C1")
    assert "N = 7 vectores" in _detalle(informe, "C2a") and "k=5 → 5 vecinos" in _detalle(informe, "C2a")
    assert "k=1 → 1 y k=50 → 7 vecinos (N = 7)" in _detalle(informe, "C2b")
    assert "6 claves nuevas" in _detalle(informe, "C4a") and "vectores 4 → 7 (+3" in _detalle(informe, "C4a")
    assert "[PREPARACION] sin restos validacion-" in salida.out and "lecturas iniciales:" in salida.out
    # limpieza: embedding apagado, video borrado y usuario desactivado
    assert mundo.cambios_embedding == [1, 0] and mundo.rangos == {"embedding": (0, 0), "worker": (0, 0)}
    assert mundo.videos == {} and mundo.usuario == {"activo": False, "password": mundo.usuario["password"]}
    assert "embedding apagado (lo encendió el validador)" in salida.out
    assert f"{comun.USUARIO_VALIDACION} desactivado" in salida.out
    # cinco tareas sueltas: conteos al empezar, crear-usuario, conteos al final, limpiar-validacion, desactivar-usuario
    assert _comandos(sesion) == [
        validate24.SQL_CONTEOS,
        "crear-usuario",
        validate24.SQL_CONTEOS,
        "limpiar-validacion",
        "desactivar-usuario",
    ]


def test_con_embedding_encendido_lo_deja_encendido(entorno_dev, capsys):
    mundo = Mundo(embedding_encendido=True)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 0, capsys.readouterr().out
    assert "ya encendido (latido publicado)" in _detalle(informe, "P5")
    assert mundo.cambios_embedding == [] and mundo.deseado["embedding"] == 1
    assert "embedding sigue encendido (como estaba)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("interruptor", "id_", "texto"),
    [
        ("filtra_umbral", "C2a", "se esperaban min(5, N=7) = 5"),
        ("guarda_consulta", "C4a", "claves nuevas fuera del video de prueba, p. ej. consultas/"),
        ("registra_evento", "C4a", "eventos_localizacion pasó de 7 a"),
        ("registra_foto", "C4b", "contienen /9j/"),
        ("user_entra", "C3c", "se esperaba 403 SIN_PERMISOS"),
        ("otro_primero", "C1", "no ella misma"),
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
    assert mundo.videos == {} and not (mundo.usuario or {}).get("activo")  # la limpieza borra y desactiva igual


def test_sin_el_endpoint_desplegado_es_codigo_2_sin_encender_nada(entorno_dev):
    mundo = Mundo(embedding_encendido=False)
    mundo.desplegado = False
    codigo, sesion, informe, _ = entorno_dev(mundo)
    assert codigo == 2 and "BE-2.4 sin desplegar" in _detalle(informe, "P3")
    assert mundo.cambios_embedding == [] and mundo.videos == {} and sesion.ecs.lanzadas == []


def test_sin_be22_hecho_es_codigo_2(entorno_dev, tmp_path):
    (tmp_path / "PLAN.md").write_text(PLAN.replace("| Hecho |", "| En curso |"), encoding="utf-8")
    codigo, _, informe, _ = entorno_dev(Mundo())
    assert codigo == 2 and "BE-2.2 no está «Hecho»" in _detalle(informe, "P2")


def test_fuera_de_horario_es_codigo_3(entorno_dev):
    mundo = Mundo(embedding_encendido=False, hora_bogota=21)
    codigo, _, informe, _ = entorno_dev(mundo)
    assert codigo == 3 and "antes de las 21:00" in _detalle(informe, "P2")
    assert mundo.cambios_embedding == []


def test_solo_c2_no_crea_video_y_cuenta_el_indice_con_una_tarea(entorno_dev):
    mundo = Mundo(embedding_encendido=True, n_base=2)
    codigo, sesion, informe, _ = entorno_dev(mundo, "--solo", "C2")
    assert codigo == 0, informe
    assert _estados(informe)["C1"] == "omitida" and _estados(informe)["C2b"] == "pasa"
    assert "N = 2 vectores" in _detalle(informe, "C2a") and "k=50 → 2" in _detalle(informe, "C2b")
    assert _comandos(sesion) == [validate24.SQL_CONTEOS]  # sin lecturas de C4a, sin video ni usuario
    assert mundo.videos == {}


def test_con_indice_vacio_y_solo_c2b(entorno_dev):
    codigo, _, informe, _ = entorno_dev(Mundo(embedding_encendido=True, n_base=0), "--solo", "C2b")
    assert codigo == 0 and "k=1 → 0 y k=50 → 0 vecinos (N = 0)" in _detalle(informe, "C2b")


@pytest.mark.parametrize(
    ("solo", "id_", "esperado"),
    [(None, "C4a", True), ("C4", "C4a", True), ("C4a", "C4a", True), ("C1,C2", "C4a", False), ("C4b", "C4a", False)],
)
def test_incluida_sigue_la_regla_de_solo(solo, id_, esperado):
    assert validate24.incluida(solo, id_) is esperado


def test_sql_de_conteos_usa_la_version_activa():
    assert f"version_vector = '{validate24.VERSION_VECTOR}'" in validate24.SQL_CONTEOS
