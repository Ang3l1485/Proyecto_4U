"""BE-4.1 sin base: mensajes de `purga` y cuerpos que envía `api`, `firmar_get`, `ColaSqs.enviar`, el turno de `purga`
del `worker` y el bucle del reconciliador (ARCHITECTURE §4.12, §5.8)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber

from app import worker
from app.clientes import s3, sqs
from app.clientes.s3 import AlmacenS3
from app.clientes.sqs import ColaSqs, FalloSqs, MensajeSqs
from app.config import Settings
from app.db import sesion
from app.dominio import mensajes
from app.dominio.mensajes import NoReconocido, PurgarImagen, PurgarVideo, Reprocesar
from app.dominio.recoleccion import clave_dataset, clave_miniatura
from app.servicios import ingesta, purga

V = uuid.UUID("9c1d0000-0000-4000-8000-000000000001")
I = uuid.UUID("a91f0000-0000-4000-8000-000000000002")  # noqa: E741
ADMIN = uuid.UUID("7c1e0000-0000-4000-8000-000000000003")
AHORA = datetime(2026, 10, 23, 15, 4, 5, 999999, tzinfo=UTC)


class Parar(Exception):
    pass


# --- Mensajes ------------------------------------------------------------------------------------------------------
def test_cuerpos_de_api_y_su_lectura():
    video = json.loads(mensajes.cuerpo_purgar_video(V, ADMIN, AHORA))
    assert video == {
        "tipo": "purgar_video",
        "version": 1,
        "video_id": str(V),
        "solicitado_por": str(ADMIN),
        "solicitado_en": "2026-10-23T15:04:05Z",
    }
    assert mensajes.interpretar_purga(json.dumps(video)) == PurgarVideo(video_id=V)
    imagen = json.loads(mensajes.cuerpo_purgar_imagen(I, V, None, AHORA))
    assert imagen["s3_keys"] == [f"dataset/{V}/{I}.jpg", f"thumbs/{V}/{I}.jpg"]
    assert imagen["solicitado_por"] is None
    assert mensajes.interpretar_purga(json.dumps(imagen)) == PurgarImagen(
        imagen_id=I, video_id=V, s3_keys=(clave_dataset(V, I), clave_miniatura(V, I))
    )
    reprocesar = mensajes.cuerpo_reprocesar(I, ADMIN, AHORA)
    assert mensajes.interpretar(reprocesar) == Reprocesar(imagen_id=I)  # lo lee la ingesta de BE-2.2


@pytest.mark.parametrize(
    ("cuerpo", "motivo"),
    [
        ("no es json", "cuerpo que no es JSON"),
        ("[1]", "cuerpo que no es un objeto JSON"),
        ('{"tipo": "otra"}', "tipo desconocido"),
        ('{"tipo": "purgar_video", "version": 2, "video_id": "x"}', "versión no admitida"),
        ('{"tipo": "purgar_video", "version": true, "video_id": "x"}', "versión no admitida"),
        ('{"tipo": "purgar_video", "version": 1, "video_id": "no-uuid"}', "sin video_id"),
        (json.dumps({"tipo": "purgar_imagen", "version": 1, "video_id": str(V)}), "sin imagen_id"),
        (
            json.dumps({"tipo": "purgar_imagen", "version": 1, "video_id": str(V), "imagen_id": str(I), "s3_keys": []}),
            "s3_keys",
        ),
        (
            json.dumps(
                {
                    "tipo": "purgar_imagen",
                    "version": 1,
                    "video_id": str(V),
                    "imagen_id": str(I),
                    "s3_keys": [f"dataset/{V}/"],  # un prefijo entero: nunca
                }
            ),
            "s3_keys",
        ),
    ],
)
def test_mensajes_de_purga_que_no_encajan(cuerpo, motivo):
    resultado = mensajes.interpretar_purga(cuerpo)
    assert isinstance(resultado, NoReconocido) and motivo in resultado.motivo


# --- Clientes ------------------------------------------------------------------------------------------------------
@pytest.fixture
def credenciales(monkeypatch):
    for variable in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAPRUEBASPRUEBAS00")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "clave-secreta-de-pruebas")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/no/existe")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/no/existe")


def test_url_get_firmada_sin_encabezados_y_ttl(credenciales):
    almacen = AlmacenS3("bucket-x", cliente=s3.crear_cliente("us-east-1"), reloj=lambda: AHORA)
    firmada = almacen.firmar_get(clave_miniatura(V, I), 3600)
    partes = urlsplit(firmada.url)
    consulta = parse_qs(partes.query)
    assert partes.path == f"/thumbs/{V}/{I}.jpg"
    assert consulta["X-Amz-Expires"] == ["3600"]
    assert consulta["X-Amz-SignedHeaders"] == ["host"]  # un GET sin encabezados que respetar
    assert firmada.expira_en == datetime(2026, 10, 23, 16, 4, 5, tzinfo=UTC)
    varias = asyncio.run(s3.firmar_gets(almacen, ["a.jpg", "a.jpg", "b.jpg"], 60))
    assert set(varias) == {"a.jpg", "b.jpg"}


def test_enviar_a_sqs_y_su_error(credenciales):
    cola = ColaSqs("https://sqs.us-east-1.amazonaws.com/1/purga", cliente=sqs.crear_cliente("us-east-1"))
    with Stubber(cola.cliente) as stub:
        stub.add_response(
            "send_message",
            {"MessageId": "m-1", "MD5OfMessageBody": "0" * 32},
            {"QueueUrl": cola.url, "MessageBody": "{}"},
        )
        stub.add_client_error("send_message", service_error_code="AccessDenied", http_status_code=403)
        assert cola.enviar("{}") == "m-1"
        with pytest.raises(FalloSqs, match="enviar: ClientError: AccessDenied"):
            cola.enviar('{"secreto": "no sale"}')


def test_colas_comparten_cliente(credenciales):
    colas = sqs.crear_colas("https://q/ingesta", "https://q/purga", "us-east-1")
    assert colas.ingesta.cliente is colas.purga.cliente
    assert sqs.crear_colas(None, None, "us-east-1") == sqs.Colas()


# --- worker: turno de purga ----------------------------------------------------------------------------------------
AJUSTES = Settings(worker_espera_embedding_s=0.01, embedding_url="http://embedding.prueba:8080")


class ColaPurga:
    def __init__(self, lotes: list[list[MensajeSqs]]) -> None:
        self.lotes = lotes
        self.esperas: list[int] = []
        self.borrados: list[str] = []
        self.fallar_recibir = False

    def recibir(self, maximo: int, espera_s: int) -> list[MensajeSqs]:
        self.esperas.append(espera_s)
        if self.fallar_recibir:
            raise FalloSqs("recibir: ClientError: 500")
        return self.lotes.pop(0) if self.lotes else []

    def borrar(self, recibo: str) -> None:
        self.borrados.append(recibo)


def _mensaje(n: int, cuerpo: str = "{}") -> MensajeSqs:
    return MensajeSqs(id=f"p{n}", recibo=f"rp{n}", cuerpo=cuerpo, recepciones=1)


def test_turno_purga_borra_los_terminados(monkeypatch, logs_json):
    async def procesar(deps, recibidos):
        return [purga.DecisionPurga(m, borrar=m.id != "p2") for m in recibidos]

    monkeypatch.setattr(purga, "procesar_purga", procesar)
    cola = ColaPurga([[_mensaje(1), _mensaje(2)]])
    asyncio.run(worker.turno_purga(asyncio.Event(), AJUSTES, cola=cola, deps=None, espera_s=1))
    assert cola.borrados == ["rp1"] and cola.esperas == [1]
    [lote] = [linea for linea in logs_json.lineas if linea["evento"] == "lote_purga"]
    assert (lote["mensajes"], lote["borrados"], lote["retenidos"]) == (2, 1, 1)


def test_turno_purga_con_fallo_de_sqs(logs_json):
    cola = ColaPurga([])
    cola.fallar_recibir = True
    asyncio.run(worker.turno_purga(asyncio.Event(), AJUSTES, cola=cola, deps=None, espera_s=0.01))
    [fallo] = [linea for linea in logs_json.lineas if linea["evento"] == "cola_fallida"]
    assert fallo["cola"] == "purga" and fallo["operacion"] == "recibir"


def test_mensaje_de_purga_no_reconocido_se_borra_sin_tocar_nada(logs_json):
    [decision] = asyncio.run(purga.procesar_purga(None, [_mensaje(1, "no es json")]))  # sin base ni S3
    assert decision.borrar
    [linea] = [linea for linea in logs_json.lineas if linea["evento"] == "mensaje_no_reconocido"]
    assert linea["cola"] == "purga"


def test_procesar_purga_transitorio_y_terminado(monkeypatch, logs_json):
    resultados = [
        s3.FalloS3("borrar: ClientError: 500"),
        sesion.BaseNoDisponible("sin base"),
        RuntimeError("raro"),
        None,
    ]

    async def purgar_video(deps, video_id):
        resultado = resultados.pop(0)
        if resultado is not None:
            raise resultado

    monkeypatch.setattr(purga, "purgar_video", purgar_video)
    cuerpo = mensajes.cuerpo_purgar_video(V, ADMIN)
    decisiones = asyncio.run(purga.procesar_purga(None, [_mensaje(n, cuerpo) for n in range(4)]))
    assert [d.borrar for d in decisiones] == [False, False, False, True]
    niveles = [linea["nivel"] for linea in logs_json.lineas if linea["evento"] == "purga_transitoria"]
    assert niveles == ["WARNING", "WARNING", "ERROR"]


def test_el_bucle_hace_la_purga_con_y_sin_embedding(monkeypatch):
    """Sin embeddings, la espera de `WORKER_ESPERA_EMBEDDING_S` es una recepción de `purga`; con embeddings, una corta
    de `ESPERA_PURGA_S` antes de cada recepción de `ingesta`."""
    llamadas: list[tuple[str, float]] = []

    async def procesar_lote(deps, recibidos):
        return [ingesta.Decision(m, borrar=True) for m in recibidos]

    monkeypatch.setattr(ingesta, "procesar_lote", procesar_lote)

    async def principal() -> None:
        detener = asyncio.Event()
        estados = iter([False, True, True])

        class ColaIngesta:
            def recibir(self, maximo, espera_s):
                llamadas.append(("ingesta", espera_s))
                if sum(1 for x in llamadas if x[0] == "ingesta") >= 2:
                    detener.set()
                return []

        async def esta_listo(ajustes):
            return next(estados, True)

        async def turno(espera_s):
            llamadas.append(("purga", espera_s))

        await asyncio.wait_for(
            worker.consumir(
                detener, AJUSTES, cola=ColaIngesta(), deps=None, esta_listo=esta_listo, espera_cola_s=0, purga=turno
            ),
            timeout=5,
        )

    asyncio.run(principal())
    assert llamadas[:3] == [("purga", 0.01), ("purga", worker.ESPERA_PURGA_S), ("ingesta", 0)]


# --- api: reconciliador --------------------------------------------------------------------------------------------
def test_reconciliador_espera_reencola_cada_intervalo_y_sigue_tras_un_fallo(logs_json):
    esperas: list[float] = []
    resultados = [
        purga.Reencolado(2, 2),
        sesion.BaseNoDisponible("sin base"),
        RuntimeError("raro"),
        purga.Reencolado(0, 0),
    ]
    llamadas: list[int] = []

    async def dormir(segundos: float) -> None:
        esperas.append(segundos)
        if len(esperas) > len(resultados):
            raise Parar

    async def accion(motor, cola, minutos):
        llamadas.append(minutos)
        resultado = resultados[len(llamadas) - 1]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    with pytest.raises(Parar):
        asyncio.run(purga.reconciliador(object(), object(), 10, dormir=dormir, accion=accion))
    assert esperas == [60.0, 600.0, 600.0, 600.0, 600.0]
    assert llamadas == [10, 10, 10, 10]
    propios = ("purgas_reencoladas", "reconciliador_fallido")
    eventos = [(linea["evento"], linea["nivel"]) for linea in logs_json.lineas if linea["evento"] in propios]
    assert eventos[:3] == [
        ("purgas_reencoladas", "INFO"),
        ("reconciliador_fallido", "WARNING"),
        ("reconciliador_fallido", "ERROR"),
    ]


def test_el_reconciliador_se_cancela_sin_ruido(logs_json):
    async def principal() -> None:
        tarea = asyncio.create_task(purga.reconciliador(object(), object(), 10))
        await asyncio.sleep(0)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(principal())
    assert [linea for linea in logs_json.lineas if "reconcil" in linea["evento"] or "reencol" in linea["evento"]] == []


def test_sql_de_pendientes():
    texto = str(purga.sql_pendientes(10))
    assert "purgado_en IS NULL" in texto and "make_interval" in texto and "LIMIT" in texto
