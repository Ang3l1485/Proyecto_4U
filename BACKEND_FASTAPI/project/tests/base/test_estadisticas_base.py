"""BE-2.3 contra una base real: `GET /v1/admin/stats` (ARCHITECTURE §4.7, §5.5).

Los datos se insertan por SQL (videos eliminados y alertas no tienen todavía endpoint: BE-4.1 y BE-3.3), salvo donde
se comprueba la coherencia con lo que devuelve la API de recolección.
"""

from __future__ import annotations

import asyncio
import base64
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.config import Settings
from app.db import sesion
from app.dominio.enumerados import RolUsuario
from app.esquemas.estadisticas import ResumenPanel, UltimoVideo
from app.main import crear_app
from app.seguridad import tokens
from app.servicios import estadisticas

pytestmark = pytest.mark.base

ADMIN = "admin.pruebas@campus.edu.co"
PASSWORD_ADMIN = "Pruebas-admin-123"
CLAVE = base64.b64encode(b"clave-de-pruebas-del-resumen".ljust(64, b"r")).decode()
RUTA = "/v1/admin/stats"
FECHA_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
VACIO = {"total_fotos": 0, "total_lugares": 0, "alertas_activas": 0, "ultimo_video": None}


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
def ajustes_st(base_migrada: Settings) -> Settings:
    return base_migrada.model_copy(update={"jwt_secret": SecretStr(CLAVE)})


@pytest.fixture
def api(ajustes_st):
    with TestClient(crear_app(ajustes_st)) as cliente:
        r = cliente.post("/v1/auth/login", json={"identificador": ADMIN, "password": PASSWORD_ADMIN})
        assert r.status_code == 200, r.text
        cliente.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield cliente


def video(ajustes: Settings, *, eliminado: bool = False, creado_en: datetime | None = None) -> tuple[uuid.UUID, int]:
    """Inserta un video `validacion-23` del admin (eliminado o no; `creado_en` = `now()` si no se da).
    Devuelve `(id, numero)`."""
    estado = "'eliminado', now(), id" if eliminado else "'pendiente', NULL, NULL"
    [(video_id, numero)] = sql(
        ajustes,
        "INSERT INTO videos (nombre, ref_cliente, creado_por, creado_en, estado, eliminado_en, eliminado_por) "  # noqa: S608
        f"SELECT 'validacion-23', :ref, id, coalesce(:creado, now()), {estado} FROM usuarios LIMIT 1 "
        "RETURNING id, numero",
        ref=f"validacion-23-{uuid.uuid4().hex[:8]}",
        creado=creado_en,
    )
    return video_id, numero


def fotos(ajustes: Settings, video_id: uuid.UUID, *estados: str) -> None:
    """Una foto por estado, con `orden` 1, 2…"""
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


def lugar(ajustes: Settings, nombre: str) -> None:
    sql(
        ajustes,
        "INSERT INTO lugares (nombre, nombre_normalizado, categoria, lat, lng, creado_por) "
        "SELECT :n, :n, 'bloque', 1.0, -100.0, id FROM usuarios LIMIT 1",
        n=nombre,
    )


def alerta(ajustes: Settings, *, activa: bool = True, eliminada: bool = False, desde: datetime | None = None) -> None:
    sql(
        ajustes,
        "INSERT INTO alertas (lat, lng, mensaje, activa, eliminada_en, vigencia_desde, creado_por, actualizado_por) "
        "SELECT 1.0, -100.0, 'validacion-23 alerta', :a, CASE WHEN :b THEN now() END, :d, id, id "
        "FROM usuarios LIMIT 1",
        a=activa,
        b=eliminada,
        d=desde,
    )


def _resumen(api: TestClient) -> dict[str, Any]:
    r = api.get(RUTA)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"total_fotos", "total_lugares", "alertas_activas", "ultimo_video"}
    ResumenPanel.model_validate(cuerpo)
    return cuerpo


# --- Totales ---------------------------------------------------------------------------------------------------------
def test_base_vacia_da_ceros_y_ultimo_video_nulo(api):
    assert _resumen(api) == VACIO


def test_total_fotos_cuenta_solo_procesadas_de_videos_no_eliminados(api, ajustes_st):
    vivo, _ = video(ajustes_st)
    fotos(ajustes_st, vivo, "procesada", "procesada", "subida", "error", "pendiente_subida")
    otro, _ = video(ajustes_st)
    fotos(ajustes_st, otro, "procesada")
    borrado, _ = video(ajustes_st, eliminado=True)
    fotos(ajustes_st, borrado, "procesada", "procesada")
    assert _resumen(api)["total_fotos"] == 3


def test_total_lugares_cuenta_todas_las_filas(api, ajustes_st):
    for nombre in ("validacion-23 a", "validacion-23 b", "validacion-23 c"):
        lugar(ajustes_st, nombre)
    assert _resumen(api)["total_lugares"] == 3
    r = api.post(
        "/v1/admin/places", json={"nombre": "validacion-23 d", "categoria": "bloque", "lat": 1.0, "lng": -100.0}
    )
    assert r.status_code == 201, r.text
    assert _resumen(api)["total_lugares"] == 4
    assert api.delete(f"/v1/admin/places/{r.json()['id']}").status_code == 204
    assert _resumen(api)["total_lugares"] == 3


def test_alertas_activas_sin_borrar_y_sin_mirar_la_vigencia(api, ajustes_st):
    alerta(ajustes_st)  # cuenta
    alerta(ajustes_st, desde=datetime.now(UTC) + timedelta(days=3))  # vigencia futura: cuenta (§5.5, sin vigencia)
    alerta(ajustes_st, activa=False)  # inactiva: no
    alerta(ajustes_st, eliminada=True)  # borrada (tombstone): no
    alerta(ajustes_st, activa=False, eliminada=True)
    assert _resumen(api)["alertas_activas"] == 2


# --- Último video ----------------------------------------------------------------------------------------------------
def test_ultimo_video_es_el_mas_reciente_no_eliminado(api, ajustes_st):
    base = datetime(2026, 10, 20, 14, 0, 0, 123456, tzinfo=UTC)
    video(ajustes_st, creado_en=base)
    _, numero = video(ajustes_st, creado_en=base + timedelta(hours=1))
    video(ajustes_st, creado_en=base - timedelta(days=1))  # más viejo, con número mayor
    video(ajustes_st, eliminado=True, creado_en=base + timedelta(days=1))  # más reciente, pero eliminado
    ultimo = _resumen(api)["ultimo_video"]
    assert ultimo == {"numero": numero, "creado_en": "2026-10-20T15:00:00Z"}  # UTC, con Z y sin fracciones
    assert FECHA_UTC.match(ultimo["creado_en"])


def test_a_igual_creado_en_gana_el_numero_mayor(api, ajustes_st):
    momento = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
    _, primero = video(ajustes_st, creado_en=momento)
    _, segundo = video(ajustes_st, creado_en=momento)
    assert segundo > primero
    assert _resumen(api)["ultimo_video"]["numero"] == segundo


def test_solo_videos_eliminados_da_ultimo_video_nulo(api, ajustes_st):
    borrado, _ = video(ajustes_st, eliminado=True)
    fotos(ajustes_st, borrado, "procesada")
    assert _resumen(api) == VACIO


def test_coincide_con_la_recoleccion_y_con_el_listado(api):
    """`ultimo_video` es el `numero` y `creado_en` del `VideoResumen` recién creado y el primero del listado por
    defecto de `GET /v1/admin/videos`."""
    r = api.post("/v1/collect/videos", json={"ref_cliente": "validacion-23-api", "nombre": "validacion-23-api"})
    assert r.status_code == 201, r.text
    creado = r.json()
    ultimo = _resumen(api)["ultimo_video"]
    assert ultimo == {"numero": creado["numero"], "creado_en": creado["creado_en"]}
    primero = api.get("/v1/admin/videos").json()["items"][0]
    assert (primero["numero"], primero["creado_en"]) == (ultimo["numero"], ultimo["creado_en"])


# --- Petición --------------------------------------------------------------------------------------------------------
def test_ignora_parametros_y_exige_token(api, ajustes_st):
    assert api.get(RUTA, params={"desde": "x", "q": "y"}).json() == VACIO
    sin_token = api.get(RUTA, headers={"Authorization": ""})
    assert sin_token.status_code == 401 and sin_token.json()["error"]["codigo"] == "NO_AUTENTICADO"
    assert api.get(f"{RUTA}/").status_code == 404  # sin barra final (§5.1)
    # El reservado de BE-5.2 sigue respondiendo 501 detrás de requiere_admin.
    uso = api.get(f"{RUTA}/uso")
    assert uso.status_code == 501 and uso.json()["error"]["codigo"] == "NO_IMPLEMENTADO"


def test_token_de_rol_user_es_403(api, ajustes_st):
    [(usuario_id,)] = sql(
        ajustes_st,
        "INSERT INTO usuarios (correo, nombre, rol, hash_password) "
        "VALUES ('validacion+user@campus.edu.co', 'validacion-usuario', 'user', 'x') RETURNING id",
    )
    token = tokens.emitir(usuario_id=usuario_id, rol=RolUsuario.user, nombre="u", ajustes=ajustes_st).token
    r = api.get(RUTA, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "SIN_PERMISOS"


def test_servicio_en_una_sentencia(ajustes_st):
    """`resumen` usa una sola sentencia (las cifras salen de la misma instantánea)."""
    sentencia = str(estadisticas.sql_resumen())
    assert sentencia.count("SELECT") == 6  # el SELECT exterior y sus cinco subconsultas escalares

    async def correr() -> ResumenPanel:
        motor = sesion.crear_motor(ajustes_st, "pruebas")
        try:
            return await estadisticas.resumen(motor)
        finally:
            await motor.dispose()

    resultado = asyncio.run(correr())
    assert resultado == ResumenPanel(total_fotos=0, total_lugares=0, alertas_activas=0, ultimo_video=None)
    assert UltimoVideo.model_fields.keys() == {"numero", "creado_en"}
