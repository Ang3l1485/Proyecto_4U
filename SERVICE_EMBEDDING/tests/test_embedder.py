"""
Tarea 6: app/embedder.py (HU-020, escenario 2).

- Pruebas rápidas: un CLIP diminuto creado en memoria (pesos aleatorios, sin descarga) ejercita
  el mismo código de embed_image: procesador → vision_model → visual_projection → L2.
- Prueba `modelo` (opcional): CLIP real `openai/clip-vit-base-patch32` desde Hugging Face.
  Ejecutar con:  python -m pytest -m modelo
"""

import numpy as np
import pytest
from PIL import Image

from tests.conftest import TORCH_REAL

pytestmark = pytest.mark.skipif(not TORCH_REAL, reason="torch/transformers no instalados")

DIM_PROYECCION = 16


@pytest.fixture
def embedder_limpio(monkeypatch):
    """embedder sin modelo cargado; restaura el estado global al terminar."""
    import app.embedder as embedder

    monkeypatch.setattr(embedder, "_model", None)
    monkeypatch.setattr(embedder, "_processor", None)
    monkeypatch.setattr(embedder, "_device", "cpu")
    return embedder


@pytest.fixture
def clip_diminuto(embedder_limpio, monkeypatch):
    """Sustituye CLIPModel/CLIPProcessor.from_pretrained por un CLIP pequeño local."""
    import torch
    from transformers import CLIPConfig, CLIPImageProcessor, CLIPModel

    torch.manual_seed(0)
    cfg = CLIPConfig(
        vision_config=dict(hidden_size=32, intermediate_size=37, num_hidden_layers=1,
                           num_attention_heads=2, image_size=32, patch_size=16),
        text_config=dict(hidden_size=32, intermediate_size=37, num_hidden_layers=1,
                         num_attention_heads=2, vocab_size=99, max_position_embeddings=16,
                         bos_token_id=0, eos_token_id=1, pad_token_id=1),
        projection_dim=DIM_PROYECCION,
    )
    modelo = CLIPModel(cfg).eval()
    procesador = CLIPImageProcessor(size={"shortest_edge": 32}, crop_size={"height": 32, "width": 32})
    llamadas = []

    class ModeloFalso:
        @staticmethod
        def from_pretrained(model_id):
            llamadas.append(("modelo", model_id))
            return modelo

    class ProcesadorFalso:
        @staticmethod
        def from_pretrained(model_id):
            llamadas.append(("procesador", model_id))
            return procesador

    monkeypatch.setattr(embedder_limpio, "CLIPModel", ModeloFalso)
    monkeypatch.setattr(embedder_limpio, "CLIPProcessor", ProcesadorFalso)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return embedder_limpio, llamadas


def _imagen(color, modo="RGB", tam=(64, 48)):
    img = Image.new("RGB", tam, color)
    # Un patrón para que no todas las imágenes sean planas.
    for x in range(0, tam[0], 8):
        for y in range(0, tam[1], 8):
            img.putpixel((x, y), (255 - color[0], 255 - color[1], 255 - color[2]))
    return img.convert(modo)


# --------------------------------------------------------------------------- #
# Pruebas rápidas (sin descarga)                                              #
# --------------------------------------------------------------------------- #
def test_embedding_es_vector_1d_float32_con_norma_1(clip_diminuto):
    embedder, _ = clip_diminuto
    vec = embedder.embed_image(_imagen((200, 30, 30)))
    assert vec.shape == (DIM_PROYECCION,)
    assert vec.dtype == np.float32
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)


def test_el_modelo_se_carga_una_sola_vez_con_el_id_configurado(clip_diminuto):
    from app import config

    embedder, llamadas = clip_diminuto
    embedder.embed_image(_imagen((10, 200, 10)))
    embedder.embed_image(_imagen((10, 10, 200)))
    assert llamadas == [("modelo", config.CLIP_MODEL_ID), ("procesador", config.CLIP_MODEL_ID)]


def test_misma_imagen_da_el_mismo_vector(clip_diminuto):
    embedder, _ = clip_diminuto
    a = embedder.embed_image(_imagen((90, 120, 150)))
    b = embedder.embed_image(_imagen((90, 120, 150)))
    np.testing.assert_allclose(a, b, atol=1e-6)
    assert float(a @ b) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.parametrize("modo", ["RGBA", "L", "P"])
def test_acepta_imagenes_que_no_son_rgb(clip_diminuto, modo):
    embedder, _ = clip_diminuto
    vec = embedder.embed_image(_imagen((40, 80, 160), modo=modo))
    assert vec.shape == (DIM_PROYECCION,)
    assert np.linalg.norm(vec) == pytest.approx(1.0, abs=1e-5)


def test_compatible_con_la_matriz_de_referencias(clip_diminuto):
    """Los vectores del embedder sirven para el producto punto que hace /predict."""
    embedder, _ = clip_diminuto
    refs = np.vstack([embedder.embed_image(_imagen(c)) for c in [(200, 0, 0), (0, 200, 0), (0, 0, 200)]])
    consulta = embedder.embed_image(_imagen((0, 200, 0)))
    sims = refs @ consulta
    assert int(np.argmax(sims)) == 1
    assert sims.max() == pytest.approx(1.0, abs=1e-5)


# --------------------------------------------------------------------------- #
# Prueba con CLIP real (opcional, necesita internet)                          #
# --------------------------------------------------------------------------- #
@pytest.mark.modelo
def test_clip_real_vector_512_normalizado(embedder_limpio):
    a = embedder_limpio.embed_image(_imagen((200, 30, 30)))
    b = embedder_limpio.embed_image(_imagen((200, 30, 30)))
    c = embedder_limpio.embed_image(_imagen((20, 60, 220)))
    assert a.shape == (512,)
    assert a.dtype == np.float32
    assert np.linalg.norm(a) == pytest.approx(1.0, abs=1e-5)
    assert float(a @ b) >= 0.999
    assert float(a @ c) < float(a @ b)
