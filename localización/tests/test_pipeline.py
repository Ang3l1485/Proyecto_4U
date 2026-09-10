import io
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from qdrant_client import QdrantClient
from app.config import Settings
from app.main import Services, create_app
from app.models.schemas import ImageMetadata
from app.services.geo_service import GeoService, angular_difference
from app.services.indexing_service import IndexingService
from app.services.kalman_service import KalmanFilter
from app.services.localization_service import LocalizationService
from app.services.qdrant_service import QdrantService
from app.services.evaluation_service import evaluate, append_csv


@pytest.fixture
def document():
    return json.loads(Path('examples/Biblioteca_001_E.json').read_text())


@pytest.fixture
def stack():
    config = Settings(_env_file=None)
    geo = GeoService(config.origin_latitude, config.origin_longitude)
    database = QdrantService(config, 3, QdrantClient(':memory:'))
    embedding = SimpleNamespace(encode=lambda image: np.array([1., 0., 0.]))
    return Services(IndexingService(embedding, database, geo), LocalizationService(embedding, database, geo, config))


def jpeg():
    stream = io.BytesIO()
    Image.new('RGB', (32, 32), 'red').save(stream, format='JPEG')
    return stream.getvalue()


def test_geo_and_idw(stack, document):
    geo = stack.localizer.geo
    xy = np.array([80., -33.])
    assert np.allclose(geo.to_xy(geo.to_position(xy)), xy)
    assert angular_difference(350, 10) == 20
    stack.indexer.index(Image.open(io.BytesIO(jpeg())), document, 'test.jpg')
    gps = document['metadata']['coordinates']['gps']
    correction = geo.correct(gps, stack.localizer.database.payloads(), stack.localizer.config)
    assert np.linalg.norm(geo.to_xy(correction['correctedGps'])) < 1e-6
    assert correction['neighborsUsed'] == 1
    assert geo.calculate_gps_error(gps, correction['correctedGps'])['error_distance'] > 0


def test_api_index_localize_session_and_validation(stack, document):
    with TestClient(create_app(stack)) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        files = {'image': ('test.jpg', jpeg(), 'image/jpeg'),
                 'metadata': ('test.json', json.dumps(document), 'application/json')}
        first = client.post('/index', files=files)
        assert first.status_code == 200
        assert client.post('/index', files=files).json()['id'] == first.json()['id']
        assert len(list(stack.localizer.database.payloads())) == 1
        data = {**document['metadata']['coordinates']['gps'], 'sessionId': 'walk', 'compassHeadingDegrees': 80}
        response = client.post('/localize', files={'image': ('x.jpg', jpeg())}, data=data)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['visualLocalization']['accepted']
        assert result['visualLocalization']['pointId'] == 'biblioteca_001'
        previous = stack.localizer.sessions['walk'][0]
        assert client.post('/localize', files={'image': ('x.jpg', jpeg())}, data=data).status_code == 200
        assert stack.localizer.sessions['walk'][0] is previous
        client.post('/localize', files={'image': ('x.jpg', jpeg())}, data={**data, 'sessionId': 'other'})
        assert stack.localizer.sessions['other'][0] is not previous
        assert client.post('/localize', files={'image': ('x.jpg', b'bad')}, data=data).status_code == 422
        assert client.post('/localize', files={'image': ('x.jpg', jpeg())}, data={**data, 'gpsAccuracyMeters': -1}).status_code == 422
        del document['metadata']['coordinates']['reference']
        files['metadata'] = ('test.json', json.dumps(document), 'application/json')
        assert 'reference' in client.post('/index', files=files).text


def test_empty_and_distance_rejection(stack, document):
    gps = document['metadata']['coordinates']['gps']
    image = Image.open(io.BytesIO(jpeg()))
    assert stack.localizer.localize(image, gps)['visualLocalization'] is None
    stack.indexer.index(image, document, 'test.jpg')
    result = stack.localizer.localize(image, {'latitude': 6.21, 'longitude': -75.57})
    assert result['vprRejectionReason'] == 'gps_disagreement'
    assert not result['visualLocalization']['accepted']
    assert result['kalman'] == result['gpsCorrected']


def test_grouping_heading_and_low_similarity(stack):
    def hit(point, score, heading, dx):
        position = stack.localizer.geo.to_position([dx, 0])
        return SimpleNamespace(score=score, payload={'pointId': point, 'block': point,
            'referenceLatitude': position['latitude'], 'referenceLongitude': position['longitude'],
            'compassHeadingDegrees': heading})
    database = SimpleNamespace(search=lambda vector, k: [hit('a', .9, 180, 20), hit('b', .88, 0, 0)], payloads=lambda: [])
    stack.localizer.database = database
    gps = stack.localizer.geo.to_position([0, 0])
    assert stack.localizer.localize(None, gps, heading=0)['visualLocalization']['pointId'] == 'b'
    database.search = lambda vector, k: [hit('a', .9, 0, 20), hit('b', .8, 0, 0), hit('b', .8, 0, 0)]
    result = stack.localizer.localize(None, gps)
    assert result['visualLocalization']['pointId'] == 'a'
    assert np.allclose(stack.localizer.geo.to_xy(result['visualLocalization']), [20, 0])
    database.search = lambda vector, k: [hit('a', .69, 0, 20)]
    assert stack.localizer.localize(None, gps)['vprRejectionReason'] == 'low_similarity'


def test_kalman_and_metrics(tmp_path):
    kalman = KalmanFilter([0, 0], 8)
    kalman.predict(1)
    kalman.update_gps([10, 0], 8)
    before = kalman.state[0]
    kalman.update_vpr([10, 0], 2)
    assert before < kalman.state[0] < 10
    assert np.all(np.linalg.eigvalsh(kalman.covariance) > 0)
    geo = GeoService(6.2, -75.5)
    reference = geo.to_position([0, 0])
    result = dict(gps=geo.to_position([3, 4]), gpsCorrected=reference, visualLocalization=None, kalman=reference)
    metrics = evaluate(result, reference, geo)
    assert metrics['gpsErrorMeters'] == pytest.approx(5)
    assert metrics['vprErrorMeters'] is None
    path = tmp_path / 'results.csv'
    append_csv(path, metrics)
    append_csv(path, metrics)
    assert len(path.read_text().splitlines()) == 3


@pytest.mark.parametrize('key', ['pointId', 'compassHeadingDegrees'])
def test_required_fields(document, key):
    del document['metadata'][key]
    with pytest.raises(ValueError, match=key):
        ImageMetadata.model_validate(document)


def test_configuration_rejects_invalid_noise():
    with pytest.raises(ValueError, match='VPR_THRESHOLDS'):
        Settings(_env_file=None, vpr_thresholds=[(.9, -2)])


def test_negative_heading_from_mobile_app_is_normalized(document):
    document['metadata']['compassHeadingDegrees'] = -112.22571810145563
    parsed = ImageMetadata.model_validate(document)
    assert parsed.metadata.compassHeadingDegrees == pytest.approx(247.77428189854437)


def test_idw_radius_and_duplicate_views(stack, document):
    image = Image.open(io.BytesIO(jpeg()))
    stack.indexer.index(image, document, 'test.jpg')
    payload = next(stack.localizer.database.payloads())
    gps = document['metadata']['coordinates']['gps']
    correction = stack.localizer.geo.correct(gps, [payload] * 10, stack.localizer.config)
    assert correction['neighborsUsed'] == 1
    distant = stack.localizer.geo.correct({'latitude': 6.3, 'longitude': -75.5}, [payload], stack.localizer.config)
    assert distant['neighborsUsed'] == 0
    assert distant['estimatedBias'] == {'x': 0., 'y': 0.}
