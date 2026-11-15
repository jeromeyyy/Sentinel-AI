"""One YOLO model, loaded once at startup, shared by every camera."""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

from .config import PipelineConfig
from .geometry import scale_box, target_size

log = logging.getLogger("pipeline.detector")
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def resolve_model_path(path: str) -> str:
    p = Path(path)
    for cand in (p, _BACKEND_DIR / p, _BACKEND_DIR / "models" / p.name):
        if cand.exists():
            return str(cand)
    return path  # let ultralytics try to download a stock weight by name


class SharedDetector:
    """Thread-safe wrapper. A lock serialises predict() calls: one model instance is not
    safe for concurrent inference, and on CPU running them in parallel gains nothing."""

    def __init__(self, cfg: PipelineConfig):
        from ultralytics import YOLO

        self.cfg = cfg
        self.model_path = resolve_model_path(cfg.model_path)
        self._lock = threading.Lock()
        t0 = time.time()
        self.model = YOLO(self.model_path, task="detect")
        self.names: Dict[int, str] = dict(self.model.names)
        log.info("Loaded %s in %.1fs", self.model_path, time.time() - t0)
        self.warmup()

    def warmup(self, n: int = 2):
        dummy = np.zeros((self.cfg.imgsz, self.cfg.imgsz, 3), dtype=np.uint8)
        t0 = time.time()
        for _ in range(n):
            self._predict(dummy, None, self.cfg.conf, self.cfg.imgsz)
        log.info("Warmup done (%d calls, %.0f ms each)", n, (time.time() - t0) * 1000 / n)

    def _predict(self, img, classes, conf, imgsz):
        kwargs = dict(imgsz=imgsz, conf=conf, iou=self.cfg.iou, verbose=False)
        if classes:
            kwargs["classes"] = list(classes)
        if self.cfg.device:
            kwargs["device"] = self.cfg.device
        if self.cfg.half and self.cfg.device not in ("", "cpu"):
            kwargs["half"] = True
        with self._lock:
            return self.model.predict(img, **kwargs)

    def detect(self, frame: np.ndarray, classes: Optional[Sequence[int]] = None,
               conf: Optional[float] = None, imgsz: Optional[int] = None,
               max_width: Optional[int] = None) -> List[dict]:
        """Run inference. The frame is downscaled to max_width first, and boxes are mapped
        back to the ORIGINAL frame's pixel coordinates before returning."""
        h, w = frame.shape[:2]
        mw = self.cfg.infer_max_width if max_width is None else max_width
        tw, th = target_size(w, h, mw)
        small = frame if (tw, th) == (w, h) else cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        res = self._predict(small, classes, conf if conf is not None else self.cfg.conf, imgsz or self.cfg.imgsz)[0]
        out = []
        if res.boxes is None or len(res.boxes) == 0:
            return out
        xyxy = res.boxes.xyxy.cpu().numpy()
        cf = res.boxes.conf.cpu().numpy()
        cl = res.boxes.cls.cpu().numpy().astype(int)
        for b, c, k in zip(xyxy, cf, cl):
            box = scale_box(b.tolist(), (tw, th), (w, h))
            out.append({"cls": int(k), "name": self.names.get(int(k), str(int(k))), "conf": float(c), "box": box})
        return out


def make_detector(cfg: PipelineConfig):
    """.onnx weights -> torch-free OnnxDetector; anything else -> ultralytics SharedDetector."""
    if cfg.model_path.lower().endswith(".onnx"):
        from .onnx_detector import OnnxDetector
        return OnnxDetector(cfg)
    return SharedDetector(cfg)
