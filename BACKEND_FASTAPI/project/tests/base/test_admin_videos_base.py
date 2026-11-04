"""BE-4.1 contra PostgreSQL (marca `base`): videos e imágenes del panel, URLs GET, borrado con retiro inmediato de
vectores, purga del `worker` y reconciliador (ARCHITECTURE §4.12, §5.5, §5.7, §5.8). S3 es `almacen_falso` y SQS,
`ColaFalsa` (`tests/conftest.py`)."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.clientes.sqs import Colas, MensajeSqs
from app.config import Settings
from app.db import sesion
from app.dominio.mensajes import cuerpo_purgar_imagen
from app.main import crear_app
from app.servicios import purga

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-be-4-1".ljust(64, b"v")).decode()
VERSION = "dinov2-vits14/pp-v1"


# --- Ayudas --------------------------------------------------------------------------------------------------------
async def _consultar(ajustes: Settings, sentencia: str, parametros: dict) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros)
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def sql(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_consultar(ajustes, sentencia, parametros))


def _vector(i: int) -> str:
    return "[" + ",".join("1" if j == i % 384 else "0" for j in range(384)) + "]"


def video(ajustes: Settings, *estados: str, nombre: str = "validacion-41") -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Un video del admin con una foto por estado (`orden` 1, 2…); las `procesada` con su vector."""
    [(video_id,)] = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por, subida_completa_en) "
        "SELECT :nombre, :ref, id, now() FROM usuarios LIMIT 1 RETURNING id",
        nombre=nombre,
        ref=f"validacion-41-{uuid.uuid4().hex[:8]}",
    )
    ids = []
    for orden, estado in enumerate(estados, start=1):
        imagen_id = uuid.uuid4()
        sql(
            ajustes,
            "INSERT INTO imagenes "
            "(id, video_id, orden, s3_key, lat, lng, capturada_en, bytes_declarados, estado, error) "
            "VALUES (:id, :v, :o, :k, 1.0, -100.0, now(), 1000, CAST(:e AS estado_imagen), :error)",
            id=imagen_id,
            v=video_id,
            o=orden,
            k=f"dataset/{video_id}/{imagen_id}.jpg",
            e=estado,
            error="no es un JPEG decodificable" if estado == "error" else None,
        )
        if estado == "procesada":
            sql(
                ajustes,
                "INSERT INTO embeddings (imagen_id, version_vector, vector) VALUES (:i, :ver, CAST(:vec AS vector))",
                i=imagen_id,
                ver=VERSION,
                vec=_vector(orden),
            )
        ids.append(imagen_id)
    return video_id, ids


def lugar(ajustes: Settings, nombre: str = "validacion-41 lugar") -> uuid.UUID:
    [(lugar_id,)] = sql(
        ajustes,
        "INSERT INTO lugares (nombre, nombre_normalizado, categoria, lat, lng, creado_por) "
        "SELECT :n, :n, 'bloque', 1.0, -100.0, id FROM usuarios LIMIT 1 RETURNING id",
        n=nombre,
    )
    return lugar_id


def auditoria(ajustes: Settings, accion: str, entidad_id: Any) -> list[Any]:
    return sql(
        ajustes,
        "SELECT actor_id, detalle FROM auditoria WHERE accion = :a AND entidad_id = :e ORDER BY id",
        a=accion,
        e=str(entidad_id),
    )


def vectores(ajustes: Settings, video_id: uuid.UUID) -> int:
    return sql(
        ajustes,
        "SELECT count(*) FROM embeddings e JOIN imagenes i ON i.id = e.imagen_id WHERE i.video_id = :v",
        v=video_id,
    )[0][0]


def admin_id(ajustes: Settings) -> uuid.UUID:
    return sql(ajustes, "SELECT id FROM usuarios WHERE correo = :c", c=ADMIN)[0][0]


def purgar(ajustes: Settings, almacen: Any, *cuerpos: str) -> list[bool]:
    async def correr() -> list[bool]:
        motor = sesion.crear_motor(ajustes, "worker", pool=2)
        try:
            mensajes = [MensajeSqs(id=f"p{n}", recibo=f"r{n}", cuerpo=c, recepciones=1) for n, c in enumerate(cuerpos)]
            decisiones = await purga.procesar_purga(purga.DependenciasPurga(motor, almacen), mensajes)
            return [d.borrar for d in decisiones]
        finally:
            await motor.dispose()

    return asyncio.run(correr())


def subir_objetos(almacen: Any, video_id: uuid.UUID, ids: list[uuid.UUID]) -> None:
    for imagen_id in ids:
        almacen.subir(f"dataset/{video_id}/{imagen_id}.jpg")
        almacen.subir(f"thumbs/{video_id}/{imagen_id}.jpg")


@pytest.fixture
def ajustes_41(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def colas(colas_falsas) -> Colas:
    return colas_falsas


@pytest.fixture
def api(ajustes_41, almacen_falso, colas):
    with TestClient(crear_app(ajustes_41, almacen=almacen_falso, colas=colas)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


# --- Videos --------------------------------------------------------------------------------------------------------
def test_detalle_con_urls_get_segun_el_estado(api, ajustes_41, almacen_falso, logs_json):
    video_id, (procesada, pendiente, con_error) = video(ajustes_41, "procesada", "pendiente_subida", "error")
    r = api.get(f"/v1/admin/videos/{video_id}")
    assert r.status_code == 200, r.text
    fotos = {f["id"]: f for f in r.json()["fotos"]}
    assert fotos[str(procesada)]["url"].endswith(f"dataset/{video_id}/{procesada}.jpg?{almacen_falso.FIRMA_FALSA}")
    assert fotos[str(procesada)]["url_miniatura"].endswith(
        f"thumbs/{video_id}/{procesada}.jpg?{almacen_falso.FIRMA_FALSA}"
    )
    assert fotos[str(procesada)]["url_expira_en"].endswith("Z")
    assert (fotos[str(pendiente)]["url"], fotos[str(pendiente)]["url_miniatura"]) == (None, None)
    assert fotos[str(pendiente)]["url_expira_en"] is None
    assert fotos[str(con_error)]["url"] is not None and fotos[str(con_error)]["url_miniatura"] is None
    assert not any(almacen_falso.FIRMA_FALSA in json.dumps(linea) for linea in logs_json.lineas)


def test_detalle_sin_s3_o_con_la_firma_rota_sigue_respondiendo(api, ajustes_41, almacen_falso):
    video_id, _ = video(ajustes_41, "procesada")
    almacen_falso.fallar_firma = True
    r = api.get(f"/v1/admin/videos/{video_id}")
    assert r.status_code == 200 and r.json()["fotos"][0]["url"] is None


def test_renombrar_audita_y_el_mismo_nombre_no_escribe(api, ajustes_41):
    video_id, _ = video(ajustes_41, "procesada")
    r = api.patch(f"/v1/admin/videos/{video_id}", json={"nombre": "  validacion-41 renombrado  ", "otro": 1})
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] == "validacion-41 renombrado"
    assert api.patch(f"/v1/admin/videos/{video_id}", json={"nombre": "validacion-41 renombrado"}).status_code == 200
    [(actor, detalle)] = auditoria(ajustes_41, "video.renombrar", video_id)
    assert actor == admin_id(ajustes_41)
    assert detalle == {"anterior": "validacion-41", "nuevo": "validacion-41 renombrado"}
    assert api.patch(f"/v1/admin/videos/{video_id}", json={"nombre": "   "}).status_code == 422
    assert api.patch(f"/v1/admin/videos/{uuid.uuid4()}", json={"nombre": "x"}).status_code == 404


def test_borrar_retira_vectores_encola_y_repetir_da_lo_mismo(api, ajustes_41, colas, almacen_falso):
    video_id, ids = video(ajustes_41, "procesada", "procesada", "error")
    otro_id, _ = video(ajustes_41, "procesada", nombre="validacion-41 otro")
    assert vectores(ajustes_41, video_id) == 2
    r = api.delete(f"/v1/admin/videos/{video_id}")
    assert r.status_code == 202, r.text
    esperado = {"id": str(video_id), "estado": "eliminado", "fotos_retiradas": 3, "purga": "programada"}
    assert r.json() == esperado
    assert vectores(ajustes_41, video_id) == 0 and vectores(ajustes_41, otro_id) == 1  # C1: fuera de la búsqueda ya
    [(estado, eliminado_por, purgado_en)] = sql(
        ajustes_41, "SELECT estado::text, eliminado_por, purgado_en FROM videos WHERE id = :v", v=video_id
    )
    assert (estado, eliminado_por, purgado_en) == ("eliminado", admin_id(ajustes_41), None)
    [(actor, detalle)] = auditoria(ajustes_41, "video.eliminar", video_id)
    assert actor == admin_id(ajustes_41) and detalle["fotos_retiradas"] == 3 and detalle["vectores"] == 2
    [mensaje] = colas.purga.mensajes()
    assert (mensaje["tipo"], mensaje["video_id"]) == ("purgar_video", str(video_id))
    # Repetir: misma respuesta, sin otra fila ni otro mensaje; el detalle y las listas ya no lo muestran.
    assert api.delete(f"/v1/admin/videos/{video_id}").json() == esperado
    assert len(auditoria(ajustes_41, "video.eliminar", video_id)) == 1 and len(colas.purga.enviados) == 1
    assert api.get(f"/v1/admin/videos/{video_id}").status_code == 404
    assert all(item["id"] != str(video_id) for item in api.get("/v1/admin/videos").json()["items"])
    assert api.get("/v1/admin/images", params={"video_id": str(video_id)}).json()["total"] == 0
    # Purga (C2): objetos y filas fuera, `purgado_en` puesto; el DELETE repetido sigue igual.
    subir_objetos(almacen_falso, video_id, ids)
    almacen_falso.subir(f"dataset/{otro_id}/x.jpg")
    assert purgar(ajustes_41, almacen_falso, colas.purga.enviados[0]) == [True]
    assert [c for c in almacen_falso.objetos if str(video_id) in c] == []
    assert f"dataset/{otro_id}/x.jpg" in almacen_falso.objetos
    assert sql(ajustes_41, "SELECT count(*) FROM imagenes WHERE video_id = :v", v=video_id)[0][0] == 0
    assert sql(ajustes_41, "SELECT purgado_en IS NOT NULL FROM videos WHERE id = :v", v=video_id)[0][0] is True
    assert purgar(ajustes_41, almacen_falso, colas.purga.enviados[0]) == [True]  # repetir no hace daño
    assert api.delete(f"/v1/admin/videos/{video_id}").json() == esperado
    assert api.delete(f"/v1/admin/videos/{uuid.uuid4()}").status_code == 404


def test_sin_sqs_borrar_un_video_responde_202_y_el_reconciliador_lo_reenvia(api, ajustes_41, colas, logs_json):
    video_id, _ = video(ajustes_41, "procesada")
    colas.purga.fallar = True
    r = api.delete(f"/v1/admin/videos/{video_id}")
    assert r.status_code == 202 and r.json()["purga"] == "programada"
    assert any(linea["evento"] == "purga_no_encolada" for linea in logs_json.lineas)
    colas.purga.fallar = False

    # Aún no pasaron 10 min: nada que reenviar. Con `eliminado_en` 11 min atrás, sí (C3).
    async def reenviar() -> purga.Reencolado:
        motor = sesion.crear_motor(ajustes_41, "pruebas")
        try:
            return await purga.reencolar_pendientes(motor, colas.purga, 10)
        finally:
            await motor.dispose()

    assert asyncio.run(reenviar()) == purga.Reencolado(0, 0)
    sql(ajustes_41, "UPDATE videos SET eliminado_en = now() - interval '11 minutes' WHERE id = :v", v=video_id)
    assert asyncio.run(reenviar()) == purga.Reencolado(1, 1)
    assert colas.purga.mensajes()[-1]["video_id"] == str(video_id)


def test_sin_cola_de_purga_borrar_es_500_sin_escribir(ajustes_41, almacen_falso):
    video_id, _ = video(ajustes_41, "procesada")
    with TestClient(crear_app(ajustes_41, almacen=almacen_falso, colas=Colas())) as cliente:
        token = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN}).json()[
            "token"
        ]
        r = cliente.delete(f"/v1/admin/videos/{video_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 500 and r.json()["error"]["codigo"] == "ERROR_INTERNO"
    assert sql(ajustes_41, "SELECT estado::text FROM videos WHERE id = :v", v=video_id)[0][0] != "eliminado"
    assert vectores(ajustes_41, video_id) == 1


def test_purgar_video_no_eliminado_se_descarta(ajustes_41, almacen_falso):
    video_id, ids = video(ajustes_41, "procesada")
    subir_objetos(almacen_falso, video_id, ids)
    cuerpo = json.dumps({"tipo": "purgar_video", "version": 1, "video_id": str(video_id)})
    assert purgar(ajustes_41, almacen_falso, cuerpo) == [True]
    assert len([c for c in almacen_falso.objetos if str(video_id) in c]) == 2


# --- Imágenes ------------------------------------------------------------------------------------------------------
def test_lista_y_detalle_de_imagenes(api, ajustes_41):
    video_id, (a, b) = video(ajustes_41, "procesada", "pendiente_subida")
    borrado, _ = video(ajustes_41, "procesada", nombre="validacion-41 borrado")
    api.delete(f"/v1/admin/videos/{borrado}")
    r = api.get("/v1/admin/images", params={"video_id": str(video_id)})
    assert r.status_code == 200, r.text
    assert [i["id"] for i in r.json()["items"]] == [str(a), str(b)] and r.json()["total"] == 2
    assert (
        api.get("/v1/admin/images", params={"estado": "pendiente_subida", "video_id": str(video_id)}).json()["total"]
        == 1
    )
    assert api.get("/v1/admin/images", params={"q": "borrado"}).json()["total"] == 0  # video eliminado
    assert api.get("/v1/admin/images", params={"por_pagina": 101}).status_code == 422
    detalle = api.get(f"/v1/admin/images/{a}").json()
    assert detalle["video"]["id"] == str(video_id) and detalle["vector"]["version_vector"] == VERSION
    assert api.get(f"/v1/admin/images/{b}").json()["vector"] is None
    assert api.get(f"/v1/admin/images/{uuid.uuid4()}").status_code == 404


def test_editar_imagen(api, ajustes_41):
    _, (imagen,) = video(ajustes_41, "procesada")
    lugar_id = lugar(ajustes_41)
    ruta = f"/v1/admin/images/{imagen}"
    r = api.patch(
        ruta, json={"lat": 1.00005, "lng": -100.0, "lugar_id": str(lugar_id), "calidad": "baja", "notas": " ok "}
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["lat"], cuerpo["calidad"], cuerpo["notas"]) == (1.00005, "baja", "ok")
    assert cuerpo["lugar"] == {"id": str(lugar_id), "nombre": "validacion-41 lugar"}
    [(_, detalle)] = auditoria(ajustes_41, "imagen.editar", imagen)
    assert detalle["cambios"] == ["lat", "lugar_id", "calidad", "notas"]  # lng no cambió
    assert api.patch(ruta, json={"calidad": "baja"}).status_code == 200
    assert len(auditoria(ajustes_41, "imagen.editar", imagen)) == 1
    assert api.patch(ruta, json={"lugar_id": None}).json()["lugar"] is None
    assert api.patch(ruta, json={"lat": 1.0}).json()["error"]["detalle"]["campos"][0]["campo"] == "lng"
    assert api.patch(ruta, json={"calidad": None}).status_code == 422
    sin_lugar = api.patch(ruta, json={"lugar_id": str(uuid.uuid4())})
    assert sin_lugar.status_code == 422 and sin_lugar.json()["error"]["detalle"]["campos"][0]["campo"] == "lugar_id"
    assert api.patch(ruta, json={"notas": "x" * 501}).status_code == 422
    assert sql(ajustes_41, "SELECT count(*) FROM embeddings WHERE imagen_id = :i", i=imagen)[0][0] == 1


def test_borrar_imagen_encola_dentro_de_la_transaccion(api, ajustes_41, colas, almacen_falso):
    video_id, (a, b) = video(ajustes_41, "procesada", "procesada")
    colas.purga.fallar = True
    r = api.delete(f"/v1/admin/images/{a}")
    assert r.status_code == 500  # SQS no aceptó: nada cambia
    assert sql(ajustes_41, "SELECT count(*) FROM imagenes WHERE id = :i", i=a)[0][0] == 1
    assert auditoria(ajustes_41, "imagen.eliminar", a) == []
    colas.purga.fallar = False
    assert api.delete(f"/v1/admin/images/{a}").status_code == 204
    assert api.delete(f"/v1/admin/images/{a}").status_code == 404
    assert sql(ajustes_41, "SELECT count(*) FROM embeddings WHERE imagen_id = :i", i=a)[0][0] == 0
    [mensaje] = colas.purga.mensajes()
    assert mensaje["s3_keys"] == [f"dataset/{video_id}/{a}.jpg", f"thumbs/{video_id}/{a}.jpg"]
    subir_objetos(almacen_falso, video_id, [a, b])
    assert purgar(ajustes_41, almacen_falso, colas.purga.enviados[0]) == [True]
    assert sorted(almacen_falso.objetos) == sorted([f"dataset/{video_id}/{b}.jpg", f"thumbs/{video_id}/{b}.jpg"])
    # Un purgar_imagen de una imagen que sigue existiendo (su DELETE se deshizo) no toca S3.
    assert purgar(ajustes_41, almacen_falso, cuerpo_purgar_imagen(b, video_id, None)) == [True]
    assert len(almacen_falso.objetos) == 2


def test_lote_eliminar_y_reasignar(api, ajustes_41, colas):
    _, (a, b, c) = video(ajustes_41, "procesada", "procesada", "error")
    lugar_id = lugar(ajustes_41)
    inexistente = uuid.uuid4()
    r = api.post("/v1/admin/images/lote", json={"accion": "eliminar", "ids": [str(c), str(inexistente), str(c)]})
    assert r.status_code == 200, r.text
    assert r.json() == {"procesadas": 1, "fallidas": [{"id": str(inexistente), "codigo": "NO_ENCONTRADO"}]}
    assert len(colas.purga.enviados) == 1
    assert api.post("/v1/admin/images/lote", json={"accion": "reasignar", "ids": [str(a)]}).status_code == 422
    sin_lugar = {"accion": "reasignar", "ids": [str(a)], "lugar_id": str(uuid.uuid4())}
    assert api.post("/v1/admin/images/lote", json=sin_lugar).status_code == 422
    r = api.post(
        "/v1/admin/images/lote", json={"accion": "reasignar", "ids": [str(a), str(b)], "lugar_id": str(lugar_id)}
    )
    assert r.json() == {"procesadas": 2, "fallidas": []}
    assert api.get(f"/v1/admin/images/{a}").json()["lugar"]["id"] == str(lugar_id)
    assert api.get("/v1/admin/places").json()["items"][0]["total_fotos"] == 2
    demasiados = {"accion": "eliminar", "ids": [str(uuid.uuid4()) for _ in range(201)]}
    assert api.post("/v1/admin/images/lote", json=demasiados).status_code == 422


def test_reprocesar(api, ajustes_41, colas):
    _, (procesada, pendiente) = video(ajustes_41, "error", "pendiente_subida")
    assert api.post(f"/v1/admin/images/{pendiente}/reprocesar").json()["error"]["codigo"] == "IMAGEN_NO_SUBIDA"
    r = api.post(f"/v1/admin/images/{procesada}/reprocesar")
    assert r.status_code == 202 and r.content == b""
    assert sql(ajustes_41, "SELECT estado::text, error FROM imagenes WHERE id = :i", i=procesada)[0] == ("subida", None)
    [mensaje] = colas.ingesta.mensajes()
    assert (mensaje["tipo"], mensaje["version"], mensaje["imagen_id"]) == ("reprocesar_imagen", 1, str(procesada))
    [(_, detalle)] = auditoria(ajustes_41, "imagen.reprocesar", procesada)
    assert detalle["estado_anterior"] == "error"
    assert api.post(f"/v1/admin/images/{uuid.uuid4()}/reprocesar").status_code == 404
