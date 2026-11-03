"""BE-2.1 contra una base real y S3 simulado: recolección y lectura de videos (ARCHITECTURE §4.5, §5.4, §5.5)."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app import cli
from app.config import Settings
from app.db import sesion
from app.esquemas.comun import Pagina
from app.esquemas.videos import ImagenesRegistradas, SubidaCompletada, VideoDetalle, VideoResumen
from app.main import crear_app

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-recoleccion".ljust(64, b"z")).decode()


async def _consultar(ajustes: Settings, sentencia: str, parametros: dict | None = None) -> list[Any]:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            resultado = await conexion.execute(text(sentencia), parametros or {})
            return list(resultado.all()) if resultado.returns_rows else []
    finally:
        await motor.dispose()


def consultar(ajustes: Settings, sentencia: str, **parametros: Any) -> list[Any]:
    return asyncio.run(_consultar(ajustes, sentencia, parametros))


@pytest.fixture
def ajustes_rec(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def api(ajustes_rec, almacen_falso):
    with TestClient(crear_app(ajustes_rec, almacen=almacen_falso)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


def cuerpo_video(ref: str = "rec_0003", **cambios: Any) -> dict[str, Any]:
    return {
        "ref_cliente": ref,
        "nombre": "video_3",
        "iniciado_en": "2026-10-20T14:00:00Z",
        "finalizado_en": "2026-10-20T14:08:32Z",
        "duracion_s": 512,
        "distancia_m": 340.3,
        "pasos": 470,
        "inicio": {"lat": 6.2001, "lng": -75.5786, "rumbo": 90.0},
        "total_fotos": 120,
        "dispositivo": "Xiaomi 23028RA60L / Android 14",
        "app_version": "0.9.0",
    } | cambios


def elemento(orden: int, **cambios: Any) -> dict[str, Any]:
    return {
        "orden": orden,
        "lat": 6.2001,
        "lng": -75.5786,
        "rumbo": 90.0,
        "capturada_en": "2026-10-20T14:00:05.250Z",
        "bytes": 345678,
    } | cambios


def crear(api: TestClient, **cambios: Any) -> dict[str, Any]:
    r = api.post("/v1/collect/videos", json=cuerpo_video(**cambios))
    assert r.status_code == 201, r.text
    return r.json()


def registrar(api: TestClient, video_id: str, *ordenes: int, estado: int = 200, **cambios: Any):
    r = api.post(f"/v1/collect/videos/{video_id}/images", json={"imagenes": [elemento(o, **cambios) for o in ordenes]})
    assert r.status_code == estado, r.text
    return r.json()


def _error(r) -> str:
    return r.json()["error"]["codigo"]


# --- POST /v1/collect/videos -------------------------------------------------------------------------------------
def test_crear_video_201_y_repetir_200_con_el_mismo(api, logs_json):
    video = crear(api)
    VideoResumen.model_validate(video)
    assert video["estado"] == "pendiente" and video["nombre"] == "video_3" and video["numero"] >= 1
    assert video["ref_cliente"] == "rec_0003"
    assert video["distancia_m"] == 340.3  # `real` leído con su valor legible, no 340.29998779296875
    assert video["inicio"] == {"lat": 6.2001, "lng": -75.5786, "rumbo": 90.0}
    assert video["total_fotos"] == 120
    assert video["conteo"] == {"pendiente_subida": 0, "subida": 0, "procesada": 0, "error": 0}
    assert video["creado_por"]["nombre"] == "Administrador"
    assert video["creado_en"].endswith("Z") and "." not in video["creado_en"]
    assert video["iniciado_en"] == "2026-10-20T14:00:00Z"
    otra = api.post("/v1/collect/videos", json=cuerpo_video(nombre="otro nombre", total_fotos=3))
    assert otra.status_code == 200
    assert otra.json() == video  # el primero gana: no se actualiza
    eventos = [linea for linea in logs_json.lineas if linea["evento"] == "video_creado"]
    assert [e["nuevo"] for e in eventos] == [True, False]


def test_nombre_vacio_o_ausente_es_video_numero(api):
    sin_nombre = crear(api, ref="rec_a", nombre=None)
    en_blanco = crear(api, ref="rec_b", nombre="   ")
    assert sin_nombre["nombre"] == f"video_{sin_nombre['numero']}"
    assert en_blanco["nombre"] == f"video_{en_blanco['numero']}"
    assert en_blanco["numero"] == sin_nombre["numero"] + 1


def test_solo_ref_cliente_es_obligatorio(api):
    r = api.post("/v1/collect/videos", json={"ref_cliente": "  rec_min  "})
    assert r.status_code == 201, r.text
    video = r.json()
    assert video["inicio"] is None and video["total_fotos"] == 0 and video["duracion_s"] is None
    [(ref,)] = consultar(api.app.state.ajustes, "SELECT ref_cliente FROM videos")
    assert ref == "rec_min"  # recortado
    assert api.post("/v1/collect/videos", json={"ref_cliente": "rec_min"}).status_code == 200


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"ref_cliente": ""}, "ref_cliente"),
        ({"ref_cliente": "x" * 41}, "ref_cliente"),
        ({"nombre": "n" * 41}, "nombre"),
        ({"nombre": "a\u0000b"}, "nombre"),
        ({"total_fotos": 201}, "total_fotos"),
        ({"duracion_s": -1}, "duracion_s"),
        ({"inicio": {"lat": 91, "lng": 0}}, "inicio.lat"),
        ({"inicio": {"lat": 0, "lng": 0, "rumbo": 360}}, "inicio.rumbo"),
        ({"inicio": {"lat": 0, "lng": 0, "rumbo": 359.99999999}}, "inicio.rumbo"),
        ({"iniciado_en": "2026-10-20T14:00:00"}, "iniciado_en"),
        ({"dispositivo": "d" * 201}, "dispositivo"),
    ],
)
def test_crear_video_con_campos_no_validos_es_422(api, cambios, campo):
    r = api.post("/v1/collect/videos", json=cuerpo_video(**cambios))
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert campo in [c["campo"] for c in r.json()["error"]["detalle"]["campos"]]


def test_fin_anterior_al_inicio_es_422(api):
    r = api.post("/v1/collect/videos", json=cuerpo_video(finalizado_en="2026-10-20T13:00:00Z"))
    assert (r.status_code, _error(r)) == (422, "VALIDACION")


def test_otro_admin_con_el_mismo_ref_cliente_crea_otro_video(api, ajustes_rec, monkeypatch):
    primero = crear(api)
    monkeypatch.setenv(cli.VARIABLE_PASSWORD, "Otro-admin-12345")
    assert cli.main(["crear-usuario", "--correo", "otro@campus.edu.co", "--nombre", "Otra", "--rol", "admin"],
                    ajustes=ajustes_rec) == 0  # fmt: skip
    r = api.post("/v1/auth/login", json={"identificador": "otro@campus.edu.co", "password": "Otro-admin-12345"})
    segundo = api.post(
        "/v1/collect/videos", json=cuerpo_video(), headers={"Authorization": f"Bearer {r.json()['token']}"}
    )
    assert segundo.status_code == 201
    assert segundo.json()["id"] != primero["id"] and segundo.json()["creado_por"]["nombre"] == "Otra"


def test_ref_cliente_de_un_video_eliminado_es_409(api):
    video = crear(api)
    eliminar(api.app.state.ajustes, video["id"])
    r = api.post("/v1/collect/videos", json=cuerpo_video())
    assert (r.status_code, _error(r)) == (409, "VIDEO_ELIMINADO")


def eliminar(ajustes: Settings, video_id: str) -> None:
    """Simula el borrado lógico de BE-4.1 (§5.7: estado, eliminado_en y eliminado_por juntos)."""
    consultar(
        ajustes,
        "UPDATE videos SET estado = 'eliminado', eliminado_en = now(), eliminado_por = creado_por WHERE id = :id",
        id=uuid.UUID(video_id),
    )


# --- POST /v1/collect/videos/{id}/images ---------------------------------------------------------------------------
def test_registrar_devuelve_urls_put_y_guarda_la_clave_de_infra(api, almacen_falso, logs_json):
    video = crear(api)
    cuerpo = registrar(api, video["id"], 2, 1, 3)
    ImagenesRegistradas.model_validate(cuerpo)
    assert [i["orden"] for i in cuerpo["imagenes"]] == [2, 1, 3]  # el orden de la petición
    for imagen in cuerpo["imagenes"]:
        assert imagen["estado"] == "pendiente_subida"
        subida = imagen["subida"]
        assert subida["metodo"] == "PUT" and subida["encabezados"] == {"Content-Type": "image/jpeg"}
        assert subida["url"].startswith(f"https://{almacen_falso.bucket}.s3.amazonaws.com/dataset/{video['id']}/")
        assert subida["expira_en"].endswith("Z")
        vence = datetime.fromisoformat(subida["expira_en"].replace("Z", "+00:00"))
        assert 890 <= (vence - datetime.now(UTC)).total_seconds() <= 900  # PRESIGN_PUT_TTL_S
    filas = consultar(api.app.state.ajustes, "SELECT id::text, s3_key, bytes_declarados, rumbo FROM imagenes")
    assert {clave for _, clave, _, _ in filas} == {f"dataset/{video['id']}/{i}.jpg" for i, _, _, _ in filas}
    assert all(b == 345678 and r == 90.0 for _, _, b, r in filas)
    texto = str(logs_json.lineas)
    assert almacen_falso.FIRMA_FALSA not in texto and "s3.amazonaws.com" not in texto
    [evento] = [e for e in logs_json.lineas if e["evento"] == "imagenes_registradas"]
    assert (evento["nuevas"], evento["urls"]) == (3, 3)


def test_repetir_actualiza_las_pendientes_y_las_subidas_no_reciben_url(api, almacen_falso):
    video = crear(api)
    primera = {i["orden"]: i for i in registrar(api, video["id"], 1, 2, 3)["imagenes"]}
    almacen_falso.subir(f"dataset/{video['id']}/{primera[1]['id']}.jpg", n_bytes=345000)
    segunda = {i["orden"]: i for i in registrar(api, video["id"], 1, 2, 3, lat=6.3)["imagenes"]}
    assert {o: i["id"] for o, i in segunda.items()} == {o: i["id"] for o, i in primera.items()}
    assert segunda[1]["estado"] == "subida" and segunda[1]["subida"] is None
    assert segunda[2]["estado"] == "pendiente_subida" and segunda[2]["subida"] is not None
    filas = dict(
        (o, (e, lat, b, etag))
        for o, e, lat, b, etag in consultar(
            api.app.state.ajustes, "SELECT orden, estado::text, lat, bytes, etag FROM imagenes ORDER BY orden"
        )
    )
    assert filas[1] == ("subida", 6.2001, 345000, "etag0")  # la subida no cambia sus metadatos
    assert filas[2][:2] == ("pendiente_subida", 6.3) and filas[2][2] is None
    # Las nuevas no se consultan en S3 (su clave es nueva); las repetidas pendientes, sí.
    assert len(almacen_falso.consultadas) == 3
    assert consultar(api.app.state.ajustes, "SELECT count(*) FROM imagenes")[0][0] == 3


def test_limites_de_5_10_son_422(api, ajustes_rec):
    video = crear(api)
    demasiadas = {"imagenes": [elemento(o) for o in range(1, 52)]}
    r = api.post(f"/v1/collect/videos/{video['id']}/images", json=demasiadas)
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert r.json()["error"]["detalle"]["campos"][0]["campo"] == "imagenes"
    for cambios, campo in (({"orden": 201}, "imagenes.0.orden"), ({"bytes": 4_194_305}, "imagenes.0.bytes")):
        r = api.post(f"/v1/collect/videos/{video['id']}/images", json={"imagenes": [elemento(1) | cambios]})
        assert (r.status_code, _error(r)) == (422, "VALIDACION")
        assert [c["campo"] for c in r.json()["error"]["detalle"]["campos"]] == [campo]
    r = api.post(f"/v1/collect/videos/{video['id']}/images", json={"imagenes": [elemento(1), elemento(1)]})
    assert r.json()["error"]["detalle"]["campos"] == [
        {"campo": "imagenes.1.orden", "motivo": "Repetido en la misma petición."}
    ]
    assert consultar(ajustes_rec, "SELECT count(*) FROM imagenes")[0][0] == 0


def test_registrar_en_un_video_inexistente_404_y_eliminado_409(api):
    r = api.post(f"/v1/collect/videos/{uuid.uuid4()}/images", json={"imagenes": [elemento(1)]})
    assert (r.status_code, _error(r)) == (404, "NO_ENCONTRADO")
    r = api.post("/v1/collect/videos/no-es-uuid/images", json={"imagenes": [elemento(1)]})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    video = crear(api)
    eliminar(api.app.state.ajustes, video["id"])
    r = api.post(f"/v1/collect/videos/{video['id']}/images", json={"imagenes": [elemento(1)]})
    assert (r.status_code, _error(r)) == (409, "VIDEO_ELIMINADO")
    r = api.post(f"/v1/collect/videos/{video['id']}/complete")
    assert (r.status_code, _error(r)) == (409, "VIDEO_ELIMINADO")


def test_sin_bucket_404_si_el_video_no_existe_y_500_si_existe(ajustes_rec, logs_json):
    """`S3_BUCKET_DATASET` se exige después de comprobar el video (§5.4): un video inexistente da 404 igual."""
    with TestClient(crear_app(ajustes_rec)) as cliente:  # sin almacén: los Settings de prueba no traen bucket
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        for ruta in ("images", "complete"):
            cuerpo = {"imagenes": [elemento(1)]} if ruta == "images" else None
            r = cliente.post(f"/v1/collect/videos/{uuid.uuid4()}/{ruta}", json=cuerpo)
            assert (r.status_code, _error(r)) == (404, "NO_ENCONTRADO"), ruta
        video = crear(cliente)
        r = cliente.post(f"/v1/collect/videos/{video['id']}/images", json={"imagenes": [elemento(1)]})
        assert (r.status_code, _error(r)) == (500, "ERROR_INTERNO")
        r = cliente.post(f"/v1/collect/videos/{video['id']}/complete")
        assert (r.status_code, _error(r)) == (500, "ERROR_INTERNO")
    eventos = [e for e in logs_json.lineas if e["evento"] == "configuracion_incompleta"]
    assert len(eventos) == 2 and eventos[0]["faltan"] == ["S3_BUCKET_DATASET"]
    assert consultar(ajustes_rec, "SELECT count(*) FROM imagenes")[0][0] == 0  # no registró nada


def test_bloquear_video_devuelve_el_estado_y_bloquea_la_fila(api, ajustes_rec):
    """La ayuda que usará el worker (BE-2.2): orden video → imágenes."""
    from app.servicios import recoleccion

    video = crear(api)

    async def probar() -> tuple:
        motor = sesion.crear_motor(ajustes_rec, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                estado = await recoleccion.bloquear_video(conexion, uuid.UUID(video["id"]))
                otra = await conexion.execute(
                    text("SELECT count(*) FROM pg_locks WHERE locktype = 'transactionid' AND granted")
                )
                ninguno = await recoleccion.bloquear_video(conexion, uuid.uuid4())
                return estado, otra.scalar_one(), ninguno
        finally:
            await motor.dispose()

    estado, bloqueos, ninguno = asyncio.run(probar())
    assert str(estado) == "pendiente" and bloqueos >= 1 and ninguno is None


def test_si_falla_la_firma_500_sin_url_y_repetir_funciona(api, almacen_falso, logs_json):
    video = crear(api)
    almacen_falso.fallar_firma = True
    r = api.post(f"/v1/collect/videos/{video['id']}/images", json={"imagenes": [elemento(1)]})
    assert (r.status_code, _error(r)) == (500, "ERROR_INTERNO")
    [evento] = [e for e in logs_json.lineas if e["evento"] == "s3_fallido"]
    assert evento["operacion"] == "firmar" and "NoCredentialsError" in evento["motivo"]
    almacen_falso.fallar_firma = False
    [imagen] = registrar(api, video["id"], 1)["imagenes"]
    assert imagen["subida"] is not None


# --- POST /v1/collect/videos/{id}/complete -------------------------------------------------------------------------
def test_complete_hace_head_y_pasa_a_subida_sin_worker(api, almacen_falso, logs_json):
    video = crear(api)
    fotos = {i["orden"]: i["id"] for i in registrar(api, video["id"], 1, 2, 3, 4)["imagenes"]}
    for orden in (1, 2, 3):
        almacen_falso.subir(f"dataset/{video['id']}/{fotos[orden]}.jpg")
    r = api.post(f"/v1/collect/videos/{video['id']}/complete")
    assert r.status_code == 200, r.text
    SubidaCompletada.model_validate(r.json())
    assert r.json() == {
        "id": video["id"],
        "estado": "pendiente",  # queda una foto sin subir
        "conteo": {"pendiente_subida": 1, "subida": 3, "procesada": 0, "error": 0},
    }
    almacen_falso.subir(f"dataset/{video['id']}/{fotos[4]}.jpg")
    almacen_falso.consultadas.clear()
    segunda = api.post(f"/v1/collect/videos/{video['id']}/complete").json()
    assert segunda["estado"] == "procesando"
    assert segunda["conteo"] == {"pendiente_subida": 0, "subida": 4, "procesada": 0, "error": 0}
    assert len(almacen_falso.consultadas) == 1  # solo la que seguía pendiente
    tercera = api.post(f"/v1/collect/videos/{video['id']}/complete").json()
    assert tercera == segunda and almacen_falso.consultadas == [f"dataset/{video['id']}/{fotos[4]}.jpg"]
    [(completa,)] = consultar(api.app.state.ajustes, "SELECT subida_completa_en FROM videos")
    assert completa is not None
    eventos = [e for e in logs_json.lineas if e["evento"] == "subida_completada"]
    assert [(e["comprobadas"], e["encontradas"]) for e in eventos] == [(4, 3), (1, 1), (0, 0)]


def test_complete_con_un_head_que_falla_deja_la_foto_pendiente(api, almacen_falso, logs_json):
    video = crear(api)
    [foto] = registrar(api, video["id"], 1)["imagenes"]
    clave = f"dataset/{video['id']}/{foto['id']}.jpg"
    almacen_falso.subir(clave)
    almacen_falso.fallar_head.add(clave)
    r = api.post(f"/v1/collect/videos/{video['id']}/complete")
    assert r.status_code == 200 and r.json()["conteo"]["pendiente_subida"] == 1
    [evento] = [e for e in logs_json.lineas if e["evento"] == "s3_fallido"]
    assert (evento["operacion"], evento["claves"], evento["nivel"]) == ("head", 1, "WARNING")


def test_estados_del_video_segun_los_conteos(api, ajustes_rec, almacen_falso):
    """§5.5: `procesado` con todas procesadas y `con_errores` sin `subida` y con alguna en error (lo hará BE-2.2)."""
    video = crear(api)
    fotos = [i["id"] for i in registrar(api, video["id"], 1, 2)["imagenes"]]
    for imagen_id in fotos:
        almacen_falso.subir(f"dataset/{video['id']}/{imagen_id}.jpg")
    assert api.post(f"/v1/collect/videos/{video['id']}/complete").json()["estado"] == "procesando"
    consultar(ajustes_rec, "UPDATE imagenes SET estado = 'procesada'")
    assert api.post(f"/v1/collect/videos/{video['id']}/complete").json()["estado"] == "procesado"
    consultar(ajustes_rec, "UPDATE imagenes SET estado = 'error', error = 'corrupta' WHERE id = :id",
              id=uuid.UUID(fotos[0]))  # fmt: skip
    assert api.post(f"/v1/collect/videos/{video['id']}/complete").json()["estado"] == "con_errores"
    # Una foto nueva tras `complete` lo devuelve a `pendiente`.
    registrar(api, video["id"], 3)
    assert api.get(f"/v1/admin/videos/{video['id']}").json()["estado"] == "pendiente"


def test_complete_de_un_video_sin_fotos_es_procesado(api):
    video = crear(api, ref="rec_vacio", total_fotos=0)
    r = api.post(f"/v1/collect/videos/{video['id']}/complete")
    assert r.json()["estado"] == "procesado"
    assert api.post(f"/v1/collect/videos/{uuid.uuid4()}/complete").status_code == 404


# --- GET /v1/admin/videos y /v1/admin/videos/{id} --------------------------------------------------------------------
def test_detalle_con_las_fotos_en_orden_y_el_mismo_conteo(api, ajustes_rec, almacen_falso):
    video = crear(api)
    fotos = {i["orden"]: i["id"] for i in registrar(api, video["id"], 3, 1, 2, rumbo=182.3)["imagenes"]}
    almacen_falso.subir(f"dataset/{video['id']}/{fotos[2]}.jpg")
    completado = api.post(f"/v1/collect/videos/{video['id']}/complete").json()
    consultar(
        ajustes_rec,
        "INSERT INTO lugares (nombre, nombre_normalizado, categoria, lat, lng, creado_por) "
        "SELECT 'Biblioteca Central', 'biblioteca central', 'biblioteca', 6.2, -75.57, id FROM usuarios",
    )
    consultar(ajustes_rec, "UPDATE imagenes SET lugar_id = (SELECT id FROM lugares), notas = 'n' WHERE orden = 1")
    r = api.get(f"/v1/admin/videos/{video['id']}")
    assert r.status_code == 200
    detalle = r.json()
    VideoDetalle.model_validate(detalle)
    assert [f["orden"] for f in detalle["fotos"]] == [1, 2, 3]
    assert detalle["conteo"] == completado["conteo"]
    primera = detalle["fotos"][0]
    assert primera["lugar"]["nombre"] == "Biblioteca Central" and primera["notas"] == "n"
    assert primera["rumbo"] == 182.3 and primera["capturada_en"] == "2026-10-20T14:00:05Z"
    assert primera["calidad"] == "normal" and primera["error"] is None
    assert (primera["url"], primera["url_miniatura"], primera["url_expira_en"]) == (None, None, None)  # hasta BE-4.1
    assert detalle["fotos"][1]["estado"] == "subida" and detalle["fotos"][1]["lugar"] is None


def test_detalle_de_inexistente_o_eliminado_es_404(api):
    assert api.get(f"/v1/admin/videos/{uuid.uuid4()}").status_code == 404
    video = crear(api)
    eliminar(api.app.state.ajustes, video["id"])
    r = api.get(f"/v1/admin/videos/{video['id']}")
    assert (r.status_code, _error(r)) == (404, "NO_ENCONTRADO")


def test_listado_con_q_orden_paginacion_y_sin_eliminados(api, ajustes_rec, almacen_falso):
    a = crear(api, ref="r1", nombre="Entrada norte")
    b = crear(api, ref="r2", nombre="validacion-21-x")
    c = crear(api, ref="r3", nombre="Bloque 50%_raro")
    registrar(api, b["id"], 1, 2)
    registrar(api, c["id"], 1)
    eliminado = crear(api, ref="r4", nombre="Entrada sur")
    eliminar(ajustes_rec, eliminado["id"])

    todos = api.get("/v1/admin/videos").json()
    Pagina[VideoResumen].model_validate(todos)
    assert (todos["total"], todos["pagina"], todos["por_pagina"]) == (3, 1, 24)
    assert [v["id"] for v in todos["items"]] == [c["id"], b["id"], a["id"]]  # fecha desc por defecto

    def ids(**params: Any) -> list[str]:
        r = api.get("/v1/admin/videos", params=params)
        assert r.status_code == 200, r.text
        return [v["id"] for v in r.json()["items"]]

    assert ids(q="ENTRADA") == [a["id"]]  # sin distinguir mayúsculas; el eliminado no sale
    assert ids(q="validacion-") == [b["id"]]
    assert ids(q="50%_") == [c["id"]] and ids(q="%") == [c["id"]]  # % y _ son literales
    assert ids(orden="nombre", dir="asc") == [c["id"], a["id"], b["id"]]
    assert ids(orden="fotos") == [b["id"], c["id"], a["id"]]
    assert ids(por_pagina=2, pagina=2) == [a["id"]]
    conteo_b = next(v for v in todos["items"] if v["id"] == b["id"])["conteo"]
    assert conteo_b == {"pendiente_subida": 2, "subida": 0, "procesada": 0, "error": 0}


@pytest.mark.parametrize(
    ("params", "campo"),
    [({"por_pagina": 101}, "por_pagina"), ({"pagina": 0}, "pagina"), ({"orden": "x"}, "orden"), ({"dir": "x"}, "dir")],
)
def test_parametros_del_listado_no_validos_son_422(api, params, campo):
    r = api.get("/v1/admin/videos", params=params)
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
    assert [c["campo"] for c in r.json()["error"]["detalle"]["campos"]] == [campo]


def test_q_con_nul_es_422(api):
    r = api.get("/v1/admin/videos", params={"q": "a\u0000"})
    assert (r.status_code, _error(r)) == (422, "VALIDACION")
