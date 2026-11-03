"""`app.dominio.mensajes.interpretar`: los mensajes de la cola `ingesta` de ARCHITECTURE §5.8."""

from __future__ import annotations

import json
import uuid

import pytest

from app.dominio.mensajes import EventosS3, NoReconocido, ObjetoSubido, PruebaS3, Reprocesar, interpretar

VIDEO = "9c1d0000-0000-4000-8000-000000000001"
IMAGEN = "a91f0000-0000-4000-8000-000000000002"


def evento(*registros: dict) -> str:
    return json.dumps({"Records": list(registros)})


def registro(clave: str, etag: str | None = '"abc"', size: object = 345678, nombre: str = "ObjectCreated:Put") -> dict:
    objeto = {"key": clave, "size": size} | ({"eTag": etag} if etag is not None else {})
    return {"eventName": nombre, "s3": {"bucket": {"name": "b"}, "object": objeto}}


def test_evento_s3_con_clave_codificada_y_varios_records():
    cuerpo = evento(
        registro(f"dataset/{VIDEO}/{IMAGEN}.jpg", etag="abc"),
        registro("dataset/con+espacio%2Fraro.jpg", etag=None, size="x"),
        registro("dataset/x.jpg", nombre="ObjectRemoved:Delete"),
    )
    resultado = interpretar(cuerpo)
    assert resultado == EventosS3(
        objetos=(
            ObjetoSubido(clave=f"dataset/{VIDEO}/{IMAGEN}.jpg", etag="abc", bytes=345678),
            ObjetoSubido(clave="dataset/con espacio/raro.jpg", etag=None, bytes=None),
        ),
        ignorados=1,
    )


def test_etag_sin_comillas():
    resultado = interpretar(evento(registro(f"dataset/{VIDEO}/{IMAGEN}.jpg", etag='"9b2c"')))
    assert resultado.objetos[0].etag == "9b2c"


def test_prueba_de_s3():
    cuerpo = json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": "b"})
    assert interpretar(cuerpo) == PruebaS3()


def test_reprocesar():
    cuerpo = {"tipo": "reprocesar_imagen", "version": 1, "imagen_id": IMAGEN, "solicitado_por": "x"}
    assert interpretar(json.dumps(cuerpo)) == Reprocesar(imagen_id=uuid.UUID(IMAGEN))


@pytest.mark.parametrize(
    "cuerpo",
    [
        "no es json",
        "[1, 2]",
        json.dumps({"hola": 1}),
        json.dumps({"Records": "x"}),
        json.dumps({"tipo": "purgar_video", "version": 1}),
        json.dumps({"tipo": "reprocesar_imagen", "version": 2, "imagen_id": IMAGEN}),
        json.dumps({"tipo": "reprocesar_imagen", "version": True, "imagen_id": IMAGEN}),
        json.dumps({"tipo": "reprocesar_imagen", "version": 1, "imagen_id": "no-uuid"}),
    ],
)
def test_no_reconocidos(cuerpo):
    assert isinstance(interpretar(cuerpo), NoReconocido)
