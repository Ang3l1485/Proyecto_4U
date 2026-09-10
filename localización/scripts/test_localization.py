import argparse
import json
from pathlib import Path
import sys
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.evaluation_service import append_csv, evaluate
from app.services.geo_service import GeoService
from app.models.schemas import ImageMetadata, Position


def main():
    parser = argparse.ArgumentParser(description='Prueba localización y exporta errores en metros')
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--metadata', type=Path,
                        help='JSON generado por la app; toma GPS, heading, sessionId y referencia automáticamente')
    parser.add_argument('--latitude', type=float)
    parser.add_argument('--longitude', type=float)
    parser.add_argument('--heading', type=float)
    parser.add_argument('--gps-accuracy', type=float)
    parser.add_argument('--session-id')
    parser.add_argument('--reference-latitude', type=float)
    parser.add_argument('--reference-longitude', type=float)
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--url', default='http://localhost:8000')
    args = parser.parse_args()
    if args.metadata:
        try:
            captured = ImageMetadata.model_validate_json(args.metadata.read_text(encoding='utf-8-sig')).metadata
        except (OSError, ValueError) as exc:
            parser.error(f'No se pudo leer el JSON de metadatos: {exc}')
        args.latitude = args.latitude if args.latitude is not None else captured.coordinates.gps.latitude
        args.longitude = args.longitude if args.longitude is not None else captured.coordinates.gps.longitude
        args.heading = args.heading if args.heading is not None else captured.compassHeadingDegrees
        args.session_id = args.session_id or getattr(captured, 'sessionId', None)
        args.reference_latitude = (args.reference_latitude if args.reference_latitude is not None
                                   else captured.coordinates.reference.latitude)
        args.reference_longitude = (args.reference_longitude if args.reference_longitude is not None
                                    else captured.coordinates.reference.longitude)
    if args.latitude is None or args.longitude is None:
        parser.error('Use --metadata o proporcione --latitude y --longitude')
    if (args.reference_latitude is None) != (args.reference_longitude is None):
        parser.error('Proporcione ambas coordenadas de referencia')
    data = {'latitude': args.latitude, 'longitude': args.longitude,
            'compassHeadingDegrees': args.heading, 'gpsAccuracyMeters': args.gps_accuracy, 'sessionId': args.session_id}
    try:
        with args.image.open('rb') as photo:
            response = requests.post(args.url.rstrip('/') + '/localize',
                files={'image': (args.image.name, photo, 'image/jpeg')},
                data={k: v for k, v in data.items() if v is not None}, timeout=180)
        if not response.ok:
            raise ValueError(f'HTTP {response.status_code}: {response.text}')
        result = response.json()
        for label, key in [('GPS original', 'gps'), ('GPS corregido', 'gpsCorrected'),
                           ('Ubicación VPR, confianza y punto reconocido', 'visualLocalization'),
                           ('Ubicación Kalman', 'kalman'), ('Top-K coincidencias', 'matches'), ('Sesión', 'sessionId')]:
            print(f'{label}: {json.dumps(result[key], ensure_ascii=False, indent=2)}')
        metrics = dict.fromkeys(['gpsErrorMeters', 'correctedErrorMeters', 'vprErrorMeters', 'kalmanErrorMeters'])
        if args.reference_latitude is not None:
            reference = Position(latitude=args.reference_latitude, longitude=args.reference_longitude).model_dump()
            metrics = evaluate(result, reference, GeoService(**reference))
            print('Errores en metros:', json.dumps(metrics, indent=2))
        if args.csv:
            append_csv(args.csv, {'image': str(args.image), 'sessionId': result['sessionId'], **metrics,
                                 'resultJson': json.dumps(result, ensure_ascii=False)})
    except (OSError, ValueError, requests.RequestException) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
