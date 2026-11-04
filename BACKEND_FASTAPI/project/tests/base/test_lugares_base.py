"""BE-3.1 contra una base real: `GET /v1/places` y el CRUD de `/v1/admin/places` (ARCHITECTURE §4.9, §5.3, §5.5)."""

from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import sesion
from app.db.modelos import Lugar
from app.dominio.enumerados import CategoriaLugar
from app.esquemas.lugares import ListaLugares, LugarAdmin, LugarPublico
from app.main import crear_app
from app.servicios import lugares

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-de-lugares".ljust(64, b"z")).decode()


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


@pytest.fixture
def ajustes_lug(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def api(ajustes_lug):
    with TestClient(crear_app(ajustes_lug)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


def entrada(nombre: str = "Biblioteca Central", **cambios: Any) -> dict[str, Any]:
    return {
        "nombre": nombre,
        "categoria": "biblioteca",
        "lat": 6.2009,
        "lng": -75.5783,
        "alias": ["biblioteca", "la biblioteca"],
        "descripcion": "Edificio de tres pisos",
        "referencias": "Frente al lago",
    } | cambios


def crear(api: TestClient, nombre: str = "Biblioteca Central", **cambios: Any) -> dict[str, Any]:
    r = api.post("/v1/admin/places", json=entrada(nombre, **cambios))
    assert r.status_code == 201, r.text
    return r.json()


def foto_con_lugar(ajustes: Settings, lugar_id: str, *, eliminado: bool = False) -> uuid.UUID:
    """Un video (eliminado o no) con una foto asignada a `lugar_id` (lo que hará BE-4.1 con `PATCH`)."""
    estado = "'eliminado', now(), id" if eliminado else "'pendiente', NULL, NULL"
    video_id = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por, estado, eliminado_en, eliminado_por) "  # noqa: S608
        f"SELECT 'validacion-31', :ref, id, {estado} FROM usuarios LIMIT 1 RETURNING id",
        ref=f"validacion-31-{uuid.uuid4().hex[:8]}",
    )[0][0]
    imagen_id = uuid.uuid4()
    sql(
        ajustes,
        "INSERT INTO imagenes (id, video_id, orden, s3_key, lat, lng, capturada_en, bytes_declarados, lugar_id) "
        "VALUES (:id, :v, 1, :k, 1.0, -100.0, now(), 1000, :l)",
        id=imagen_id,
        v=video_id,
        k=f"dataset/{video_id}/{imagen_id}.jpg",
        l=uuid.UUID(lugar_id),
    )
    return imagen_id


def auditoria(ajustes: Settings, accion: str) -> list[Any]:
    return sql(
        ajustes,
        "SELECT actor_id, entidad, entidad_id, detalle FROM auditoria WHERE accion = :a ORDER BY id",
        a=accion,
    )


# --- Crear ---------------------------------------------------------------------------------------------------------
def test_crear_devuelve_lugar_admin_y_anota_auditoria(api, ajustes_lug, logs_json):
    cuerpo = crear(api, "  Biblioteca Central  ", alias=[" biblio "], descripcion="  ", extra="ignorado")
    LugarAdmin.model_validate(cuerpo)
    assert set(cuerpo) == set(LugarAdmin.model_fields)
    assert cuerpo["nombre"] == "Biblioteca Central"
    assert cuerpo["alias"] == ["biblio"]
    assert cuerpo["descripcion"] is None and cuerpo["referencias"] == "Frente al lago"
    assert cuerpo["imagen_url"] is None and cuerpo["total_fotos"] == 0
    assert cuerpo["creado_en"] == cuerpo["actualizado_en"] and cuerpo["creado_en"].endswith("Z")
    [(normalizado, creado_por)] = sql(
        ajustes_lug, "SELECT nombre_normalizado, creado_por FROM lugares WHERE id = :i", i=uuid.UUID(cuerpo["id"])
    )
    assert normalizado == "biblioteca central"
    [(actor, entidad, entidad_id, detalle)] = auditoria(ajustes_lug, "lugar.crear")
    assert actor == creado_por and entidad == "lugar" and entidad_id == cuerpo["id"]
    assert detalle == {"nombre": "Biblioteca Central", "categoria": "biblioteca"}
    [evento] = [linea for linea in logs_json.lineas if linea["evento"] == "lugar_guardado"]
    assert evento["operacion"] == "crear" and evento["lugar_id"] == cuerpo["id"]
    assert "Biblioteca" not in str(evento)


@pytest.mark.parametrize("repetido", ["BIBLIOTECA CENTRAL", "Bibliotéca Céntral", "  biblioteca   central "])
def test_nombre_repetido_al_crear_es_409_sin_escribir(api, ajustes_lug, repetido):
    crear(api)
    r = api.post("/v1/admin/places", json=entrada(repetido, categoria="bloque"))
    assert r.status_code == 409, r.text
    assert r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"
    assert sql(ajustes_lug, "SELECT count(*) FROM lugares")[0][0] == 1
    assert len(auditoria(ajustes_lug, "lugar.crear")) == 1


def test_crear_con_campos_no_validos_es_422(api):
    r = api.post("/v1/admin/places", json=entrada("a", lat=91, alias=["x"] * 21, categoria="cocina"))
    assert r.status_code == 422
    campos = {c["campo"] for c in r.json()["error"]["detalle"]["campos"]}
    assert campos == {"nombre", "lat", "alias", "categoria"}


def test_admin_places_exige_token(ajustes_lug):
    with TestClient(crear_app(ajustes_lug)) as cliente:
        assert cliente.get("/v1/admin/places").status_code == 401
        r = cliente.post("/v1/admin/places", json={"nombre": "a"})  # sin token: 401 antes que 422
        assert r.status_code == 401 and r.json()["error"]["codigo"] == "NO_AUTENTICADO"
        assert cliente.delete(f"/v1/admin/places/{uuid.uuid4()}").status_code == 401


# --- Reemplazar ----------------------------------------------------------------------------------------------------
def test_reemplazar_cambia_todo_y_anota_los_cambios(api, ajustes_lug):
    lugar = crear(api)
    nuevo = {"nombre": "Biblióteca central", "categoria": "bloque", "lat": 6.21, "lng": -75.58}  # mismo nombre
    r = api.put(f"/v1/admin/places/{lugar['id']}", json=nuevo)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["nombre"] == "Biblióteca central" and cuerpo["categoria"] == "bloque"
    assert (cuerpo["lat"], cuerpo["lng"]) == (6.21, -75.58)
    assert cuerpo["alias"] == [] and cuerpo["descripcion"] is None and cuerpo["referencias"] is None
    assert cuerpo["creado_en"] == lugar["creado_en"] and cuerpo["actualizado_en"] >= lugar["actualizado_en"]
    [(_, _, entidad_id, detalle)] = auditoria(ajustes_lug, "lugar.editar")
    assert entidad_id == lugar["id"]
    assert detalle == {"cambios": ["nombre", "categoria", "lat", "lng", "alias", "descripcion", "referencias"]}
    publico = api.get("/v1/places").json()["items"]
    assert [(p["nombre"], p["categoria"]) for p in publico] == [("Biblióteca central", "bloque")]


def test_reemplazar_sin_cambios_no_escribe(api, ajustes_lug):
    lugar = crear(api)
    sql(ajustes_lug, "UPDATE lugares SET actualizado_en = '2026-01-01T00:00:00Z'")
    r = api.put(f"/v1/admin/places/{lugar['id']}", json=entrada())
    assert r.status_code == 200
    assert r.json()["actualizado_en"] == "2026-01-01T00:00:00Z"
    assert auditoria(ajustes_lug, "lugar.editar") == []


def test_reemplazar_con_el_nombre_de_otro_es_409(api, ajustes_lug):
    crear(api, "Cafe Norte")
    otro = crear(api, "Bloque 19")
    r = api.put(f"/v1/admin/places/{otro['id']}", json=entrada("CAFÉ NORTE"))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"
    assert sql(ajustes_lug, "SELECT nombre FROM lugares WHERE id = :i", i=uuid.UUID(otro["id"]))[0][0] == "Bloque 19"


def test_reemplazar_un_lugar_que_no_existe_es_404_y_un_id_raro_422(api):
    r = api.put(f"/v1/admin/places/{uuid.uuid4()}", json=entrada())
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "NO_ENCONTRADO"
    assert api.put("/v1/admin/places/no-es-uuid", json=entrada()).status_code == 422


def test_la_restriccion_unica_se_reconoce_como_nombre_duplicado(api, ajustes_lug):
    """La carrera entre dos `PUT` (la comprobación previa no ve al otro) acaba en la restricción única."""
    a, b = crear(api, "Uno"), crear(api, "Dos")

    async def chocar() -> IntegrityError:
        motor = sesion.crear_motor(ajustes_lug, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                await conexion.execute(
                    update(Lugar).where(Lugar.id == uuid.UUID(b["id"])).values(nombre_normalizado="uno")
                )
        except IntegrityError as exc:
            return exc
        finally:
            await motor.dispose()
        raise AssertionError("no chocó")

    assert lugares._es_nombre_duplicado(asyncio.run(chocar()))
    assert a["id"] != b["id"]


# --- Borrar --------------------------------------------------------------------------------------------------------
def test_borrar_deja_las_fotos_sin_lugar_y_repetir_da_204(api, ajustes_lug, logs_json):
    lugar = crear(api)
    imagen = foto_con_lugar(ajustes_lug, lugar["id"])
    otra = foto_con_lugar(ajustes_lug, lugar["id"], eliminado=True)
    [admin] = api.get("/v1/admin/places").json()["items"]
    assert admin["total_fotos"] == 1  # la del video eliminado no cuenta
    sql(ajustes_lug, "UPDATE imagenes SET actualizado_en = '2026-01-01T00:00:00Z'")

    r = api.delete(f"/v1/admin/places/{lugar['id']}")
    assert r.status_code == 204 and r.content == b""
    filas = sql(
        ajustes_lug,
        "SELECT lugar_id, actualizado_en FROM imagenes WHERE id IN (:a, :b)",
        a=imagen,
        b=otra,
    )
    assert [f[0] for f in filas] == [None, None]
    assert all(f[1] > datetime.fromisoformat("2026-01-02T00:00:00+00:00") for f in filas)
    assert sql(ajustes_lug, "SELECT count(*) FROM lugares")[0][0] == 0
    [(_, _, entidad_id, detalle)] = auditoria(ajustes_lug, "lugar.eliminar")
    assert entidad_id == lugar["id"] and detalle == {"nombre": "Biblioteca Central", "fotos_sin_lugar": 2}

    assert api.delete(f"/v1/admin/places/{lugar['id']}").status_code == 204
    assert len(auditoria(ajustes_lug, "lugar.eliminar")) == 1
    eventos = [linea for linea in logs_json.lineas if linea["evento"] == "lugar_eliminado"]
    assert [(e["existia"], e["fotos_sin_lugar"]) for e in eventos] == [(True, 2), (False, 0)]
    assert api.get("/v1/places").json() == {"items": [], "total": 0}


# --- Lectura pública ------------------------------------------------------------------------------------------------
def test_places_es_publico_y_ordena_por_nombre_normalizado(api, ajustes_lug):
    for nombre in ("Zeta", "árbol", "Biblioteca", "Ábside", "_Raro"):
        crear(api, nombre)
    with TestClient(crear_app(ajustes_lug)) as anonimo:
        sin_token = anonimo.get("/v1/places")
        token_malo = anonimo.get("/v1/places", headers={"Authorization": "Bearer no-es-un-token"})
    assert sin_token.status_code == 200 and token_malo.status_code == 200
    cuerpo = sin_token.json()
    ListaLugares[LugarPublico].model_validate(cuerpo)
    assert cuerpo["total"] == 5
    assert [p["nombre"] for p in cuerpo["items"]] == ["_Raro", "Ábside", "árbol", "Biblioteca", "Zeta"]
    assert all(p["distancia_m"] is None and set(p) == set(LugarPublico.model_fields) for p in cuerpo["items"])


def test_places_con_posicion_ordena_por_distancia_y_filtra_categoria(api):
    crear(api, "Lejos", categoria="entrada", lat=0.002, lng=0.001)  # ~111,2 m al norte
    crear(api, "Aquí", categoria="bloque", lat=0.001, lng=0.001)
    crear(api, "Empate B", categoria="bloque", lat=0.001, lng=0.0015)  # al este y al oeste: la misma distancia
    crear(api, "Empate A", categoria="bloque", lat=0.001, lng=0.0005)
    cuerpo = api.get("/v1/places", params={"lat": 0.001, "lng": 0.001}).json()
    assert [p["nombre"] for p in cuerpo["items"]] == ["Aquí", "Empate A", "Empate B", "Lejos"]
    distancias = [p["distancia_m"] for p in cuerpo["items"]]
    assert distancias[0] == 0.0 and distancias[1] == distancias[2] == 55.6 and distancias[3] == 111.2
    filtrado = api.get("/v1/places", params={"lat": 0.001, "lng": 0.001, "categoria": "entrada"}).json()
    assert [p["nombre"] for p in filtrado["items"]] == ["Lejos"] and filtrado["total"] == 1


@pytest.mark.parametrize(
    ("params", "campo"),
    [
        ({"lat": 1.0}, "lng"),
        ({"lng": 1.0}, "lat"),
        ({"lat": "nan", "lng": 1.0}, "lat"),
        ({"lat": 91, "lng": 1.0}, "lat"),
        ({"lat": 1, "lng": "abc"}, "lng"),
        ({"categoria": "cocina"}, "categoria"),
    ],
)
def test_places_con_parametros_no_validos_es_422(api, params, campo):
    r = api.get("/v1/places", params=params)
    assert r.status_code == 422, r.text
    assert [c["campo"] for c in r.json()["error"]["detalle"]["campos"]] == [campo]


def test_places_sin_base_es_503():
    ajustes = Settings(app_env="test", embedding_url=None)
    with TestClient(crear_app(ajustes)) as cliente:
        r = cliente.get("/v1/places")
    assert r.status_code == 503 and r.json()["error"]["codigo"] == "BASE_NO_DISPONIBLE"


# --- Lectura del panel ----------------------------------------------------------------------------------------------
def test_admin_places_busca_sin_tildes_ni_mayusculas(api, ajustes_lug):
    lugar = crear(api, "Café Norte", categoria="cafeteria")
    crear(api, "Bloque 100%")
    crear(api, "Bloque 1000")
    foto_con_lugar(ajustes_lug, lugar["id"])
    cuerpo = api.get("/v1/admin/places", params={"q": "  CAFÉ  "}).json()
    ListaLugares[LugarAdmin].model_validate(cuerpo)
    assert [(p["nombre"], p["total_fotos"]) for p in cuerpo["items"]] == [("Café Norte", 1)] and cuerpo["total"] == 1
    assert [p["nombre"] for p in api.get("/v1/admin/places", params={"q": "100%"}).json()["items"]] == ["Bloque 100%"]
    por_categoria = api.get("/v1/admin/places", params={"categoria": "cafeteria"}).json()["items"]
    assert [p["nombre"] for p in por_categoria] == ["Café Norte"]
    todos = api.get("/v1/admin/places", params={"q": "   "}).json()
    assert [p["nombre"] for p in todos["items"]] == ["Bloque 100%", "Bloque 1000", "Café Norte"]


@pytest.mark.parametrize("q", ["a\x00b", "x" * 101])
def test_admin_places_con_q_no_valida_es_422(api, q):
    r = api.get("/v1/admin/places", params={"q": q})
    assert r.status_code == 422 and r.json()["error"]["detalle"]["campos"][0]["campo"] == "q"


def test_leer_todos_para_la_localizacion(api, ajustes_lug):
    crear(api, "Zeta", categoria="bloque")
    crear(api, "Ágora", categoria="auditorio", lat=6.3, lng=-75.6)

    async def leer() -> tuple[list[lugares.LugarRef], list[lugares.LugarRef]]:
        motor = sesion.crear_motor(ajustes_lug, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                return await lugares.leer_todos(conexion), await lugares.leer_todos(conexion, CategoriaLugar.bloque)
        finally:
            await motor.dispose()

    todos, bloques = asyncio.run(leer())
    assert [(r.nombre, r.categoria, r.lat) for r in todos] == [
        ("Ágora", CategoriaLugar.auditorio, 6.3),
        ("Zeta", CategoriaLugar.bloque, 6.2009),
    ]
    assert [r.nombre for r in bloques] == ["Zeta"]
