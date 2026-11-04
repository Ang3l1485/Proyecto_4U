"""`python -m app.cli limpiar-validacion` contra una base real y S3 simulado (ARCHITECTURE §4.5, §5.9)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app import cli
from app.config import Settings
from app.db import sesion

pytestmark = pytest.mark.base


async def _sql(ajustes: Settings, sentencia: str, parametros: dict | None = None) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros or {})
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def sql(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_sql(ajustes, sentencia, parametros))


@pytest.fixture
def ajustes_s3(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"s3_bucket_dataset": "bucket-de-pruebas"})


@pytest.fixture
def s3(almacen_falso, monkeypatch):
    monkeypatch.setattr(cli, "crear_almacen", lambda ajustes: almacen_falso)
    return almacen_falso


def video(ajustes: Settings, s3, nombre: str, ref: str | None = None, fotos: int = 2) -> str:
    """Inserta un video con `fotos` imágenes (una con vector) y sus objetos en `dataset/` y `thumbs/`."""
    [(video_id,)] = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por) SELECT :n, :r, id FROM usuarios RETURNING id",
        n=nombre,
        r=ref or nombre,
    )
    for orden in range(1, fotos + 1):
        imagen_id = uuid.uuid4()
        sql(
            ajustes,
            "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, capturada_en, bytes_declarados) "
            "VALUES (:i, :v, :o, :k, 1, -100, now(), 10)",
            i=imagen_id,
            v=video_id,
            o=orden,
            k=f"dataset/{video_id}/{imagen_id}.jpg",
        )
        s3.subir(f"dataset/{video_id}/{imagen_id}.jpg")
        s3.subir(f"thumbs/{video_id}/{imagen_id}.jpg")
    vector = "[" + ",".join(["0.05"] * 384) + "]"
    sql(
        ajustes,
        "INSERT INTO embeddings (imagen_id, version_vector, vector) "
        "SELECT id, 'dinov2-vits14/pp-v1', CAST(:vec AS vector) FROM imagenes WHERE video_id = :v LIMIT 1",
        v=video_id,
        vec=vector,
    )
    return str(video_id)


def linea_limpieza(salida: str) -> dict[str, int]:
    [linea] = [linea for linea in salida.splitlines() if linea.startswith("LIMPIEZA ")]
    return json.loads(linea.removeprefix("LIMPIEZA "))


def eventos(salida: str, nombre: str) -> list[dict]:
    resultado = []
    for linea in salida.splitlines():
        if linea.startswith("{"):
            datos = json.loads(linea)
            if datos.get("evento") == nombre:
                resultado.append(datos)
    return resultado


def test_borra_un_video_de_validacion_con_filas_y_objetos(ajustes_s3, s3, capsys):
    borrar = video(ajustes_s3, s3, "validacion-21-a")
    queda = video(ajustes_s3, s3, "validacion-21-b")
    assert cli.main(["limpiar-validacion", "--video", borrar], ajustes=ajustes_s3) == 0
    salida = capsys.readouterr().out
    assert linea_limpieza(salida) == {"videos": 1, "objetos": 4}
    [evento] = eventos(salida, "limpieza_validacion")
    assert (evento["videos"], evento["objetos"], evento["video_ids"], evento["proceso"]) == (1, 4, [borrar], "migrate")
    assert sql(ajustes_s3, "SELECT id::text FROM videos") == [(queda,)]
    assert sql(ajustes_s3, "SELECT count(*) FROM imagenes")[0][0] == 2  # en cascada
    assert sql(ajustes_s3, "SELECT count(*) FROM embeddings")[0][0] == 1
    assert not [c for c in s3.objetos if borrar in c]
    assert len([c for c in s3.objetos if queda in c]) == 4


def test_sin_video_borra_todos_los_de_validacion_y_nada_mas(ajustes_s3, s3, capsys):
    a = video(ajustes_s3, s3, "validacion-21-a")
    b = video(ajustes_s3, s3, "validacion-21-b", fotos=1)
    real = video(ajustes_s3, s3, "Entrada norte", "rec_0001")
    mixto = video(ajustes_s3, s3, "validacion-21-c", "rec_0002")  # el ref_cliente no lleva el prefijo
    assert cli.main(["limpiar-validacion"], ajustes=ajustes_s3) == 0
    salida = capsys.readouterr().out
    assert linea_limpieza(salida) == {"videos": 2, "objetos": 6}
    assert sorted(eventos(salida, "limpieza_validacion")[0]["video_ids"]) == sorted([a, b])
    assert sorted(fila[0] for fila in sql(ajustes_s3, "SELECT id::text FROM videos")) == sorted([real, mixto])
    assert cli.main(["limpiar-validacion"], ajustes=ajustes_s3) == 0
    assert linea_limpieza(capsys.readouterr().out) == {"videos": 0, "objetos": 0}


def test_se_niega_con_un_video_sin_prefijo_o_inexistente_y_no_borra_nada(ajustes_s3, s3, capsys):
    prueba = video(ajustes_s3, s3, "validacion-21-a")
    real = video(ajustes_s3, s3, "Entrada norte", "rec_0001")
    inexistente = str(uuid.uuid4())
    for ids in ([real], [inexistente], [prueba, real], [prueba, inexistente]):
        argumentos = ["limpiar-validacion"] + [parte for i in ids for parte in ("--video", i)]
        assert cli.main(argumentos, ajustes=ajustes_s3) == 1, ids
    salida = capsys.readouterr().out
    rechazos = eventos(salida, "limpieza_rechazada")
    assert len(rechazos) == 4 and rechazos[0]["sin_prefijo"] == [real] and rechazos[1]["inexistentes"] == [inexistente]
    assert "LIMPIEZA" not in salida
    assert len(sql(ajustes_s3, "SELECT id FROM videos")) == 2 and len(s3.objetos) == 8


def test_sin_bucket_es_3_y_un_uuid_mal_formado_es_3(base_migrada, s3, capsys):
    assert cli.main(["limpiar-validacion"], ajustes=base_migrada) == 3
    [evento] = eventos(capsys.readouterr().out, "configuracion_incompleta")
    assert evento["faltan"] == ["S3_BUCKET_DATASET"]
    assert cli.main(["limpiar-validacion", "--video", "no-es-uuid"], ajustes=base_migrada) == 3


def test_si_s3_falla_no_borra_las_filas(ajustes_s3, s3, capsys, monkeypatch):
    from app.clientes.s3 import FalloS3

    prueba = video(ajustes_s3, s3, "validacion-21-a")

    def falla(prefijo: str) -> int:
        raise FalloS3(f"borrar {prefijo}: ClientError: AccessDenied")

    monkeypatch.setattr(s3, "borrar_prefijo", falla)
    assert cli.main(["limpiar-validacion", "--video", prueba], ajustes=ajustes_s3) == 1
    [evento] = eventos(capsys.readouterr().out, "s3_fallido")
    assert evento["operacion"] == "borrar" and "AccessDenied" in evento["motivo"]
    assert sql(ajustes_s3, "SELECT id::text FROM videos") == [(prueba,)]


def test_base_no_disponible_es_2(ajustes_s3, s3, capsys):
    caida = ajustes_s3.model_copy(update={"db_port": 1, "db_connect_timeout_s": 1})
    assert cli.main(["limpiar-validacion"], ajustes=caida) == 2
    assert eventos(capsys.readouterr().out, "base_no_disponible")


def test_simular_comprueba_y_cuenta_sin_borrar(ajustes_s3, s3, capsys):
    prueba = video(ajustes_s3, s3, "validacion-21-a")
    real = video(ajustes_s3, s3, "Entrada norte", "rec_0001")
    assert cli.main(["limpiar-validacion", "--video", prueba, "--simular"], ajustes=ajustes_s3) == 0
    salida = capsys.readouterr().out
    [linea] = [linea for linea in salida.splitlines() if linea.startswith("SIMULACION ")]
    assert json.loads(linea.removeprefix("SIMULACION ")) == {"videos": 1, "objetos": 4}
    assert eventos(salida, "limpieza_simulada")[0]["video_ids"] == [prueba]
    assert "LIMPIEZA" not in salida and not eventos(salida, "limpieza_validacion")
    assert cli.main(["limpiar-validacion", "--video", real, "--simular"], ajustes=ajustes_s3) == 1
    assert eventos(capsys.readouterr().out, "limpieza_rechazada")[0]["sin_prefijo"] == [real]
    assert cli.main(["limpiar-validacion", "--simular"], ajustes=ajustes_s3) == 0
    assert 'SIMULACION {"videos": 1, "objetos": 4}' in capsys.readouterr().out
    assert len(sql(ajustes_s3, "SELECT id FROM videos")) == 2 and len(s3.objetos) == 8  # nada borrado


def test_una_lista_vacia_nunca_es_borrar_todos(ajustes_s3, s3):
    from app.servicios import limpieza

    video(ajustes_s3, s3, "validacion-21-a")

    async def con_lista_vacia():
        motor = sesion.crear_motor(ajustes_s3, "pruebas")
        try:
            return await limpieza.limpiar_validacion(motor, s3, [])
        finally:
            await motor.dispose()

    resultado = asyncio.run(con_lista_vacia())
    assert (resultado.videos, resultado.objetos) == (0, 0)
    assert len(sql(ajustes_s3, "SELECT id FROM videos")) == 1 and len(s3.objetos) == 4


def test_si_falla_la_segunda_pasada_no_falla_el_comando(ajustes_s3, s3, capsys, monkeypatch):
    """Tras borrar las filas, un fallo de S3 solo deja objetos huérfanos: evento `limpieza_s3_incompleta` y código 0."""
    from app.clientes.s3 import FalloS3

    prueba = video(ajustes_s3, s3, "validacion-21-a")
    original = s3.borrar_prefijo
    llamadas = {"n": 0}

    def segunda_pasada_falla(prefijo: str) -> int:
        llamadas["n"] += 1
        if llamadas["n"] > 2:  # 2 prefijos en la primera pasada; la segunda falla
            raise FalloS3(f"borrar {prefijo}: ClientError: SlowDown")
        return original(prefijo)

    monkeypatch.setattr(s3, "borrar_prefijo", segunda_pasada_falla)
    assert cli.main(["limpiar-validacion", "--video", prueba], ajustes=ajustes_s3) == 0
    salida = capsys.readouterr().out
    [evento] = eventos(salida, "limpieza_s3_incompleta")
    assert evento["prefijos"] == [f"dataset/{prueba}/", f"thumbs/{prueba}/"] and "SlowDown" in evento["motivo"]
    assert evento["nivel"] == "WARNING"
    assert linea_limpieza(salida) == {"videos": 1, "objetos": 4}
    assert sql(ajustes_s3, "SELECT count(*) FROM videos")[0][0] == 0
