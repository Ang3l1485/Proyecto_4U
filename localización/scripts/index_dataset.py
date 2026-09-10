import argparse
import logging
from pathlib import Path
import sys
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.schemas import ImageMetadata


def main():
    parser = argparse.ArgumentParser(description='Indexa pares JPG + JSON a través de FastAPI')
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] / 'dataset')
    parser.add_argument('--url', default='http://localhost:8000')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if not args.dataset.is_dir():
        parser.error(f'No existe la carpeta {args.dataset}')
    files = list(args.dataset.rglob('*'))
    images = [p for p in files if p.suffix.lower() in ('.jpg', '.jpeg')]
    sidecars = {str(p.with_suffix('')).lower(): p for p in files if p.suffix.lower() == '.json'}
    image_keys = {str(p.with_suffix('')).lower() for p in images}
    errors = 0
    for key, path in sidecars.items():
        if key not in image_keys:
            logging.error('Falta imagen JPG para %s', path)
            errors += 1
    if not images:
        logging.error('No hay imágenes JPG en %s', args.dataset)
        return 1
    indexed = 0
    with requests.Session() as session:
        for image in sorted(images):
            metadata = sidecars.get(str(image.with_suffix('')).lower())
            try:
                if metadata is None:
                    raise ValueError(f'Falta JSON para {image}')
                ImageMetadata.model_validate_json(metadata.read_text(encoding='utf-8-sig'))
                with image.open('rb') as photo, metadata.open('rb') as document:
                    response = session.post(args.url.rstrip('/') + '/index',
                        files={'image': (image.name, photo, 'image/jpeg'),
                               'metadata': (metadata.name, document, 'application/json')}, timeout=180)
                if not response.ok:
                    raise ValueError(f'HTTP {response.status_code}: {response.text}')
                indexed += 1
                logging.info('Indexada: %s', image.name)
            except (OSError, ValueError, requests.RequestException) as exc:
                errors += 1
                logging.error('%s: %s', image, exc)
    logging.info('Final: %s indexadas, %s errores', indexed, errors)
    return int(errors > 0)


if __name__ == '__main__':
    sys.exit(main())
