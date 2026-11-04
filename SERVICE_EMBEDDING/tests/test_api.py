"""
Tarea 2: contrato HTTP de /health y /predict (HU-020, escenarios 1, 2 y 3).

El modelo y la base se sustituyen: `embed_image` devuelve un vector fijo y `model_store`
se carga con referencias sintéticas (ver conftest.py).
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main


@pytest.fixture
def cliente():
    # Sin `with`: no se ejecuta el evento de arranque (no se toca la base).
    return TestClient(main.app)


@pytest.fixture
def embed_fijo(monkeypatch):
    """Sustituye embed_image por uno que devuelve el vector indicado y guarda la imagen recibida."""
    llamadas = []

    def configurar(vector):
        def falso(imagen):
            llamadas.append(imagen)
            return np.asarray(vector, dtype=np.float32)

        monkeypatch.setattr(main, "embed_image", falso)
        return llamadas

    return configurar


def _predict(cliente, contenido, nombre="consulta.png", tipo="image/png"):
    return cliente.post("/predict", files={"image": (nombre, contenido, tipo)})


# --------------------------------------------------------------------------- #
# Escenario 1: /health                                                        #
# --------------------------------------------------------------------------- #
def test_health_antes_de_cargar(cliente, store_vacio):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "ready": False}


def test_health_con_store_cargado(cliente, store_listo):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "ready": True}


def test_el_arranque_carga_el_store_una_vez(monkeypatch, store_vacio):
    llamadas = []
    monkeypatch.setattr(store_vacio, "load", lambda: llamadas.append(1))
    with TestClient(main.app) as c:
        assert c.get("/health").status_code == 200
    assert llamadas == [1]


# --------------------------------------------------------------------------- #
# Escenario 2: /predict                                                       #
# --------------------------------------------------------------------------- #
def test_predict_devuelve_los_cuatro_campos(cliente, store_listo, embed_fijo, imagen_png):
    embed_fijo([0.1, 0.9, 0.2, 0.0])
    r = _predict(cliente, imagen_png)
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"location", "point_id", "similarity", "matched_ref_image"}
    assert isinstance(cuerpo["similarity"], float)


def test_predict_elige_la_referencia_mas_parecida(cliente, store_listo, embed_fijo, imagen_png):
    embed_fijo([0.1, 0.9, 0.2, 0.0])  # más parecido a la fila 1 (Cafeteria)
    cuerpo = _predict(cliente, imagen_png).json()
    assert cuerpo["location"] == "Cafeteria"
    assert cuerpo["point_id"] == 2
    assert cuerpo["matched_ref_image"] == "cafeteria_01.png"
    assert cuerpo["similarity"] == pytest.approx(0.9, abs=1e-4)


def test_predict_redondea_la_similitud_a_4_decimales(cliente, store_listo, embed_fijo, imagen_png):
    embed_fijo([0.87654321, 0.0, 0.0, 0.0])
    cuerpo = _predict(cliente, imagen_png).json()
    assert cuerpo["similarity"] == 0.8765


def test_predict_en_empate_gana_la_primera_referencia(cliente, store_listo, embed_fijo, imagen_png):
    embed_fijo([0.5, 0.5, 0.0, 0.0])
    cuerpo = _predict(cliente, imagen_png).json()
    assert cuerpo["point_id"] == 1
    assert cuerpo["matched_ref_image"] == "biblioteca_01.png"


def test_predict_point_id_sin_nombre_devuelve_unknown(cliente, store_listo, embed_fijo, imagen_png):
    embed_fijo([0.0, 0.0, 1.0, 0.0])  # fila 2, point_id 99 no está en locations_info
    cuerpo = _predict(cliente, imagen_png).json()
    assert cuerpo["location"] == "Unknown"
    assert cuerpo["point_id"] == 99


@pytest.mark.parametrize(
    "modo, formato, tipo",
    [("RGBA", "PNG", "image/png"), ("L", "PNG", "image/png"), ("RGB", "JPEG", "image/jpeg")],
)
def test_predict_entrega_al_modelo_una_imagen_rgb(
    cliente, store_listo, embed_fijo, modo, formato, tipo
):
    import io

    buf = io.BytesIO()
    Image.new(modo, (40, 30)).save(buf, format=formato)
    llamadas = embed_fijo([1.0, 0.0, 0.0, 0.0])

    r = _predict(cliente, buf.getvalue(), nombre=f"consulta.{formato.lower()}", tipo=tipo)

    assert r.status_code == 200
    assert len(llamadas) == 1
    assert llamadas[0].mode == "RGB"
    assert llamadas[0].size == (40, 30)


# --------------------------------------------------------------------------- #
# Escenario 3: errores controlados                                            #
# --------------------------------------------------------------------------- #
def test_predict_archivo_que_no_es_imagen_da_400(cliente, store_listo, embed_fijo):
    llamadas = embed_fijo([1.0, 0.0, 0.0, 0.0])
    r = _predict(cliente, b"esto no es una imagen", nombre="nota.txt", tipo="text/plain")
    assert r.status_code == 400
    assert r.json() == {"detail": "Invalid image file"}
    assert llamadas == []  # no se llega a calcular el embedding


def test_predict_antes_de_cargar_da_503(cliente, store_vacio, embed_fijo, imagen_png):
    llamadas = embed_fijo([1.0, 0.0, 0.0, 0.0])
    r = _predict(cliente, imagen_png)
    assert r.status_code == 503
    assert r.json() == {"detail": "Model not ready yet"}
    assert llamadas == []


def test_predict_sin_campo_image_da_422(cliente, store_listo):
    r = cliente.post("/predict")
    assert r.status_code == 422


def test_predict_con_campo_con_otro_nombre_da_422(cliente, store_listo, imagen_png):
    r = cliente.post("/predict", files={"file": ("consulta.png", imagen_png, "image/png")})
    assert r.status_code == 422
