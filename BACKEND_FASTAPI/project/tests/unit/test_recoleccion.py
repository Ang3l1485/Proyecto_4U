"""Reglas puras de la recolección (`app.dominio.recoleccion`) y esquemas de §5.4 y §5.5 (`app.esquemas.videos`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.dominio.enumerados import EstadoVideo
from app.dominio.recoleccion import (
    Conteo,
    clave_dataset,
    clave_miniatura,
    como_real,
    es_dato_de_validacion,
    estado_video,
    ids_de_clave,
    prefijos_del_video,
    real_legible,
)
from app.esquemas.comun import Pagina, Referencia
from app.esquemas.videos import ImagenRegistro, InicioRecorrido, SubidaPut, VideoCrear

VIDEO_ID = uuid.UUID("9c1d0000-0000-4000-8000-000000000001")
IMAGEN_ID = uuid.UUID("a91f0000-0000-4000-8000-000000000002")


def test_claves_de_infra_5_5_y_su_inversa():
    assert clave_dataset(VIDEO_ID, IMAGEN_ID) == f"dataset/{VIDEO_ID}/{IMAGEN_ID}.jpg"
    assert clave_miniatura(VIDEO_ID, IMAGEN_ID) == f"thumbs/{VIDEO_ID}/{IMAGEN_ID}.jpg"
    assert prefijos_del_video(VIDEO_ID) == (f"dataset/{VIDEO_ID}/", f"thumbs/{VIDEO_ID}/")
    assert ids_de_clave(clave_dataset(VIDEO_ID, IMAGEN_ID)) == (VIDEO_ID, IMAGEN_ID)
    for mala in (
        f"thumbs/{VIDEO_ID}/{IMAGEN_ID}.jpg",
        f"dataset/{VIDEO_ID}/{IMAGEN_ID}.png",
        f"dataset/{VIDEO_ID}/{IMAGEN_ID}.jpg/x",
        f"dataset/{VIDEO_ID}".upper(),
        "",
    ):
        assert ids_de_clave(mala) is None


def test_conteo_desde_un_group_by():
    conteo = Conteo.desde({"subida": 3, "error": 1})
    assert conteo.como_dict() == {"pendiente_subida": 0, "subida": 3, "procesada": 0, "error": 1}
    assert conteo.total == 4


@pytest.mark.parametrize(
    ("conteo", "completa", "esperado"),
    [
        (Conteo(), False, EstadoVideo.pendiente),
        (Conteo(), True, EstadoVideo.procesado),
        (Conteo(subida=4), False, EstadoVideo.pendiente),
        (Conteo(pendiente_subida=1, subida=3), True, EstadoVideo.pendiente),
        (Conteo(subida=1, procesada=3), True, EstadoVideo.procesando),
        (Conteo(subida=1, error=1), True, EstadoVideo.procesando),
        (Conteo(procesada=3, error=1), True, EstadoVideo.con_errores),
        (Conteo(procesada=4), True, EstadoVideo.procesado),
    ],
)
def test_estado_del_video(conteo, completa, esperado):
    assert estado_video(conteo, completa) == esperado


def test_solo_se_limpia_con_el_prefijo_en_nombre_y_ref():
    assert es_dato_de_validacion("validacion-21-x", "validacion-21-x")
    assert not es_dato_de_validacion("validacion-21-x", "rec_0003")
    assert not es_dato_de_validacion("video_3", "validacion-21-x")
    assert not es_dato_de_validacion("Validacion-21", "validacion-21")


def test_real_como_float32_y_legible():
    assert como_real(359.99999999) == 360.0
    assert como_real(340.3) != 340.3
    assert real_legible(como_real(340.3)) == 340.3
    assert real_legible(como_real(182.3)) == 182.3
    casi_360 = como_real(359.99997)
    assert real_legible(casi_360) < 360 and como_real(real_legible(casi_360)) == casi_360
    assert real_legible(None) is None and real_legible(0.0) == 0.0


# --- Esquemas -------------------------------------------------------------------------------------------------------
def test_video_crear_recorta_y_normaliza():
    datos = VideoCrear.model_validate({"ref_cliente": "  rec_1 ", "nombre": "  ", "dispositivo": " Pixel "})
    assert (datos.ref_cliente, datos.nombre, datos.dispositivo, datos.total_fotos) == ("rec_1", None, "Pixel", 0)
    assert VideoCrear.model_validate({"ref_cliente": "r", "nombre": " Entrada "}).nombre == "Entrada"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"ref_cliente": "   "},
        {"ref_cliente": "r" * 41},
        {"ref_cliente": "r", "nombre": "x" * 41},
        {"ref_cliente": "r\x00"},
        {"ref_cliente": "r", "app_version": "v" * 41},
        {"ref_cliente": "r", "distancia_m": float("nan")},
        {"ref_cliente": "r", "distancia_m": 1e7},
        {"ref_cliente": "r", "pasos": 2**31},
        {"ref_cliente": "r", "iniciado_en": "2026-10-20T14:00:00"},
        {"ref_cliente": "r", "iniciado_en": "2026-10-20T15:00:00Z", "finalizado_en": "2026-10-20T14:00:00Z"},
    ],
)
def test_video_crear_rechaza(cuerpo):
    with pytest.raises(ValidationError):
        VideoCrear.model_validate(cuerpo)


@pytest.mark.parametrize("rumbo", [-0.1, 360, 359.99999999, float("inf"), 1e39])
def test_rumbo_fuera_de_rango_tambien_como_real(rumbo):
    with pytest.raises(ValidationError):
        InicioRecorrido(lat=0, lng=0, rumbo=rumbo)
    with pytest.raises(ValidationError):
        ImagenRegistro(orden=1, lat=0, lng=0, rumbo=rumbo, capturada_en=datetime.now(UTC), bytes=1)


def test_rumbo_nulo_y_fecha_con_otra_zona():
    imagen = ImagenRegistro.model_validate(
        {"orden": 1, "lat": 0, "lng": 0, "capturada_en": "2026-10-20T09:00:05-05:00", "bytes": 1}
    )
    assert imagen.rumbo is None and imagen.capturada_en == datetime(2026, 10, 20, 14, 0, 5, tzinfo=UTC)


def test_fechas_de_salida_en_utc_con_z_y_sin_fracciones():
    hora = datetime(2026, 10, 23, 10, 4, 5, 987654, tzinfo=timezone(timedelta(hours=-5)))
    subida = SubidaPut(url="https://x", encabezados={}, expira_en=hora)
    assert subida.model_dump(mode="json")["expira_en"] == "2026-10-23T15:04:05Z"
    assert subida.model_dump()["expira_en"] == "2026-10-23T15:04:05Z"


def test_pagina_generica():
    pagina = Pagina[Referencia](items=[Referencia(id=VIDEO_ID, nombre="x")], total=1, pagina=1, por_pagina=24)
    assert pagina.model_dump(mode="json")["items"] == [{"id": str(VIDEO_ID), "nombre": "x"}]


@pytest.mark.parametrize("fecha", ["0001-01-01T00:00:00+05:00", "9999-12-31T23:00:00-05:00"])
def test_fecha_con_zona_fuera_de_rango_en_utc_es_error_de_validacion(fecha):
    with pytest.raises(ValidationError, match="fuera de rango"):
        VideoCrear.model_validate({"ref_cliente": "r", "iniciado_en": fecha})


def test_fecha_con_zona_se_guarda_en_utc_y_los_extremos_validos_pasan():
    datos = VideoCrear.model_validate(
        {"ref_cliente": "r", "iniciado_en": "0001-01-01T00:00:00Z", "finalizado_en": "9999-12-31T18:00:00-05:00"}
    )
    assert datos.iniciado_en.tzinfo == UTC and datos.finalizado_en == datetime(9999, 12, 31, 23, 0, tzinfo=UTC)
