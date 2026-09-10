import math
import numpy as np


def angular_difference(a, b):
    return abs((a - b + 180) % 360 - 180)


class GeoService:
    """Proyección equirectangular local; X este, Y norte, metros."""
    def __init__(self, latitude, longitude):
        self.lat, self.lon = latitude, longitude
        self.scale = math.cos(math.radians(latitude))

    def to_xy(self, position):
        return np.array([math.radians(position['longitude'] - self.lon) * self.scale,
                         math.radians(position['latitude'] - self.lat)]) * 6371008.8

    def to_position(self, xy):
        return {'latitude': self.lat + math.degrees(xy[1] / 6371008.8),
                'longitude': self.lon + math.degrees(xy[0] / (6371008.8 * self.scale))}

    def calculate_gps_error(self, gps_position, reference_position):
        error = self.to_xy(gps_position) - self.to_xy(reference_position)
        return {'error_x': float(error[0]), 'error_y': float(error[1]),
                'error_distance': float(np.linalg.norm(error))}

    def correct(self, gps, payloads, config):
        xy = self.to_xy(gps)
        # Una contribución por punto físico; promedia sus capturas históricas.
        groups = {}
        for p in payloads:
            measured = self.to_xy({'latitude': p['gpsLatitude'], 'longitude': p['gpsLongitude']})
            reference = self.to_xy({'latitude': p['referenceLatitude'], 'longitude': p['referenceLongitude']})
            groups.setdefault(p['pointId'], []).append((measured, reference - measured))
        neighbors = []
        for rows in groups.values():
            measured, bias = np.mean(np.asarray(rows), axis=0)
            distance = float(np.linalg.norm(measured - xy))
            if distance <= config.idw_radius:
                neighbors.append((distance, bias))
        neighbors.sort(key=lambda row: row[0])
        neighbors = neighbors[:config.idw_neighbors]
        bias = np.zeros(2)
        if neighbors:
            bias = np.average([n[1] for n in neighbors], axis=0,
                              weights=[1 / (n[0] ** 2 + config.idw_epsilon) for n in neighbors])
        return {'originalGps': gps, 'estimatedBias': {'x': float(bias[0]), 'y': float(bias[1])},
                'correctedGps': self.to_position(xy + bias), 'neighborsUsed': len(neighbors)}


def calculate_gps_error(gps_position, reference_position):
    return GeoService(reference_position['latitude'], reference_position['longitude']).calculate_gps_error(
        gps_position, reference_position)
