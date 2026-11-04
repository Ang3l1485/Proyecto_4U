"""
model_store.py -- Singleton that holds the CLIP model and reference
embedding matrix in RAM. Loaded ONCE at FastAPI startup, reused for
every request with zero DB/model reload overhead.
"""

import logging
from threading import Lock

import numpy as np

from app.db       import fetch_reference_embeddings, fetch_location_names
from app.embedder import _load_model

logger = logging.getLogger(__name__)

_lock            = Lock()
_ready           = False
_ref_matrix: np.ndarray | None = None   # shape (N, 512)
_ref_meta:   list[dict]  | None = None  # [{id, id_point, image_name}, ...]
_location_names: dict[int, str] | None = None


def load() -> None:
    """
    Load everything into RAM. Call once at application startup.
    Thread-safe; subsequent calls are no-ops.
    """
    global _ready, _ref_matrix, _ref_meta, _location_names

    with _lock:
        if _ready:
            return

        logger.info("=== Model store: loading CLIP model ===")
        _load_model()

        logger.info("=== Model store: loading reference embeddings from DB ===")
        _ref_matrix, _ref_meta = fetch_reference_embeddings()
        logger.info("Reference matrix: %s", _ref_matrix.shape)

        logger.info("=== Model store: loading location names from DB ===")
        _location_names = fetch_location_names()
        logger.info("Locations loaded: %d", len(_location_names))

        _ready = True
        logger.info("=== Model store ready. Will serve requests. ===")


def is_ready() -> bool:
    return _ready


def get_ref_matrix() -> np.ndarray:
    return _ref_matrix


def get_ref_meta() -> list[dict]:
    return _ref_meta


def get_location_names() -> dict[int, str]:
    return _location_names