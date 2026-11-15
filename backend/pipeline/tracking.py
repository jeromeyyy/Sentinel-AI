"""Per-camera ByteTrack (ultralytics' BYTETracker) fed with our shared-model detections.
We call the tracker directly, not model.track(), because model.track() keeps tracker state
inside the model and would mix identities when several cameras share one model."""
from types import SimpleNamespace
from typing import List

import numpy as np


class _Dets:
    """Minimal object with the attributes BYTETracker reads from ultralytics Boxes."""

    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)
        x1, y1, x2, y2 = self.xyxy.T if len(self.xyxy) else (np.array([]),) * 4
        self.xywh = np.stack([(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1], axis=1) if len(self.xyxy) else np.zeros((0, 4), np.float32)

    def __len__(self):
        return len(self.conf)

    def __getitem__(self, idx):
        return _Dets(self.xyxy[idx], self.conf[idx], self.cls[idx])


class CameraTracker:
    def __init__(self, frame_rate: float = 10.0, torch_free: bool = False):
        self.lite = None
        if torch_free:
            from .bytetrack_lite import ByteTrackLite
            self.lite = ByteTrackLite(frame_rate=int(max(1, frame_rate)))
            return
        from ultralytics.trackers.byte_tracker import BYTETracker
        global _BT
        _BT = BYTETracker
        args = SimpleNamespace(
            track_high_thresh=0.35, track_low_thresh=0.1, new_track_thresh=0.4,
            track_buffer=30, match_thresh=0.8, fuse_score=True, frame_rate=int(max(1, frame_rate)),
        )
        self.tracker = BYTETracker(args, frame_rate=int(max(1, frame_rate))) if _accepts_fr(BYTETracker) else BYTETracker(args)

    def update(self, dets: List[dict], names: dict) -> List[dict]:
        if dets:
            d = _Dets([x["box"] for x in dets], [x["conf"] for x in dets], [x["cls"] for x in dets])
        else:
            d = _Dets(np.zeros((0, 4)), [], [])
        if self.lite is not None:
            out = self.lite.update(d.xyxy, d.conf, d.cls)
        else:
            out = self.tracker.update(d)
        tracks = []
        for row in out:
            x1, y1, x2, y2, tid, conf, cls = row[:7]
            tracks.append({"id": int(tid), "cls": int(cls), "name": names.get(int(cls), str(int(cls))),
                           "conf": float(conf), "box": [float(x1), float(y1), float(x2), float(y2)]})
        return tracks


def _accepts_fr(BYTETracker) -> bool:
    import inspect
    return "frame_rate" in inspect.signature(BYTETracker.__init__).parameters
