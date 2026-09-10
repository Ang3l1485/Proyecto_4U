import csv
from pathlib import Path


def evaluate(result, reference, geo):
    return {name: None if result[key] is None else geo.calculate_gps_error(result[key], reference)['error_distance']
            for name, key in [('gpsErrorMeters', 'gps'), ('correctedErrorMeters', 'gpsCorrected'),
                              ('vprErrorMeters', 'visualLocalization'), ('kalmanErrorMeters', 'kalman')]}


def append_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open('a', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
