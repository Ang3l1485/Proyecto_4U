import io
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from app.config import settings
from app.models.schemas import Position
from app.services.embedding_service import EmbeddingService
from app.services.geo_service import GeoService
from app.services.indexing_service import IndexingService
from app.services.localization_service import LocalizationService
from app.services.qdrant_service import QdrantService

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class Services:
    indexer: IndexingService
    localizer: LocalizationService


def build_services():
    logger.info('Cargando DINOv2 y conectando Qdrant...')
    embedding = EmbeddingService(settings)
    database = QdrantService(settings, embedding.dimension)
    geo = GeoService(settings.origin_latitude, settings.origin_longitude)
    return Services(IndexingService(embedding, database, geo), LocalizationService(embedding, database, geo, settings))


async def read_upload(upload, limit):
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, 'Archivo demasiado grande')
    return data


def load_image(data):
    try:
        image = Image.open(io.BytesIO(data))
        if image.format != 'JPEG':
            raise ValueError('Se requiere una imagen JPG/JPEG')
        image.load()
        return image
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, f'Imagen no válida: {exc}') from exc


def create_app(services=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.services = services or await run_in_threadpool(build_services)
        yield

    app = FastAPI(title='Localización visual del campus', lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/index')
    async def index(image: Annotated[UploadFile, File()], metadata: Annotated[UploadFile, File()]):
        photo = load_image(await read_upload(image, settings.max_upload_bytes))
        try:
            document = json.loads(await read_upload(metadata, 1000000))
            identifier = await run_in_threadpool(app.state.services.indexer.index, photo, document,
                                                 Path(image.filename or 'upload.jpg').name)
            return {'status': 'indexed', 'id': identifier}
        except (ValidationError, ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, f'Metadatos no válidos; verifique pointId, gps, reference y heading: {exc}') from exc

    @app.post('/localize')
    async def localize(image: Annotated[UploadFile, File()],
                       latitude: Annotated[float, Form(ge=-90, le=90)],
                       longitude: Annotated[float, Form(ge=-180, le=180)],
                       compassHeadingDegrees: Annotated[float | None, Form(ge=0, lt=360)] = None,
                       gpsAccuracyMeters: Annotated[float | None, Form(gt=0, le=10000)] = None,
                       sessionId: Annotated[str | None, Form(min_length=1, max_length=128)] = None):
        photo = load_image(await read_upload(image, settings.max_upload_bytes))
        gps = Position(latitude=latitude, longitude=longitude).model_dump()
        return await run_in_threadpool(app.state.services.localizer.localize, photo, gps,
                                       compassHeadingDegrees, gpsAccuracyMeters, sessionId)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        from fastapi.responses import JSONResponse
        logger.exception('Error procesando %s', request.url.path, exc_info=exc)
        return JSONResponse(status_code=503, content={'detail': 'No se pudo procesar la operación. Revise Qdrant y los logs del servidor.'})

    return app


app = create_app()
