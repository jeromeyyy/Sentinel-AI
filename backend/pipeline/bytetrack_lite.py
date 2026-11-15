"""Torch-free ByteTrack (Zhang et al., ECCV 2022) using the XYAH Kalman filter copied from Ultralytics.

Same algorithm and default thresholds as ultralytics' BYTETracker (two-stage association: high-score
detections first, then low-score ones against the still-unmatched tracks; score-fused IoU cost; lost-track
buffer). It is an independent compact port, not a byte-for-byte copy, so IDs can differ slightly from
ultralytics on the same input; tests/test_bytetrack_lite.py checks it on synthetic motion only.
Needs only numpy and lap(x)."""
from typing import List

import numpy as np

from .kalman_xyah import KalmanFilterXYAH

try:
    import lap
except ImportError:  # pragma: no cover
    lap = None

NEW, TRACKED, LOST, REMOVED = 0, 1, 2, 3


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)), np.float32)
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0]); iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2]); iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return (inter / (aa[:, None] + ab[None, :] - inter + 1e-9)).astype(np.float32)


def _assign(cost: np.ndarray, thresh: float):
    if cost.size == 0:
        return [], list(range(cost.shape[0])), list(range(cost.shape[1]))
    x, y = lap.lapjv(cost, extend_cost=True, cost_limit=thresh, return_cost=False)
    matches = [[i, int(m)] for i, m in enumerate(x) if m >= 0]
    return matches, [int(i) for i in np.where(x < 0)[0]], [int(i) for i in np.where(y < 0)[0]]


class _Track:
    def __init__(self, xyxy, score, cls):
        x1, y1, x2, y2 = [float(v) for v in xyxy]
        self.tlwh = np.array([x1, y1, x2 - x1, y2 - y1], np.float64)
        self.score, self.cls = float(score), int(cls)
        self.mean = self.cov = None
        self.state, self.is_activated, self.tid = NEW, False, 0
        self.start_frame = self.end_frame = 0

    @staticmethod
    def _xyah(tlwh):
        return np.array([tlwh[0] + tlwh[2] / 2, tlwh[1] + tlwh[3] / 2, tlwh[2] / max(tlwh[3], 1e-6), tlwh[3]])

    @property
    def xyxy(self):
        if self.mean is None:
            t = self.tlwh
        else:
            cx, cy, a, h = self.mean[:4]
            t = np.array([cx - a * h / 2, cy - h / 2, a * h, h])
        return np.array([t[0], t[1], t[0] + t[2], t[1] + t[3]])

    def predict(self, kf):
        m = self.mean.copy()
        if self.state != TRACKED:
            m[7] = 0
        self.mean, self.cov = kf.predict(m, self.cov)

    def activate(self, kf, frame, tid):
        self.tid = tid
        self.mean, self.cov = kf.initiate(self._xyah(self.tlwh))
        self.state, self.is_activated = TRACKED, frame == 1
        self.start_frame = self.end_frame = frame

    def update(self, det, kf, frame, reactivate=False):
        self.mean, self.cov = kf.update(self.mean, self.cov, self._xyah(det.tlwh))
        self.state, self.is_activated = TRACKED, True
        self.score, self.cls, self.end_frame = det.score, det.cls, frame


class ByteTrackLite:
    def __init__(self, frame_rate=30, track_high_thresh=0.35, track_low_thresh=0.1, new_track_thresh=0.4,
                 track_buffer=30, match_thresh=0.8, fuse_score=True):
        self.hi, self.lo, self.new_thr, self.match_thr, self.fuse = track_high_thresh, track_low_thresh, new_track_thresh, match_thresh, fuse_score
        self.max_lost = int(frame_rate / 30.0 * track_buffer)
        self.kf = KalmanFilterXYAH()
        self.tracked: List[_Track] = []; self.lost: List[_Track] = []
        self.frame = 0; self._next_id = 1

    def _cost(self, tracks, dets):
        c = 1 - _iou(np.array([t.xyxy for t in tracks]).reshape(-1, 4), np.array([d.xyxy for d in dets]).reshape(-1, 4))
        if self.fuse and c.size:
            c = 1 - (1 - c) * np.array([d.score for d in dets])[None, :]
        return c

    def update(self, xyxy, conf, cls) -> np.ndarray:
        """Returns rows [x1, y1, x2, y2, id, conf, cls] for activated tracks (same layout as ultralytics)."""
        self.frame += 1
        xyxy = np.asarray(xyxy, np.float32).reshape(-1, 4); conf = np.asarray(conf, np.float32); cls = np.asarray(cls)
        dets = [_Track(b, s, c) for b, s, c in zip(xyxy, conf, cls)]
        high = [d for d in dets if d.score >= self.hi]
        low = [d for d in dets if self.lo < d.score < self.hi]
        unconfirmed = [t for t in self.tracked if not t.is_activated]
        tracked = [t for t in self.tracked if t.is_activated]
        pool = {id(t): t for t in tracked + self.lost}; pool = list(pool.values())
        for t in pool:
            t.predict(self.kf)
        m, u_t, u_d = _assign(self._cost(pool, high), self.match_thr)
        for it, idt in m:
            pool[it].update(high[idt], self.kf, self.frame)
        rem = [pool[i] for i in u_t if pool[i].state == TRACKED]
        m2, u_t2, _ = _assign(1 - _iou(np.array([t.xyxy for t in rem]).reshape(-1, 4), np.array([d.xyxy for d in low]).reshape(-1, 4)), 0.5)
        for it, idt in m2:
            rem[it].update(low[idt], self.kf, self.frame)
        for i in u_t2:
            rem[i].state = LOST
        left = [high[i] for i in u_d]
        for t in unconfirmed:
            t.predict(self.kf)
        m3, u_unc, u_d3 = _assign(self._cost(unconfirmed, left), 0.7)
        for it, idt in m3:
            unconfirmed[it].update(left[idt], self.kf, self.frame)
        for i in u_unc:
            unconfirmed[i].state = REMOVED
        for i in u_d3:
            d = left[i]
            if d.score >= self.new_thr:
                d.activate(self.kf, self.frame, self._next_id); self._next_id += 1
                self.tracked.append(d)
        everyone = {id(t): t for t in self.tracked + self.lost + pool + unconfirmed}.values()
        self.tracked = [t for t in everyone if t.state == TRACKED]
        self.lost = [t for t in everyone if t.state == LOST and self.frame - t.end_frame <= self.max_lost]
        return np.array([[*t.xyxy, t.tid, t.score, t.cls] for t in self.tracked if t.is_activated], np.float32).reshape(-1, 7)
