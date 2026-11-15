"""Constant-velocity Kalman filter over a box state (cx, cy, aspect, height) plus velocities.

Independent implementation written from the standard linear Kalman equations (predict: x=Fx, P=FPF'+Q;
update: K=PH'(HPH'+R)^-1). The 1/20 and 1/160 noise weights are the widely published ByteTrack/DeepSORT
tuning constants (numbers, not code). Not copied from any other project. Needs only numpy.
"""
import numpy as np


class KalmanFilterXYAH:
    def __init__(self):
        n = 4
        self.F = np.eye(2 * n)
        for i in range(n):
            self.F[i, n + i] = 1.0  # position += velocity (dt = 1 frame)
        self.H = np.eye(n, 2 * n)
        self._w_pos, self._w_vel = 1.0 / 20, 1.0 / 160

    def initiate(self, measurement):
        mean = np.r_[measurement, np.zeros(4)]
        h = measurement[3]
        std = [2 * self._w_pos * h, 2 * self._w_pos * h, 1e-2, 2 * self._w_pos * h,
               10 * self._w_vel * h, 10 * self._w_vel * h, 1e-5, 10 * self._w_vel * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean, covariance):
        h = mean[3]
        std = [self._w_pos * h, self._w_pos * h, 1e-2, self._w_pos * h,
               self._w_vel * h, self._w_vel * h, 1e-5, self._w_vel * h]
        q = np.diag(np.square(std))
        return self.F @ mean, self.F @ covariance @ self.F.T + q

    def project(self, mean, covariance):
        h = mean[3]
        std = [self._w_pos * h, self._w_pos * h, 1e-1, self._w_pos * h]
        r = np.diag(np.square(std))
        return self.H @ mean, self.H @ covariance @ self.H.T + r

    def update(self, mean, covariance, measurement):
        pm, pc = self.project(mean, covariance)
        gain = np.linalg.solve(pc, (covariance @ self.H.T).T).T  # K = P H' S^-1
        new_mean = mean + gain @ (measurement - pm)
        new_cov = covariance - gain @ pc @ gain.T
        return new_mean, new_cov
