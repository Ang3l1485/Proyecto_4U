# ============================================================
# Build stage
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /install

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install/pkg -r requirements.txt

# Pre-download CLIP model weights into the image at build time.
# This means the container starts instantly — no HuggingFace download at runtime.
ENV PYTHONPATH=/install/pkg/lib/python3.11/site-packages
RUN HF_HOME=/install/hf_cache \
    python -c "from transformers import CLIPModel, CLIPProcessor; \
               CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); \
               CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); \
               print('CLIP model cached.')"

# ============================================================
# Runtime stage
# ============================================================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

COPY --from=builder /install/pkg      /usr/local
COPY --from=builder /install/hf_cache /home/appuser/.cache/huggingface

COPY app/ ./app/

# HuggingFace reads from this cache dir — already populated at build time
ENV HF_HOME=/home/appuser/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface

USER appuser

EXPOSE 8080

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]