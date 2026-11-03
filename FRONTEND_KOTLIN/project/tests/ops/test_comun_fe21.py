"""Pruebas de las ayudas que añadió FE-2.1 a comun.py (sin red ni AWS): tamaño de un JPEG, objeto de S3, encendido
de `embedding` con la CLI simulada, token en las peticiones y argumentos propios del validador."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import comun
import pytest


def jpeg(ancho: int, alto: int, *, marcador_sof: int = 0xC0, app1: int = 0) -> bytes:
    """Cabecera JPEG mínima: SOI, APP0 (JFIF), un APP1 opcional de `app1` bytes, DQT y el SOF con las medidas."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    exif = (b"\xff\xe1" + (app1 + 2).to_bytes(2, "big") + b"\x00" * app1) if app1 else b""
    dqt = b"\xff\xdb" + (67).to_bytes(2, "big") + b"\x00" * 65
    sof = bytes([0xFF, marcador_sof]) + (17).to_bytes(2, "big") + b"\x08" + alto.to_bytes(2, "big")
    sof += ancho.to_bytes(2, "big") + b"\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    sos = b"\xff\xda" + (12).to_bytes(2, "big") + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    return b"\xff\xd8" + app0 + exif + dqt + sof + sos + b"\x12\x34" * 50 + b"\xff\xd9"


# --- dimensiones_jpeg --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("ancho", "alto", "marcador"), [(1600, 1200, 0xC0), (1200, 1600, 0xC2), (4000, 3000, 0xC1)])
def test_dimensiones_jpeg_lee_el_sof(ancho, alto, marcador):
    assert comun.dimensiones_jpeg(jpeg(ancho, alto, marcador_sof=marcador)) == (ancho, alto)


def test_dimensiones_jpeg_salta_un_exif_grande():
    assert comun.dimensiones_jpeg(jpeg(4032, 3024, app1=60_000)) == (4032, 3024)


def test_dimensiones_jpeg_rechaza_lo_que_no_es_un_jpeg_o_esta_cortado():
    assert comun.dimensiones_jpeg(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) is None
    assert comun.dimensiones_jpeg(jpeg(1600, 1200)[:30]) is None  # cortado antes del SOF
    assert comun.dimensiones_jpeg(b"\xff\xd8\xff\xda\x00\x02\xff\xd9") is None  # SOS sin SOF
    assert comun.dimensiones_jpeg(b"") is None


# --- leer_objeto_s3 ----------------------------------------------------------------------------------------------


def test_leer_objeto_s3_toma_el_total_de_content_range_y_las_medidas(monkeypatch):
    llamadas = []

    def aws_json(*args, accion, timeout=120, mostrar_error=True):
        llamadas.append(args)
        Path(args[8]).write_bytes(jpeg(1600, 1200))  # el archivo de salida va tras --range
        return {"ContentRange": "bytes 0-131071/612345", "ContentLength": 131072}

    monkeypatch.setattr(comun, "aws_json", aws_json)
    o = comun.leer_objeto_s3("bucket-x", "dataset/v/i.jpg")
    assert (o.bytes, o.dimensiones) == (612345, (1600, 1200))
    assert llamadas[0][:8] == (
        "s3api",
        "get-object",
        "--bucket",
        "bucket-x",
        "--key",
        "dataset/v/i.jpg",
        "--range",
        "bytes=0-131071",
    )


def test_leer_objeto_s3_objeto_pequeno_sin_content_range(monkeypatch):
    def aws_json(*args, accion, timeout=120, mostrar_error=True):
        Path(args[8]).write_bytes(jpeg(800, 600))
        return {"ContentLength": 900}

    monkeypatch.setattr(comun, "aws_json", aws_json)
    o = comun.leer_objeto_s3("b", "k")
    assert (o.bytes, o.dimensiones) == (900, (800, 600))


# --- EmbeddingDev ------------------------------------------------------------------------------------------------


class Reloj:
    def __init__(self) -> None:
        self.t = 0.0

    def reloj(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += s


class AwsFalso:
    """La CLI `aws` simulada para el contrato de encendido (infra §5.10)."""

    def __init__(self, *, latido_tras=1, alarma_tras=1, sano_tras=2, ip_cloud_map="10.0.0.5", throttle_una_vez=True):
        self.llamadas: list[tuple[str, ...]] = []
        self.latido_tras = latido_tras
        self.alarma_tras = alarma_tras
        self.sano_tras = sano_tras
        self.ip_cloud_map = ip_cloud_map
        self.throttle = throttle_una_vez
        self.n: dict[str, int] = {}

    def __call__(self, *args, accion, timeout=120, mostrar_error=True):
        self.llamadas.append(args)
        clave = f"{args[0]} {args[1]}"
        self.n[clave] = self.n.get(clave, 0) + 1
        veces = self.n[clave]
        if clave == "application-autoscaling describe-scalable-targets":
            return {"ScalableTargets": [{"ResourceId": r} for r in args[5:7]]}
        if clave == "cloudwatch get-metric-statistics":
            if self.throttle:
                self.throttle = False
                raise comun.ErrorAws("Throttling", "Throttling")
            return {"Datapoints": [{"Sum": 1.0}] if veces > self.latido_tras else []}
        if clave == "cloudwatch describe-alarms":
            return {"MetricAlarms": [{"StateValue": "OK" if veces > self.alarma_tras else "ALARM"}]}
        if clave == "ecs describe-services":
            estado = "COMPLETED" if veces > self.sano_tras else "IN_PROGRESS"
            return {
                "despliegues": [{"status": "PRIMARY", "rolloutState": estado}],
                "registros": [{"registryArn": "arn:aws:servicediscovery:us-east-1:1:service/srv-emb"}],
            }
        if clave == "ecs list-tasks":
            return ["arn:aws:ecs:us-east-1:1:task/c/t1"]
        if clave == "ecs describe-tasks":
            ip = {"name": "privateIPv4Address", "value": "10.0.0.5"}
            return [{"salud": "HEALTHY", "adjuntos": [{"details": [ip]}]}]
        if clave == "servicediscovery list-instances":
            assert args[3] == "srv-emb"
            return [self.ip_cloud_map]
        return None  # register-scalable-target, put-metric-data, update-service

    def ordenes(self) -> list[str]:
        return [f"{a[0]} {a[1]}" for a in self.llamadas]


def _instalar(monkeypatch, aws: AwsFalso) -> Reloj:
    reloj = Reloj()
    monkeypatch.setattr(comun, "aws_json", aws)
    monkeypatch.setattr(comun, "reloj", reloj.reloj)
    monkeypatch.setattr(comun, "dormir", reloj.dormir)
    return reloj


def test_encender_sigue_el_contrato_en_orden(monkeypatch):
    aws = AwsFalso()
    _instalar(monkeypatch, aws)
    segundos = comun.EmbeddingDev("campus-locator-dev").encender(lambda: True)
    ordenes = aws.ordenes()
    assert ordenes[:3] == [
        "application-autoscaling register-scalable-target",
        "application-autoscaling register-scalable-target",
        "cloudwatch put-metric-data",
    ]
    assert ordenes.index("cloudwatch describe-alarms") > ordenes.index("cloudwatch get-metric-statistics")
    assert ordenes.index("ecs update-service") > ordenes.index("cloudwatch describe-alarms")
    assert ordenes[-1] == "servicediscovery list-instances"
    registro = [a for a in aws.llamadas if a[1] == "register-scalable-target"]
    assert {a[7] for a in registro} == {"service/campus-locator-dev/embedding", "service/campus-locator-dev/worker"}
    assert all(a[-1] == "1" for a in registro)  # max-capacity 1
    latido = next(a for a in aws.llamadas if a[1] == "put-metric-data")
    assert latido[3] == comun.NAMESPACE_METRICAS and latido[5].startswith(
        "MetricName=EmbeddingEncendidos,Value=1,Unit=Count"
    )
    actualizar = next(a for a in aws.llamadas if a[1] == "update-service")
    assert actualizar[3:8] == ("campus-locator-dev", "--service", "embedding", "--desired-count", "1")
    assert segundos > 0


def test_encender_sin_la_ip_en_cloud_map_es_bloqueo_tras_10_min(monkeypatch):
    aws = AwsFalso(ip_cloud_map="10.9.9.9")
    reloj = _instalar(monkeypatch, aws)
    with pytest.raises(comun.Bloqueo, match="Cloud Map sin la IP"):
        comun.EmbeddingDev("c").encender(lambda: True)
    assert reloj.t > comun.EmbeddingDev.LIMITE_ENCENDIDO_S


def test_encender_espera_a_la_api(monkeypatch):
    aws = AwsFalso()
    _instalar(monkeypatch, aws)
    respuestas = iter([False, False, True])
    comun.EmbeddingDev("c").encender(lambda: next(respuestas))


def test_comprobar_inf21_sin_objetivo_de_worker_es_bloqueo(monkeypatch):
    monkeypatch.setattr(
        comun, "aws_json", lambda *a, accion, **k: {"ScalableTargets": [{"ResourceId": "service/c/embedding"}]}
    )
    with pytest.raises(comun.Bloqueo, match="INF-2.1.*worker"):
        comun.EmbeddingDev("c").comprobar_inf21()


def test_apagar_pone_rango_0_y_desired_0_a_los_dos(monkeypatch):
    aws = AwsFalso()
    _instalar(monkeypatch, aws)
    comun.EmbeddingDev("c").apagar()
    assert aws.ordenes() == [
        "application-autoscaling register-scalable-target",
        "ecs update-service",
        "application-autoscaling register-scalable-target",
        "ecs update-service",
    ]
    assert all(a[-1] == "0" for a in aws.llamadas if a[1] == "register-scalable-target")
    assert [a[5] for a in aws.llamadas if a[1] == "update-service"] == ["embedding", "worker"]


def test_hora_bogota_es_utc_menos_5():
    assert comun.hora_bogota(datetime(2026, 10, 26, 2, 30, tzinfo=UTC)).strftime("%Y-%m-%d %H:%M") == "2026-10-25 21:30"


# --- token en las peticiones y argumentos propios ---------------------------------------------------------------


class _Respuesta:
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true}'


def test_http_get_y_post_con_token_ponen_authorization(monkeypatch):
    vistas = []

    def urlopen(peticion, timeout=0):
        vistas.append(dict(peticion.header_items()))
        return _Respuesta()

    monkeypatch.setattr(comun.urllib.request, "urlopen", urlopen)
    comun.http_get("https://a.com/v1/admin/videos", token="t-secreto")
    comun.http_post_json("https://a.com/v1/collect/videos", {}, token="t-secreto")
    comun.http_get("https://a.com/v1/health")
    assert vistas[0]["Authorization"] == "Bearer t-secreto"
    assert vistas[1]["Authorization"] == "Bearer t-secreto"
    assert "Authorization" not in vistas[2]
    assert all("X-request-id" in v for v in vistas)


def test_validador_con_argumentos_propios(tmp_path: Path):
    vistos = {}

    def cuerpo(v: comun.Validador) -> None:
        vistos["video"] = v.args.video

    v = comun.Validador(
        lote="FE-X.Y",
        validacion="validation-x-y",
        descripcion="",
        comprobaciones=["C1"],
        argumentos=lambda p: p.add_argument("--video", default=None),
    )
    informe = tmp_path / "i.json"
    assert v.correr(cuerpo, ["--entorno", "local", "--video", "Entrada norte", "--informe", str(informe)]) == 0
    assert vistos["video"] == "Entrada norte"
    assert json.loads(informe.read_text(encoding="utf-8"))["resultado"] == "pasa"
