"""Pruebas de validate21.py con Gradle, la API, AWS (S3 y embedding) y el reloj simulados (sin teléfono ni JDK)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import comun
import pytest
import validate21

URL = "https://api.example.com/v1"
ADMIN = ("admin@campus.edu.co", "Clave-Secreta-1")
TOKEN = "eyJ-token-secreto"
VIDEO_ID = "6f1c2d3e-0000-4000-8000-000000000001"
PLAN_APP = (
    # Como el PLAN real: la fila de §2.1 (nombre, dependencias) va antes que la de estado de §3.
    "| FE-2.3 | Pruebas en dispositivo y robustez de la recolección | FE-0.11, FE-0.12 | — | [`validation-2-3`](x) |\n"
    "| FE-1.2 | 1 | Hecho | [1-2](x) | `4d578c5` 2026-10-25 | 0.5.0 | | |\n"
    "| FE-2.3 | 2 | Hecho | [2-3](x) | `abc1234` 2026-10-26 | 0.7.0 | | |\n"
)
PLAN_BACKEND = "| BE-2.1 | 2 | Hecho | x | `9f6ed19` | 0.8.0 | |\n| BE-2.2 | 2 | Hecho | x | `3b01b68` | 0.9.2 | |\n"


class Reloj:
    def __init__(self) -> None:
        self.t = 1000.0

    def reloj(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += s


class EmbeddingFalso:
    """Sustituye a comun.EmbeddingDev: registra lo que se le pide."""

    eventos: list[str] = []
    fallar = False

    def __init__(self, cluster, embedding="embedding", worker="worker"):
        EmbeddingFalso.eventos.append(f"crear {cluster} {embedding} {worker}")

    def comprobar_inf21(self):
        EmbeddingFalso.eventos.append("inf21")
        return "ok"

    def encender(self, listo):
        EmbeddingFalso.eventos.append("encender")
        if EmbeddingFalso.fallar:
            raise comun.Bloqueo("INF-2.1: embedding no quedó sano en 10 min (sin tarea HEALTHY)")
        Mundo.actual.embedding = "ok"
        assert listo()
        return 200.0

    def apagar(self):
        EmbeddingFalso.eventos.append("apagar")

    def latido(self):
        EmbeddingFalso.eventos.append("latido")


class Mundo:
    actual: Mundo

    def __init__(self, tmp_path: Path, *, n_fotos=60, estados=("procesando", "procesado"), embedding="no_disponible"):
        Mundo.actual = self
        self.tmp = tmp_path
        self.reloj = Reloj()
        self.embedding = embedding
        self.estados = list(estados)
        self.n_fotos = n_fotos
        self.lecturas_detalle = 0
        self.videos = [{"id": VIDEO_ID, "numero": 7, "nombre": "Entrada norte", "ref_cliente": "rec_0003"}]
        self.objetos: dict[str, comun.ObjetoS3] = {}
        self.ref_cliente = "rec_0003"
        self.total_fotos = n_fotos
        self.error_foto = None
        self.gradle_llamadas: list[tuple[str, ...]] = []
        self.plan_app = PLAN_APP
        self.hora = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)  # 10:00 en Bogotá
        EmbeddingFalso.eventos = []
        EmbeddingFalso.fallar = False

    def instalar(self, monkeypatch):
        plan_app = self.tmp / "PLAN_APP.md"
        plan_app.write_text(self.plan_app, encoding="utf-8")
        plan_be = self.tmp / "PLAN_BE.md"
        plan_be.write_text(PLAN_BACKEND, encoding="utf-8")
        monkeypatch.setattr(comun, "PLAN_APP", plan_app)
        monkeypatch.setattr(comun, "PLAN_BACKEND", plan_be)
        monkeypatch.setattr(comun, "DIR_RESULTADOS_PRUEBAS", self.tmp)
        monkeypatch.setattr(comun, "gradle", self.gradle)
        monkeypatch.setattr(comun, "url_api_vigente", lambda: (URL, "terraform output api_base_url"))
        monkeypatch.setattr(comun, "credenciales_admin", lambda entorno: ADMIN)
        monkeypatch.setattr(comun, "http_get", self.http_get)
        monkeypatch.setattr(comun, "http_post_json", self.http_post_json)
        monkeypatch.setattr(comun, "cuenta_aws", lambda: "arn:aws:iam::648617469176:root")
        monkeypatch.setattr(comun, "terraform_outputs", self.outputs)
        monkeypatch.setattr(comun, "leer_objeto_s3", self.leer_objeto_s3)
        monkeypatch.setattr(comun, "EmbeddingDev", EmbeddingFalso)
        monkeypatch.setattr(comun, "hora_bogota", lambda ahora=None: self.hora.astimezone(comun.ZONA_BOGOTA))
        monkeypatch.setattr(comun, "reloj", self.reloj.reloj)
        monkeypatch.setattr(comun, "dormir", self.reloj.dormir)
        monkeypatch.setattr(comun, "commit_actual", lambda: "abc1234")

    # --- Gradle

    def gradle(self, *args, timeout=0):
        self.gradle_llamadas.append(args)
        if "testDebugUnitTest" in args:
            casos = {
                "SubidaRecorridoTest": 13,
                "ColaSubidaTest": 8,
                "AlmacenRecorridosTest": 13,
                "RecodificacionFotoTest": 12,
            }
            for clase, n in casos.items():
                if f"*.{clase}" in args:
                    (self.tmp / f"TEST-com.example.myapplication.data.local.{clase}.xml").write_text(
                        f'<testsuite tests="{n}" failures="0" errors="0" skipped="0"/>', encoding="utf-8"
                    )
            return comun.Resultado(0, "BUILD SUCCESSFUL", "")
        return comun.Resultado(0, "Gradle 8.7\nJVM:          21.0.11 (JetBrains s.r.o. 21.0.11+1-b1163.116)\n", "")

    # --- AWS

    def outputs(self, directorio=None):
        return {
            "bucket_dataset": "campus-locator-dev-dataset-648617469176",
            "ecs_cluster": "campus-locator-dev",
            "ecs_servicios": {"api": "api", "worker": "worker", "embedding": "embedding"},
        }

    def leer_objeto_s3(self, bucket, clave, primeros=131072):
        assert bucket == "campus-locator-dev-dataset-648617469176"
        return self.objetos.get(clave) or comun.ObjetoS3(clave, 512_345, (1600, 1200))

    # --- API

    def detalle(self) -> dict:
        estado = self.estados[min(self.lecturas_detalle, len(self.estados) - 1)]
        self.lecturas_detalle += 1
        fotos = []
        for i in range(1, self.n_fotos + 1):
            e = "procesada" if estado == "procesado" else "subida"
            if self.error_foto == i:
                e = "error"
            fotos.append(
                {
                    "id": f"img-{i}",
                    "video_id": VIDEO_ID,
                    "orden": i,
                    "estado": e,
                    "error": "lado menor 200 px (mínimo 320)" if e == "error" else None,
                }
            )
        conteo = {"pendiente_subida": 0, "subida": 0, "procesada": 0, "error": 0}
        for f in fotos:
            conteo[f["estado"]] += 1
        return {
            "id": VIDEO_ID,
            "numero": 7,
            "nombre": "Entrada norte",
            "ref_cliente": self.ref_cliente,
            "estado": estado,
            "total_fotos": self.total_fotos,
            "conteo": conteo,
            "fotos": fotos,
        }

    def http_get(self, url, timeout=15.0, token=None):
        ruta = url.removeprefix(URL)
        if ruta == "/health":
            return comun.RespuestaHttp(200, {}, '{"estado":"ok"}', 5)
        if ruta == "/health/ready":
            return comun.RespuestaHttp(
                200, {}, json.dumps({"estado": "ok", "db": "ok", "embedding": self.embedding}), 5
            )
        assert token == TOKEN, f"{ruta} sin token"
        if ruta.startswith("/admin/videos?q="):
            return comun.RespuestaHttp(200, {}, json.dumps({"items": self.videos, "total": len(self.videos)}), 5)
        if ruta == f"/admin/videos/{VIDEO_ID}":
            return comun.RespuestaHttp(200, {}, json.dumps(self.detalle()), 5)
        return comun.RespuestaHttp(404, {}, '{"error":{"codigo":"NO_ENCONTRADO"}}', 5)

    def http_post_json(self, url, cuerpo, timeout=15.0, token=None):
        ruta = url.removeprefix(URL)
        if ruta == "/auth/login":
            assert cuerpo == {"identificador": ADMIN[0], "password": ADMIN[1]}
            return comun.RespuestaHttp(
                200,
                {},
                json.dumps(
                    {
                        "token": TOKEN,
                        "expira_en": "2026-10-26T03:00:00Z",
                        "usuario": {"nombre": "Admin", "rol": "admin"},
                    }
                ),
                5,
            )
        if ruta == "/collect/videos":
            assert token == TOKEN and cuerpo == {}
            return comun.RespuestaHttp(422, {}, '{"error":{"codigo":"VALIDACION","mensaje":"x","detalle":null}}', 5)
        return comun.RespuestaHttp(404, {}, "{}", 5)


def _correr(tmp_path, *argv):
    informe = tmp_path / "informe.json"
    codigo = validate21.main([*argv, "--informe", str(informe)])
    return codigo, json.loads(informe.read_text(encoding="utf-8"))


def _estados(datos):
    return {e["id"]: e["estado"] for e in datos["precondiciones"] + datos["comprobaciones"]}


def _detalle(datos, id_):
    return next(e["detalle"] for e in datos["precondiciones"] + datos["comprobaciones"] if e["id"] == id_)


# --- local ---------------------------------------------------------------------------------------------------------


def test_local_corre_las_pruebas_y_la_ruta_y_omite_lo_de_dev(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "local")
    assert codigo == 0
    estados = _estados(datos)
    assert estados == {
        "P1": "pasa",
        "C1": "omitida",
        "C2a": "pasa",
        "C2b": "omitida",
        "C3a": "pasa",
        "C3b": "omitida",
        "C4": "pasa",
    }
    assert "SubidaRecorridoTest 13/13" in _detalle(datos, "C2a")
    assert "RecodificacionFotoTest 12/12" in _detalle(datos, "C3a")
    assert "ResumenVideoScreen" in _detalle(datos, "C4")  # contra el MainActivity.kt real
    assert len([a for a in m.gradle_llamadas if "testDebugUnitTest" in a]) == 1  # una sola ejecución de Gradle
    assert [x["id"] for x in datos["manuales"]] == ["C2c"]


# --- dev -----------------------------------------------------------------------------------------------------------


def test_dev_espera_la_ingesta_enciende_embedding_y_lo_apaga(tmp_path, monkeypatch, capsys):
    m = Mundo(tmp_path, estados=("procesando", "procesando", "procesado"))
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 0, datos
    estados = _estados(datos)
    assert all(estados[p] == "pasa" for p in ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"))
    assert all(estados[c] == "pasa" for c in ("C1", "C2a", "C2b", "C3a", "C3b", "C4"))
    assert "encendido por el validador" in _detalle(datos, "P8")
    assert EmbeddingFalso.eventos[-1] == "apagar"  # limpieza: lo deja como lo encontró
    assert "60 fotos, procesada 60" in _detalle(datos, "C1")
    assert "máx. 512345 B" in _detalle(datos, "C3b") and "1600 px" in _detalle(datos, "C3b")
    salida = capsys.readouterr()
    texto = salida.out + salida.err + json.dumps(datos)
    assert TOKEN not in texto and ADMIN[1] not in texto


def test_dev_video_ya_procesado_no_toca_embedding(tmp_path, monkeypatch):
    m = Mundo(tmp_path, estados=("procesado",))
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 0
    assert "ya está procesado" in _detalle(datos, "P8")
    assert "encender" not in EmbeddingFalso.eventos and "apagar" not in EmbeddingFalso.eventos


def test_dev_embedding_ya_encendido_solo_publica_un_latido(tmp_path, monkeypatch):
    m = Mundo(tmp_path, embedding="ok")
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 0
    assert "latido" in EmbeddingFalso.eventos and "apagar" not in EmbeddingFalso.eventos


def test_dev_sin_video_es_3(tmp_path, monkeypatch):
    Mundo(tmp_path).instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev")
    assert codigo == 3
    assert _estados(datos)["P2"] == "falla"
    assert _estados(datos)["P3"] == "no evaluada"


def test_dev_video_inexistente_o_repetido_es_3(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.videos = []
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 3 and "no hay ningún video" in _detalle(datos, "P7")
    m.videos = [
        {"id": "a", "numero": 1, "nombre": "Entrada norte", "ref_cliente": "rec_0001"},
        {"id": "b", "numero": 2, "nombre": "Entrada norte", "ref_cliente": "rec_0002"},
        {"id": "c", "numero": 3, "nombre": "Entrada norte 2", "ref_cliente": "rec_0003"},
    ]
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 3 and "hay 2 videos" in _detalle(datos, "P7")


def test_dev_fe23_sin_hecho_bloquea_con_codigo_2(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.plan_app = PLAN_APP.replace(
        "| FE-2.3 | 2 | Hecho | [2-3](x) | `abc1234` 2026-10-26 |", "| FE-2.3 | 2 | En curso | [2-3](x) | — |"
    )
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 2
    assert _estados(datos)["P4"] == "falla"
    assert _estados(datos)["P8"] == "no evaluada"


def test_dev_foto_fuera_de_limites_falla_c3b(tmp_path, monkeypatch):
    m = Mundo(tmp_path, estados=("procesado",))
    clave = f"dataset/{VIDEO_ID}/img-7.jpg"
    m.objetos[clave] = comun.ObjetoS3(clave, 4_500_000, (2000, 1500))
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 1
    assert _estados(datos)["C3b"] == "falla"
    assert "img-7.jpg: 4500000 B, 2000×1500 px" in _detalle(datos, "C3b")


def test_dev_con_errores_falla_c1_con_el_motivo(tmp_path, monkeypatch):
    m = Mundo(tmp_path, estados=("con_errores",))
    m.error_foto = 3
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 1
    assert "con_errores" in _detalle(datos, "C1") and "lado menor 200 px" in _detalle(datos, "C1")


def test_dev_pocas_fotos_o_duplicadas(tmp_path, monkeypatch):
    m = Mundo(tmp_path, n_fotos=40, estados=("procesado",))
    m.total_fotos = 41  # la app declaró una más de las que hay
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 1
    assert "40 fotos (mínimo 50)" in _detalle(datos, "C1")
    assert _estados(datos)["C2b"] == "falla"


def test_dev_minimo_fotos_rebaja_el_umbral_de_c1(tmp_path, monkeypatch):
    m = Mundo(tmp_path, n_fotos=10, estados=("procesado",))
    m.total_fotos = 10
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte", "--minimo-fotos", "10")
    assert codigo == 0, datos
    assert "10 fotos, procesada 10" in _detalle(datos, "C1")
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte", "--minimo-fotos", "11")
    assert codigo == 1 and "10 fotos (mínimo 11)" in _detalle(datos, "C1")


def test_dev_espera_15_min_y_falla_si_sigue_pendiente(tmp_path, monkeypatch):
    m = Mundo(tmp_path, estados=("pendiente",))
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 1
    assert "¿terminó la subida en el teléfono?" in _detalle(datos, "C1")
    assert m.reloj.t - 1000 >= validate21.LIMITE_PROCESADO_S


def test_dev_despues_de_la_hora_limite_no_enciende_embedding(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.hora = datetime(2026, 10, 26, 2, 45, tzinfo=UTC)  # 21:45 en Bogotá
    m.instalar(monkeypatch)
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 3
    assert "21:45" in _detalle(datos, "P8")
    assert "encender" not in EmbeddingFalso.eventos


def test_dev_encendido_fallido_bloquea_y_apaga_igual(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.instalar(monkeypatch)
    EmbeddingFalso.fallar = True
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte")
    assert codigo == 2
    assert EmbeddingFalso.eventos[-1] == "apagar"


def test_solo_c4_en_dev_no_necesita_aws_ni_embedding(tmp_path, monkeypatch):
    m = Mundo(tmp_path)
    m.instalar(monkeypatch)
    monkeypatch.setattr(comun, "cuenta_aws", lambda: (_ for _ in ()).throw(AssertionError("no debía llamar a AWS")))
    codigo, datos = _correr(tmp_path, "--entorno", "dev", "--video", "Entrada norte", "--solo", "C4")
    assert codigo == 0
    assert "no hace falta" in _detalle(datos, "P8")


# --- C4 (comprobación estática) ------------------------------------------------------------------------------------

RUTAS_BIEN = """
        composable("admin/recoleccion") {
                RecoleccionScreen(
                    onFinalizado = { resumen ->
                        nav.navigate("admin/recoleccion/resumen?video=${resumen.videoId}") {
                            popUpTo("admin/ubicacion-manual") { inclusive = true }
                        }
                    },
                )
        }
        composable(
            "admin/recoleccion/resumen?video={video}",
        ) { entrada -> ResumenVideoScreen(videoId = null, onIrAlPanel = {}) }
        composable("admin/lugares") { /* placeholder */ }
"""


def test_c4_acepta_la_ruta_con_argumento_opcional():
    assert "admin/recoleccion/resumen?video={video}" in validate21.comprobar_ruta_resumen(RUTAS_BIEN)


@pytest.mark.parametrize(
    ("texto", "mensaje"),
    [
        (RUTAS_BIEN + '\ncomposable("admin/recoleccion/resumen") { /* placeholder */ }', "placeholder"),
        (RUTAS_BIEN.replace("ResumenVideoScreen(", "Otra("), "no compone ResumenVideoScreen"),
        (
            RUTAS_BIEN.replace('nav.navigate("admin/recoleccion/resumen?video', 'nav.navigate("admin/panel?x'),
            "onFinalizado",
        ),
        (RUTAS_BIEN.replace('"admin/recoleccion/resumen?video={video}"', '"admin/otra"'), "no registra"),
    ],
)
def test_c4_rechaza(texto, mensaje):
    with pytest.raises(comun.Falla, match=mensaje):
        validate21.comprobar_ruta_resumen(texto)


def test_video_exacto_ignora_los_que_solo_contienen_el_nombre():
    items = [
        {"nombre": "Entrada norte"},
        {"nombre": "entrada norte"},
        {"nombre": "Entrada norte 2"},
        {"nombre": " Entrada norte "},
    ]
    assert len(validate21.video_exacto(items, "Entrada norte")) == 2
