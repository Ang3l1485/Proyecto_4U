"""Prueba técnica opcional con pesos reales y una imagen sintética; no evalúa VPR."""
from pathlib import Path
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services.embedding_service import EmbeddingService


if __name__ == '__main__':
    service = EmbeddingService(settings)
    image = Image.fromarray(np.random.default_rng(0).integers(0, 256, (224, 224, 3), dtype=np.uint8))
    vector = service.encode(image)
    assert vector.shape == (service.dimension,)
    assert np.isfinite(vector).all()
    assert np.isclose(np.linalg.norm(vector), 1, atol=1e-5)
    print(f'DINOv2 OK: dispositivo={service.device}, dimensiones={vector.size}, norma={np.linalg.norm(vector):.6f}')
