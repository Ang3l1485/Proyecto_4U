import numpy as np


class KalmanFilter:
    def __init__(self, xy, sigma, acceleration_sigma=2):
        self.state = np.array([*xy, 0., 0.], dtype=float)
        self.covariance = np.diag([sigma ** 2, sigma ** 2, 25., 25.])
        self.acceleration_sigma = acceleration_sigma

    def predict(self, dt):
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt debe ser finito y no negativo')
        f = np.eye(4)
        f[0, 2] = f[1, 3] = dt
        g = np.array([[dt ** 2 / 2, 0], [0, dt ** 2 / 2], [dt, 0], [0, dt]])
        self.state = f @ self.state
        self.covariance = f @ self.covariance @ f.T + g @ g.T * self.acceleration_sigma ** 2

    def _update(self, xy, sigma):
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError('sigma debe ser positiva y finita')
        h = np.eye(2, 4)
        r = np.eye(2) * sigma ** 2
        s = h @ self.covariance @ h.T + r
        k = np.linalg.solve(s, h @ self.covariance).T
        self.state += k @ (np.asarray(xy) - h @ self.state)
        a = np.eye(4) - k @ h
        self.covariance = a @ self.covariance @ a.T + k @ r @ k.T

    def update_gps(self, xy, sigma):
        self._update(xy, sigma)

    def update_vpr(self, xy, sigma):
        self._update(xy, sigma)
