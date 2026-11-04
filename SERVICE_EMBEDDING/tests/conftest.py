"""
Configuración común de las pruebas locales (HU-020).

- Sin AWS: credenciales ficticias y archivos de configuración de AWS inexistentes, para que
  ninguna llamada real pueda salir aunque la máquina tenga un perfil configurado.
- Sin red: se bloquean las conexiones a hosts que no sean locales (salvo pruebas `modelo`).
- Sin fotos versionadas: las imágenes se generan en memoria con PIL.
"""

import io
import os
import socket
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# --------------------------------------------------------------------------- #
# Entorno ANTES de importar `app` (config.py lee DB_HOST al importarse)        #
# --------------------------------------------------------------------------- #
_SIN_ARCHIVO = str(Path(__file__).parent / "_no_existe_aws")
os.environ["DB_HOST"] = "db.test.invalid"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-2"
os.environ["AWS_CONFIG_FILE"] = _SIN_ARCHIVO
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = _SIN_ARCHIVO
os.environ.pop("AWS_PROFILE", None)

# --------------------------------------------------------------------------- #
# torch / transformers: si no están instalados, se simulan para que las        #
# pruebas rápidas corran igual. Las pruebas de embedder se saltan en ese caso. #
# --------------------------------------------------------------------------- #
try:
    import torch  # noqa: F401
    import transformers  # noqa: F401

    TORCH_REAL = True
except ImportError:
    TORCH_REAL = False
    _torch = types.ModuleType("torch")
    _torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    _transformers = types.ModuleType("transformers")
    _transformers.CLIPModel = type("CLIPModel", (), {})
    _transformers.CLIPProcessor = type("CLIPProcessor", (), {})
    sys.modules.setdefault("torch", _torch)
    sys.modules.setdefault("transformers", _transformers)

RAIZ = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Guardia de red                                                               #
# --------------------------------------------------------------------------- #
_HOSTS_LOCALES = {"127.0.0.1", "::1", "localhost"}
_connect_original = socket.socket.connect


@pytest.fixture(autouse=True)
def sin_red(request, monkeypatch):
    """Falla si una prueba intenta conectarse a un host externo (AWS, Hugging Face...)."""
    if request.node.get_closest_marker("modelo"):
        yield
        return

    def connect_bloqueado(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _HOSTS_LOCALES:
            raise RuntimeError(f"Conexión externa bloqueada en pruebas: {address!r}")
        return _connect_original(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect_bloqueado)
    yield


# --------------------------------------------------------------------------- #
# Fixtures de datos                                                            #
# --------------------------------------------------------------------------- #
def _png(color=(120, 160, 200), tam=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def imagen_png() -> bytes:
    """Bytes de un PNG pequeño generado en memoria."""
    return _png()


@pytest.fixture
def crear_png():
    """Fábrica de PNG con color y tamaño a elección."""
    return _png


# Referencias sintéticas: 3 vectores unitarios de dimensión 4.
REF_MATRIX = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ],
    dtype=np.float32,
)
REF_META = [
    {"id": 10, "id_point": 1, "image_name": "biblioteca_01.png"},
    {"id": 11, "id_point": 2, "image_name": "cafeteria_01.png"},
    {"id": 12, "id_point": 99, "image_name": "sin_nombre_01.png"},  # point_id sin nombre
]
NOMBRES = {1: "Biblioteca", 2: "Cafeteria"}


@pytest.fixture
def store_listo(monkeypatch):
    """Deja model_store cargado con datos sintéticos, sin modelo ni base de datos."""
    import app.model_store as store

    monkeypatch.setattr(store, "_ready", True)
    monkeypatch.setattr(store, "_ref_matrix", REF_MATRIX.copy())
    monkeypatch.setattr(store, "_ref_meta", [dict(m) for m in REF_META])
    monkeypatch.setattr(store, "_location_names", dict(NOMBRES))
    return store


@pytest.fixture
def store_vacio(monkeypatch):
    """model_store sin cargar (estado justo después de importar)."""
    import app.model_store as store

    monkeypatch.setattr(store, "_ready", False)
    monkeypatch.setattr(store, "_ref_matrix", None)
    monkeypatch.setattr(store, "_ref_meta", None)
    monkeypatch.setattr(store, "_location_names", None)
    return store
