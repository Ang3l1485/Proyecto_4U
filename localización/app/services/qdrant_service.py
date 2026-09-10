import uuid
from qdrant_client import QdrantClient, models


class QdrantService:
    def __init__(self, config, dimension, client=None):
        self.client = client if client is not None else QdrantClient(url=config.qdrant_url, timeout=30)
        self.collection = config.collection
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=dimension, distance=models.Distance.COSINE))
        params = self.client.get_collection(self.collection).config.params.vectors
        if not isinstance(params, models.VectorParams) or params.size != dimension or params.distance != models.Distance.COSINE:
            raise ValueError('Colección incompatible: cree otra colección para este modelo')

    def upsert(self, vector, payload, identity):
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        self.client.upsert(self.collection, points=[models.PointStruct(
            id=identifier, vector=vector.tolist(), payload=payload)], wait=True)
        return identifier

    def search(self, vector, top_k=10):
        return self.client.query_points(self.collection, query=vector.tolist(), limit=top_k,
                                        with_payload=True).points

    def payloads(self):
        offset = None
        while True:
            points, offset = self.client.scroll(self.collection, limit=256, offset=offset,
                                                 with_payload=True, with_vectors=False)
            for point in points:
                yield point.payload
            if offset is None:
                break
