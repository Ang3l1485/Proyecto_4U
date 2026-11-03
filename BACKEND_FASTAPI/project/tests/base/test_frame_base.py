"""BE-5.1 contra una base real: `POST /v1/localize/frame` (ARCHITECTURE §4.14, §5.3) y
`db.consultas.buscar_vecinos_en_radio`. Reutiliza las piezas de `test_localizacion_base.py` (cargado con `importlib`,
como `test_validate24.py` hace con el mundo falso de BE-2.2): `EmbeddingsFijos` (la foto registrada da `eje(0)`),
`con_similitud`, `indexar_en` en coordenadas propias, `crear_lugar`, `eventos`, `norte`/`este` y las fixtures `emb` y
`api`. Comprueba que una imagen fuera del radio nunca cuenta (aunque sea idéntica), el radio enviado y el por defecto,
`imagenes_en_radio`, el evento con `origen = frame` y que la consulta no usa el índice HNSW."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.clientes import embedding
from app.config import Settings
from app.db import consultas, sesion
from app.dominio import geo
from app.esquemas.localizacion import FrameRespuesta

pytestmark = pytest.mark.base

_ruta = Path(__file__).with_name("test_localizacion_base.py")
_spec = importlib.util.spec_from_file_location("piezas_localizacion_base", _ruta)
t32 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t32)

emb = t32.emb  # fixtures reutilizadas
api = t32.api

RUTA = "/v1/localize/frame"
LAT0, LNG0 = t32.LAT0, t32.LNG0
VERSION = t32.VERSION
APP_VERSION = "validacion-51-prueba"


def norte(m: float) -> float:
    return t32.norte(m)


def este(m: float) -> float:
    return t32.este(m)


def frame(
    api_: Any, foto: bytes, lat: float, lng: float, *, radio_m: float | None = None, rumbo: float | None = 90.0
) -> Any:
    metadatos: dict[str, Any] = {
        "rumbo": rumbo,
        "posicion_previa": {"lat": lat, "lng": lng},
        "app_version": APP_VERSION,
    }
    if radio_m is not None:
        metadatos["radio_m"] = radio_m
    files = [
        ("foto", ("frame.jpg", foto, "image/jpeg")),
        ("metadatos", (None, json.dumps(metadatos).encode(), "application/json")),
    ]
    return api_.post(RUTA, files=files)


@pytest.fixture
def foto(emb) -> bytes:
    foto = t32.jpeg(51)
    emb.registrar([foto])  # → eje(0)
    return foto


def test_lo_identico_fuera_del_radio_no_cuenta(api, base_migrada, emb, foto):
    """A (0,95) junto a la posición previa y B (idéntica, 1,0) a 300 m: con la previa cerca de A sale A; con la previa
    en B, sale B. Una imagen lejana nunca mueve la posición, por parecida que sea."""
    t32.indexar_en(base_migrada, [(t32.con_similitud(0, 0.95), LAT0, LNG0, 80.0), (t32.eje(0), norte(300), LNG0, 80.0)])
    lugar = t32.crear_lugar(base_migrada, "Biblioteca de prueba", norte(5), LNG0)

    r = frame(api, foto, LAT0, este(15))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert list(cuerpo) == list(FrameRespuesta.model_fields)
    assert (cuerpo["resultado"], cuerpo["nivel"], cuerpo["confianza"]) == ("ok", "alta", 1.0)
    assert geo.distancia_m(cuerpo["posicion"]["lat"], cuerpo["posicion"]["lng"], LAT0, LNG0) < 0.5
    assert cuerpo["distancia_previa_m"] == pytest.approx(15.0, abs=0.2)
    assert (cuerpo["radio_busqueda_m"], cuerpo["imagenes_en_radio"]) == (40.0, 1)  # B no está en el radio
    assert cuerpo["lugar_cercano"]["id"] == str(lugar)
    assert emb.llamadas == [{"n": 1, "prioridad": "alta", "request_id": emb.llamadas[0]["request_id"]}]

    r = frame(api, foto, norte(300), este(10))
    cuerpo = r.json()
    assert cuerpo["resultado"] == "ok" and cuerpo["imagenes_en_radio"] == 1
    assert geo.distancia_m(cuerpo["posicion"]["lat"], cuerpo["posicion"]["lng"], norte(300), LNG0) < 0.5


def test_sin_imagenes_en_el_radio_es_sin_coincidencias_y_deja_evento(api, base_migrada, foto):
    t32.indexar_en(base_migrada, [(t32.eje(0), LAT0, LNG0, None)])
    r = frame(api, foto, norte(1000), LNG0, rumbo=None)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["resultado"] == "sin_coincidencias" and cuerpo["imagenes_en_radio"] == 0
    assert cuerpo["posicion"] is None and cuerpo["distancia_previa_m"] is None and cuerpo["confianza"] == 0
    assert cuerpo["nivel"] is None and cuerpo["lugar_cercano"] is None and cuerpo["referencias"] == []
    filas = t32.eventos(base_migrada)
    assert len(filas) == 1
    origen, resultado, nivel, confianza, lat, lng, usadas, con_coincidencia, _lat_ms, version, app = filas[0]
    assert (origen, resultado, nivel, lat, lng, usadas, con_coincidencia) == (
        "frame", "sin_coincidencias", None, None, None, 1, 0,
    )  # fmt: skip
    assert confianza == 0 and version == VERSION and app == APP_VERSION


def test_radio_m_limita_la_busqueda(api, base_migrada, foto):
    """La imagen está a 60 m de la previa: con `radio_m` = 30 no se encuentra; con 100, sí."""
    t32.indexar_en(base_migrada, [(t32.eje(0), LAT0, LNG0, 10.0)])
    r = frame(api, foto, norte(-60), LNG0, radio_m=30)
    assert (r.json()["resultado"], r.json()["imagenes_en_radio"], r.json()["radio_busqueda_m"]) == (
        "sin_coincidencias", 0, 30.0,
    )  # fmt: skip
    r = frame(api, foto, norte(-60), LNG0, radio_m=100)
    cuerpo = r.json()
    assert cuerpo["resultado"] == "ok" and cuerpo["distancia_previa_m"] == pytest.approx(60.0, abs=0.2)


def test_borde_del_radio_por_haversine(api, base_migrada, foto):
    """A 39,5 m entra y a 40,5 m no (radio por defecto 40, la misma fórmula que `geo.distancia_m`)."""
    t32.indexar_en(base_migrada, [(t32.eje(0), LAT0, este(39.5), None), (t32.eje(0), LAT0, este(-40.5), None)])
    cuerpo = frame(api, foto, LAT0, LNG0).json()
    assert cuerpo["imagenes_en_radio"] == 1 and cuerpo["radio_busqueda_m"] == Settings().loc_frame_radio_m
    assert cuerpo["posicion"]["lng"] == pytest.approx(round(este(39.5), 6), abs=1e-6)


def test_evento_ok_y_los_errores_no_dejan_fila(api, base_migrada, foto, emb):
    t32.indexar_en(base_migrada, [(t32.eje(0), LAT0, LNG0, None)])
    assert frame(api, foto, LAT0, LNG0, radio_m=500).status_code == 422  # fuera de [10, 100]
    emb.fallo = embedding.EmbeddingNoDisponible("apagado")
    assert frame(api, foto, LAT0, LNG0).status_code == 503
    emb.fallo = None
    assert frame(api, foto, LAT0, LNG0).status_code == 200
    filas = t32.eventos(base_migrada)
    assert len(filas) == 1
    origen, resultado, nivel, _conf, lat, lng, usadas, con_coincidencia, _lat_ms, _ver, app = filas[0]
    assert (origen, resultado, nivel, usadas, con_coincidencia, app) == ("frame", "ok", "alta", 1, 1, APP_VERSION)
    assert (lat, lng) == (round(LAT0, 5), round(LNG0, 5))


def _consulta(ajustes: Settings, lat: float, lng: float, radio_m: float, k: int) -> tuple[list[Any], int]:
    async def correr() -> tuple[list[Any], int]:
        motor = sesion.crear_motor(ajustes, "pruebas")
        try:
            async with sesion.transaccion(motor) as conexion:
                return await consultas.buscar_vecinos_en_radio(
                    conexion, t32.eje(0), lat=lat, lng=lng, radio_m=radio_m, k=k, version_vector=VERSION
                )
        finally:
            await motor.dispose()

    return asyncio.run(correr())


def test_buscar_vecinos_en_radio_ordena_limita_y_cuenta(base_migrada):
    similitudes = [0.30, 0.95, 0.60, 0.80, 0.99, 0.10, 0.70, 0.50, 0.85, 0.40, 0.90, 0.20]
    filas = [(t32.con_similitud(0, s), norte(2 * i), LNG0, None) for i, s in enumerate(similitudes)]
    filas.append((t32.eje(0), norte(500), LNG0, None))  # idéntica y fuera del radio
    t32.indexar_en(base_migrada, filas)
    vecinos, en_radio = _consulta(base_migrada, LAT0, LNG0, 40.0, 10)
    assert en_radio == 12 and len(vecinos) == 10
    assert [round(v.similitud, 2) for v in vecinos] == sorted(similitudes, reverse=True)[:10]
    assert all(geo.distancia_m(LAT0, LNG0, v.lat, v.lng) <= 40.0 for v in vecinos)
    assert _consulta(base_migrada, norte(2000), LNG0, 40.0, 10) == ([], 0)


def test_buscar_vecinos_en_radio_rechaza_argumentos(base_migrada):
    with pytest.raises(ValueError, match="k"):
        _consulta(base_migrada, LAT0, LNG0, 40.0, 0)
    with pytest.raises(ValueError, match="radio_m"):
        _consulta(base_migrada, LAT0, LNG0, math.nan, 10)


async def _plan(ajustes: Settings) -> str:
    motor = sesion.crear_motor(ajustes, "pruebas")
    try:
        async with motor.begin() as conexion:
            await conexion.execute(text("SET LOCAL enable_seqscan = off"))  # aun empujado al índice, no lo usa
            filas = await conexion.execute(
                text("EXPLAIN " + consultas.sql_vecinos_en_radio(VERSION)),
                {"vector": consultas.texto_vector(t32.eje(0)), "lat": LAT0, "lng": LNG0, "radio": 40.0, "k": 10},
            )
            return "\n".join(str(f[0]) for f in filas.all())
    finally:
        await motor.dispose()


def test_la_consulta_del_radio_no_usa_el_indice_hnsw(base_migrada):
    t32.indexar_en(base_migrada, [(t32.con_similitud(0, 0.5), norte(i), LNG0, None) for i in range(10)])
    plan = asyncio.run(_plan(base_migrada))
    assert "hnsw" not in plan.lower(), plan
    assert "cerca" in plan.lower()  # la CTE materializada
