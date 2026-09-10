import threading
import time
import uuid
import numpy as np
from app.services.geo_service import angular_difference
from app.services.kalman_service import KalmanFilter


class LocalizationService:
    def __init__(self, embedding, database, geo, config):
        self.embedding, self.database, self.geo, self.config = embedding, database, geo, config
        self.sessions = {}
        self.lock = threading.Lock()

    def localize(self, image, gps, heading=None, accuracy=None, session_id=None):
        c = self.config
        hits = self.database.search(self.embedding.encode(image), c.top_k)
        matches, groups = [], {}
        for hit in hits:
            p = hit.payload
            similarity = float(np.clip(hit.score, -1, 1))
            score = similarity if heading is None else ((1 - c.heading_weight) * similarity +
                    c.heading_weight * (1 - angular_difference(heading, p['compassHeadingDegrees']) / 180))
            match = {key: p[key] for key in ('pointId', 'block', 'referenceLatitude', 'referenceLongitude')}
            match.update(similarity=similarity, finalScore=score, heading=p['compassHeadingDegrees'])
            matches.append(match)
            groups.setdefault(p['pointId'], []).append(match)
        matches.sort(key=lambda m: m['finalScore'], reverse=True)
        correction = self.geo.correct(gps, self.database.payloads(), c)
        corrected_xy = self.geo.to_xy(correction['correctedGps'])
        visual, visual_xy, sigma = None, None, None
        reason = 'no_matches'
        if groups:
            # Media de scores: evita favorecer puntos con más fotografías.
            winner = max(groups.values(), key=lambda rows: np.mean([r['finalScore'] for r in rows]))
            weights = np.array([max(r['similarity'], 0) for r in winner])
            if weights.sum() == 0:
                weights = np.ones(len(winner))
            positions = [self.geo.to_xy({'latitude': r['referenceLatitude'], 'longitude': r['referenceLongitude']}) for r in winner]
            visual_xy = np.average(positions, axis=0, weights=weights)
            confidence = float(np.average([r['similarity'] for r in winner], weights=weights))
            distance = float(np.linalg.norm(visual_xy - corrected_xy))
            for threshold, noise in sorted(c.vpr_thresholds, reverse=True):
                if confidence >= threshold:
                    sigma = noise
                    break
            reason = 'low_similarity' if sigma is None else ('gps_disagreement' if distance > c.max_vpr_distance else None)
            visual = {**self.geo.to_position(visual_xy), 'confidence': confidence,
                      'pointId': winner[0]['pointId'], 'block': winner[0]['block'],
                      'accepted': reason is None, 'rejectionReason': reason, 'distanceToGpsMeters': distance}
        session_id = session_id or str(uuid.uuid4())
        gps_sigma = accuracy if accuracy is not None else c.gps_sigma
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items() if now - value[1] < c.session_ttl}
            if session_id in self.sessions:
                kalman, last = self.sessions[session_id]
                kalman.predict(now - last)
                kalman.update_gps(corrected_xy, gps_sigma)
            else:
                if len(self.sessions) >= c.max_sessions:
                    del self.sessions[min(self.sessions, key=lambda key: self.sessions[key][1])]
                kalman = KalmanFilter(corrected_xy, gps_sigma, c.acceleration_sigma)
            if reason is None:
                kalman.update_vpr(visual_xy, sigma)
            self.sessions[session_id] = (kalman, now)
            fused = self.geo.to_position(kalman.state[:2])
        return {'sessionId': session_id, 'gps': gps, 'gpsCorrected': correction['correctedGps'],
                'gpsCorrection': correction, 'visualLocalization': visual, 'vprRejectionReason': reason,
                'kalman': fused, 'matches': matches}
