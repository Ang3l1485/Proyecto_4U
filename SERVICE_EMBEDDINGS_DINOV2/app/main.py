"""
main.py -- FastAPI service for CLIP image similarity.

Startup: loads CLIP model + all reference embeddings from DB into RAM.
POST /predict: receives an image, returns the closest location in ~300ms.
GET  /health:  used by ECS health checks.
"""

import io
import logging
import sys

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

import app.model_store as store
from app.embedder import embed_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="CLIP Location Similarity API")


@app.on_event("startup")
def startup():
    """Load model and DB embeddings once. All requests reuse this."""
    store.load()


@app.get("/health")
def health():
    return {"status": "ok", "ready": store.is_ready()}


@app.post("/predict")
async def predict(image: UploadFile = File(...)):
    """
    Receive an image file, return the closest matching location.

    Returns JSON:
    {
      "location":          "Cafeteria",
      "point_id":          3,
      "similarity":        0.94,
      "matched_ref_image": "cafeteria_ref_01.png"
    }
    """
    if not store.is_ready():
        raise HTTPException(status_code=503, detail="Model not ready yet")

    # Read uploaded image
    contents = await image.read()
    try:
        pil_image = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Embed query image
    query_vec = embed_image(pil_image)                         # (512,)

    # Cosine similarity against full reference matrix (dot product)
    ref_matrix     = store.get_ref_matrix()                    # (N, 512)
    similarities   = ref_matrix @ query_vec                    # (N,)
    best_idx       = int(np.argmax(similarities))
    best_sim       = float(similarities[best_idx])

    best           = store.get_ref_meta()[best_idx]
    point_id       = best["id_point"]
    location_name  = store.get_location_names().get(point_id, "Unknown")

    logger.info(
        "Predicted: %s (point_id=%s, sim=%.4f) for file=%s",
        location_name, point_id, best_sim, image.filename,
    )

    return JSONResponse({
        "location":          location_name,
        "point_id":          point_id,
        "similarity":        round(best_sim, 4),
        "matched_ref_image": best["image_name"],
    })