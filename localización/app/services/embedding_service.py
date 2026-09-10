import threading
import numpy as np
from PIL import ImageOps


class EmbeddingService:
    def __init__(self, config):
        import torch
        from transformers import AutoImageProcessor, AutoModel
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.processor = AutoImageProcessor.from_pretrained(config.model_id, revision=config.model_revision, use_fast=False)
        self.model = AutoModel.from_pretrained(config.model_id, revision=config.model_revision).to(self.device).eval()
        self.dimension = self.model.config.hidden_size
        self.lock = threading.Lock()

    def encode(self, image):
        with self.lock, self.torch.inference_mode():
            inputs = self.processor(images=ImageOps.exif_transpose(image).convert('RGB'), return_tensors='pt')
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            vector = self.model(**inputs).last_hidden_state[0, 0].cpu().numpy().astype(np.float32)
            norm = np.linalg.norm(vector)
            if not np.isfinite(norm) or norm == 0:
                raise ValueError('Embedding no válido')
            return vector / norm
