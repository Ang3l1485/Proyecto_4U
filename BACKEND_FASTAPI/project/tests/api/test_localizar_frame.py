"""BE-5.1 sin base de datos: `POST /v1/localize/frame` (ARCHITECTURE §4.14, §5.3). Lo que se valida antes de tocar
la base (`400`/`422`, en el orden de §5.3), que es público, y, con el servicio sustituido, la respuesta, el evento de
log `frame_calculado` y la traducción de los errores de embeddings. La búsqueda en el radio y el evento de
`eventos_localizacion` van en `tests/base/test_frame_base.py`."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.v1 import localizar as router_localizar
from app.clientes import embedding
from app.config import Settings
from app.dominio import geo, localizacion
from app.esquemas.localizacion import FrameRespuesta
from app.servicios import localizar as servicio

RUTA = "/v1/localize/frame"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PREVIA = {"lat": 6.2001, "lng": -75.5786}
METADATOS = {"rumbo": 84.5, "posicion_previa": PREVIA, "radio_m": 40, "app_version": "1.0"}


def _error(r) -> tuple[int, str, Any]:
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}
    return r.status_code, cuerpo["error"]["codigo"], cuerpo["error"]["detalle"]


def frame(cliente, *, foto: Any = JPEG, metadatos: Any = METADATOS, extra: list | None = None, **kwargs: Any):
    files: list = []
    if foto is not None:
        files.append(("foto", ("frame.jpg", foto, "image/jpeg")))
    if metadatos is not None:
        cuerpo = metadatos if isinstance(metadatos, bytes) else json.dumps(metadatos).encode()
        files.append(("metadatos", (None, cuerpo, "application/json")))
    files += extra or []
    if not files:
        files = [("otra", (None, b"nada", "text/plain"))]
    return cliente.post(RUTA, files=files, **kwargs)


def _campos(r) -> list[str]:
    estado, codigo, detalle = _error(r)
    assert (estado, codigo) == (422, "VALIDACION")
    return [c["campo"] for c in detalle["campos"]]


# --- 400 FOTOS_INVALIDAS / SOLICITUD_INVALIDA --------------------------------------------------------------------
def test_sin_multipart_falta_la_parte_foto(cliente):
    estado, codigo, detalle = _error(cliente.post(RUTA, json={"foto": "x"}))
    assert (estado, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0)
    assert "falta la parte foto" in detalle["motivo"]


def test_cuerpo_de_mas_es_400_con_indice_0(cliente, ajustes):
    grande = JPEG + b"\x00" * (ajustes.loc_max_bytes_foto + 70_000)
    estado, codigo, detalle = _error(frame(cliente, foto=grande))
    assert (estado, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0)
    assert "una foto de" in detalle["motivo"]


def test_multipart_mal_formado(cliente):
    r = cliente.post(RUTA, content=b"--x\r\nsin cabeceras", headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert _error(r)[:2] == (400, "SOLICITUD_INVALIDA")


def test_parte_fotos_de_localize_no_cuenta(cliente):
    r = frame(cliente, foto=None, extra=[("fotos", ("0.jpg", JPEG, "image/jpeg"))])
    estado, codigo, detalle = _error(r)
    assert (estado, codigo, detalle) == (400, "FOTOS_INVALIDAS", {"indice": 0, "motivo": "falta la parte foto"})


def test_dos_fotos_es_indice_1(cliente):
    r = frame(cliente, extra=[("foto", ("otra.jpg", JPEG, "image/jpeg"))])
    estado, codigo, detalle = _error(r)
    assert (estado, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 1)


@pytest.mark.parametrize(
    ("tipo", "datos", "motivo"),
    [("image/png", JPEG, "tipo image/png"), ("image/jpeg", b"", "vacía"), ("image/jpeg", b"GIF89a", "FF D8 FF")],
)
def test_foto_que_no_vale(cliente, tipo, datos, motivo):
    r = cliente.post(
        RUTA,
        files=[
            ("foto", ("f.jpg", datos, tipo)),
            ("metadatos", (None, json.dumps(METADATOS).encode(), "application/json")),
        ],
    )
    estado, codigo, detalle = _error(r)
    assert (estado, codigo, detalle["indice"]) == (400, "FOTOS_INVALIDAS", 0)
    assert motivo in detalle["motivo"]


# --- 422 VALIDACION (metadatos) ----------------------------------------------------------------------------------
def test_sin_metadatos_o_repetidos(cliente):
    assert _campos(frame(cliente, metadatos=None)) == ["metadatos"]
    repetidos = [("metadatos", (None, json.dumps(METADATOS).encode(), "application/json"))]
    assert _campos(frame(cliente, extra=repetidos)) == ["metadatos"]


def test_metadatos_que_no_son_json_es_400(cliente):
    assert _error(frame(cliente, metadatos=b"{no"))[:2] == (400, "SOLICITUD_INVALIDA")


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"rumbo": 360}, "metadatos.rumbo"),
        ({"rumbo": -0.1}, "metadatos.rumbo"),
        ({"rumbo": "norte"}, "metadatos.rumbo"),
        ({"posicion_previa": None}, "metadatos.posicion_previa"),
        ({"posicion_previa": 5}, "metadatos.posicion_previa"),
        ({"posicion_previa": {"lat": 91, "lng": 0}}, "metadatos.posicion_previa.lat"),
        ({"posicion_previa": {"lat": 0, "lng": -180.5}}, "metadatos.posicion_previa.lng"),
        ({"posicion_previa": {"lat": 0}}, "metadatos.posicion_previa.lng"),
        ({"radio_m": 9.9}, "metadatos.radio_m"),
        ({"radio_m": 100.1}, "metadatos.radio_m"),
        ({"radio_m": "40"}, None),  # Pydantic acepta el texto numérico, como en el resto de la API (llega a la base)
        ({"app_version": "x" * 41}, "metadatos.app_version"),
    ],
)
def test_campos_que_no_valen(cliente, cambios, campo):
    r = frame(cliente, metadatos=METADATOS | cambios)
    if campo is None:
        assert _error(r)[:2] == (503, "BASE_NO_DISPONIBLE")
    else:
        assert _campos(r) == [campo]


def test_faltan_rumbo_y_posicion_previa(cliente):
    assert _campos(frame(cliente, metadatos={"radio_m": 40})) == ["metadatos.rumbo", "metadatos.posicion_previa"]


def test_nan_no_vale(cliente):
    texto = json.dumps(METADATOS).replace('"radio_m": 40', '"radio_m": NaN').encode()
    assert _campos(frame(cliente, metadatos=texto)) == ["metadatos.radio_m"]


@pytest.mark.parametrize(
    "metadatos",
    [
        {"rumbo": None, "posicion_previa": PREVIA},  # rumbo nulo y radio por defecto
        METADATOS | {"origen": "escaneo", "otro": 1},  # campos de más, ignorados
        METADATOS | {"radio_m": 10},
        METADATOS | {"radio_m": 100},
    ],
)
def test_metadatos_validos_llegan_a_la_base(cliente, metadatos):
    """Sin motor, una petición válida termina en `503 BASE_NO_DISPONIBLE` (la validación pasó)."""
    assert _error(frame(cliente, metadatos=metadatos))[:2] == (503, "BASE_NO_DISPONIBLE")


def test_es_publico_e_ignora_authorization(cliente):
    r = frame(cliente, headers={"Authorization": "Bearer no-es-un-token"})
    assert _error(r)[:2] == (503, "BASE_NO_DISPONIBLE")


def test_metadatos_del_frame_usa_el_radio_por_defecto(ajustes):
    parte = SimpleNamespace(nombre="metadatos", datos=json.dumps({"rumbo": None, "posicion_previa": PREVIA}).encode())
    metadatos, radio = router_localizar.metadatos_del_frame([parte], ajustes)
    assert (metadatos.radio_m, radio) == (None, ajustes.loc_frame_radio_m)


# --- con el servicio sustituido -------------------------------------------------------------------------------------
def _resultado(vecinos: list[SimpleNamespace], *, radio_m: float = 40.0, en_radio: int = 3) -> servicio.ResultadoFrame:
    loc = localizacion.localizar([vecinos], [84.5], localizacion.Parametros())
    pos = loc.posicion
    distancia = None if pos is None else geo.distancia_m(PREVIA["lat"], PREVIA["lng"], pos.lat, pos.lng)
    return servicio.ResultadoFrame(
        localizacion=loc, lugar_cercano=None, referencias=[], distancia_previa_m=distancia, radio_busqueda_m=radio_m,
        imagenes_en_radio=en_radio, version_vector="dinov2-vits14/pp-v1", embedding_ms=90, busqueda_ms=4,
        latencia_ms=120,
    )  # fmt: skip


@pytest.fixture
def con_servicio(monkeypatch):
    """Sustituye el motor y `servicios.localizar.localizar_frame`; `llamadas` guarda los argumentos."""
    estado: dict[str, Any] = {"llamadas": [], "resultado": None, "fallo": None}

    async def falso(motor, ajustes, foto, rumbo, **kwargs):
        estado["llamadas"].append({"foto": foto, "rumbo": rumbo, **kwargs})
        if estado["fallo"] is not None:
            raise estado["fallo"]
        return estado["resultado"]

    monkeypatch.setattr(router_localizar, "obtener_motor", lambda request: object())
    monkeypatch.setattr(servicio, "localizar_frame", falso)
    return estado


def test_respuesta_ok_con_la_forma_de_5_3(cliente, con_servicio, logs_json):
    norte = PREVIA["lat"] + 10 / (geo.RADIO_TIERRA_M * 3.141592653589793 / 180)
    vecinos = [SimpleNamespace(lat=norte, lng=PREVIA["lng"], similitud=0.97, rumbo=80.0)]
    con_servicio["resultado"] = _resultado(vecinos)
    r = frame(cliente, metadatos=METADATOS | {"radio_m": 35.25})
    assert r.status_code == 200
    cuerpo = r.json()
    assert list(cuerpo) == list(FrameRespuesta.model_fields)
    assert cuerpo["resultado"] == "ok" and cuerpo["nivel"] == "alta" and cuerpo["confianza"] == 1.0
    assert cuerpo["posicion"] == {"lat": round(norte, 6), "lng": PREVIA["lng"], "radio_m": 5.0}
    assert cuerpo["distancia_previa_m"] == 10.0 and cuerpo["radio_busqueda_m"] == 40.0
    assert cuerpo["imagenes_en_radio"] == 3 and cuerpo["referencias"] == [] and cuerpo["lugar_cercano"] is None
    llamada = con_servicio["llamadas"][0]
    assert llamada["foto"] == JPEG and llamada["rumbo"] == 84.5
    assert (llamada["lat"], llamada["lng"], llamada["radio_m"]) == (PREVIA["lat"], PREVIA["lng"], 35.25)
    assert llamada["app_version"] == "1.0"
    linea = next(lin for lin in logs_json.lineas if lin["evento"] == "frame_calculado")
    assert linea["imagenes_en_radio"] == 3 and linea["distancia_previa_m"] == 10.0 and linea["bytes"] == len(JPEG)
    assert "lat" not in linea and "lng" not in linea and str(PREVIA["lat"]) not in json.dumps(linea)


def test_sin_coincidencias_es_200(cliente, con_servicio):
    con_servicio["resultado"] = _resultado([SimpleNamespace(lat=0, lng=0, similitud=0.2, rumbo=None)], en_radio=1)
    r = frame(cliente, metadatos={"rumbo": None, "posicion_previa": PREVIA})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["resultado"] == "sin_coincidencias" and cuerpo["confianza"] == 0
    assert cuerpo["posicion"] is None and cuerpo["nivel"] is None and cuerpo["distancia_previa_m"] is None
    assert cuerpo["imagenes_en_radio"] == 1 and con_servicio["llamadas"][0]["radio_m"] == Settings().loc_frame_radio_m


@pytest.mark.parametrize(
    ("fallo", "esperado"),
    [
        (embedding.EmbeddingNoDisponible("apagado"), (503, "EMBEDDING_NO_DISPONIBLE")),
        (embedding.RespuestaNoValida("rota"), (503, "EMBEDDING_NO_DISPONIBLE")),
        (servicio.VersionVectorDistinta("a", "b"), (503, "EMBEDDING_NO_DISPONIBLE")),
        (embedding.ImagenRechazada(0, "IMAGEN_INVALIDA"), (400, "FOTOS_INVALIDAS")),
    ],
)
def test_errores_de_embeddings(cliente, con_servicio, fallo, esperado):
    con_servicio["fallo"] = fallo
    r = frame(cliente)
    assert _error(r)[:2] == esperado
    if esperado[1] == "FOTOS_INVALIDAS":
        assert _error(r)[2] == {"indice": 0, "motivo": "embeddings la rechazó (IMAGEN_INVALIDA)"}
