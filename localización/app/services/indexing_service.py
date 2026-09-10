import hashlib
from app.models.schemas import ImageMetadata


class IndexingService:
    def __init__(self, embedding, database, geo):
        self.embedding, self.database, self.geo = embedding, database, geo

    def index(self, image, document, image_path):
        parsed = ImageMetadata.model_validate(document)
        m = parsed.metadata
        gps, ref = m.coordinates.gps.model_dump(), m.coordinates.reference.model_dump()
        payload = {'pointId': m.pointId, 'block': m.block, 'floor': m.floor,
                   'gpsLatitude': gps['latitude'], 'gpsLongitude': gps['longitude'],
                   'referenceLatitude': ref['latitude'], 'referenceLongitude': ref['longitude'],
                   'compassHeadingDegrees': m.compassHeadingDegrees, 'compassDirection': m.compassDirection,
                   'imagePath': image_path, 'sourceMetadata': parsed.model_dump(),
                   'gpsError': self.geo.calculate_gps_error(gps, ref)}
        digest = hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
        identity = f'{m.pointId}:{image.size}:{digest}'
        return self.database.upsert(self.embedding.encode(image), payload, identity)
