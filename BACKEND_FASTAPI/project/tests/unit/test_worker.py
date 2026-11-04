"""`app.worker`: latido sin consumo (BE-1.1) y bucle de ingesta (BE-2.2) con cola, embeddings y lote simulados."""

from __future__ import annotations

import asyncio

import pytest

from app import worker
from app.clientes.sqs import FalloSqs, MensajeSqs
from app.config import Settings
from app.servicios import ingesta

AJUSTES = Settings(worker_espera_embedding_s=0.01, embedding_url="http://embedding.prueba:8080")


def test_emite_latidos_y_se_detiene(logs_json):
    async def escenario():
        detener = asyncio.Event()
        tarea = asyncio.create_task(worker.ejecutar(detener, intervalo_s=0.01))
        await asyncio.sleep(0.05)
        detener.set()
        await asyncio.wait_for(tarea, timeout=1)

    asyncio.run(escenario())
    latidos = [linea for linea in logs_json.lineas if linea["evento"] == "latido"]
    assert len(latidos) >= 2 and latidos[0]["modo"] == "sin_consumo"


class Cola:
    def __init__(self, lotes: list[list[MensajeSqs]], detener: asyncio.Event) -> None:
        self.lotes = lotes
        self.detener = detener
        self.recibidas = 0
        self.borrados: list[str] = []
        self.devueltos: list[str] = []
        self.fallar_borrar = False

    def recibir(self, maximo: int, espera_s: int) -> list[MensajeSqs]:
        assert maximo == 10 and espera_s == 0
        self.recibidas += 1
        if not self.lotes:
            self.detener.set()
            return []
        return self.lotes.pop(0)

    def borrar(self, recibo: str) -> None:
        if self.fallar_borrar:
            raise FalloSqs("borrar: ClientError: 500")
        self.borrados.append(recibo)

    def devolver(self, recibo: str) -> None:
        self.devueltos.append(recibo)


def _mensaje(n: int) -> MensajeSqs:
    return MensajeSqs(id=f"m{n}", recibo=f"r{n}", cuerpo="{}", recepciones=1)


def _correr(cola_de, listo, monkeypatch, decidir=lambda m: True):
    async def procesar_lote(deps, recibidos):
        return [ingesta.Decision(m, borrar=decidir(m)) for m in recibidos]

    monkeypatch.setattr(ingesta, "procesar_lote", procesar_lote)

    async def escenario():
        detener = asyncio.Event()
        cola = cola_de(detener)

        async def esta_listo(ajustes):
            return listo(cola)

        await asyncio.wait_for(
            worker.consumir(detener, AJUSTES, cola=cola, deps=None, esta_listo=esta_listo, espera_cola_s=0), timeout=5
        )
        return cola

    return asyncio.run(escenario())


def test_borra_los_terminados_y_deja_los_transitorios(monkeypatch, logs_json):
    cola = _correr(
        lambda d: Cola([[_mensaje(1), _mensaje(2), _mensaje(3)]], d),
        lambda c: True,
        monkeypatch,
        decidir=lambda m: m.id != "m2",
    )
    assert cola.borrados == ["r1", "r3"] and cola.devueltos == []
    lote = next(linea for linea in logs_json.lineas if linea["evento"] == "lote_ingesta")
    assert (lote["mensajes"], lote["borrados"], lote["retenidos"]) == (3, 2, 1)
    assert any(linea["evento"] == "latido" and linea["modo"] == "ingesta" for linea in logs_json.lineas)


def test_sin_embedding_no_recibe(monkeypatch, logs_json):
    estado = {"consultas": 0}

    def listo(cola):
        estado["consultas"] += 1
        if estado["consultas"] >= 5:
            cola.detener.set()
        return False

    cola = _correr(lambda d: Cola([[_mensaje(1)]], d), listo, monkeypatch)
    assert cola.recibidas == 0 and cola.borrados == []
    eventos = [linea["evento"] for linea in logs_json.lineas]
    assert eventos.count("embedding_no_listo") == 1  # solo al cambiar


def test_si_embedding_se_apaga_mientras_espera_devuelve_los_mensajes(monkeypatch):
    respuestas = iter([True, False, False])

    def listo(cola):
        valor = next(respuestas, None)
        if valor is None:
            cola.detener.set()
            return False
        return valor

    cola = _correr(lambda d: Cola([[_mensaje(1), _mensaje(2)]], d), listo, monkeypatch)
    assert cola.devueltos == ["r1", "r2"] and cola.borrados == []


def test_un_fallo_de_sqs_no_tumba_el_bucle(monkeypatch, logs_json):
    def cola_de(detener):
        cola = Cola([[_mensaje(1)]], detener)
        cola.fallar_borrar = True
        return cola

    cola = _correr(cola_de, lambda c: True, monkeypatch)
    assert cola.borrados == []
    assert any(linea["evento"] == "cola_fallida" for linea in logs_json.lineas)


@pytest.mark.parametrize(
    ("variables", "faltan"),
    [
        ({}, ["SQS_URL_INGESTA", "S3_BUCKET_DATASET", "EMBEDDING_URL", "DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"]),
        (
            {
                "sqs_url_ingesta": "https://sqs/x",
                "s3_bucket_dataset": "b",
                "embedding_url": "http://e:8080",
                "db_host": "h",
                "db_name": "n",
                "db_user": "u",
                "db_password": "p",
            },
            [],
        ),
    ],
)
def test_configuracion_que_necesita_la_ingesta(variables, faltan):
    assert worker.faltan_para_ingesta(Settings(**variables)) == faltan
