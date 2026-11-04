"""
embedder.py -- Load CLIP and embed PIL images into L2-normalised vectors.
"""

import logging

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from app import config

logger = logging.getLogger(__name__)

_model: CLIPModel | None = None
_processor: CLIPProcessor | None = None
_device: str = "cpu"


def _load_model() -> None:
    global _model, _processor, _device
    if _model is not None:
        return
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading CLIP model '%s' onto %s ...", config.CLIP_MODEL_ID, _device)
    _model = CLIPModel.from_pretrained(config.CLIP_MODEL_ID).to(_device)
    _processor = CLIPProcessor.from_pretrained(config.CLIP_MODEL_ID)
    logger.info("CLIP model loaded.")


def embed_image(image: Image.Image) -> np.ndarray:
    """
    Embed a PIL Image with CLIP and return an L2-normalised float32 vector.
    Returns np.ndarray of shape (512,), dtype float32.

    Uses the vision model + projection layer directly instead of
    get_image_features(), which returns different types across
    transformers versions.
    """
    _load_model()

    inputs = _processor(images=image.convert("RGB"), return_tensors="pt")
    pixel_values = inputs["pixel_values"].to(_device)

    with torch.no_grad():
        # vision_model always returns BaseModelOutputWithPooling —
        # .pooler_output is the [CLS] token: shape (batch, hidden_size)
        vision_out = _model.vision_model(pixel_values=pixel_values)
        pooled = vision_out.pooler_output                 # (1, 768)

        # visual_projection maps hidden_size → embed_dim (512)
        features = _model.visual_projection(pooled)       # (1, 512)

    # L2-normalise to unit sphere so dot product == cosine similarity
    norms = torch.linalg.norm(features, dim=-1, keepdim=True).clamp_min(1e-8)
    vec = (features / norms).cpu().numpy().squeeze(0)     # (512,)
    return vec.astype(np.float32)