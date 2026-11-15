"""Torch-free YOLOv8 detector: onnxruntime + numpy + OpenCV only. Same detect() interface as SharedDetector.

Export once (needs torch, on a dev machine): python scripts/export_onnx.py backend/models/yolov8n.pt 480
Then set DETECTOR_BACKEND=onnx, MODEL_PATH=models/yolov8n.onnx. The exported input size is fixed (IMGSZ must match).
"""
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np

from .config import PipelineConfig
from .geometry import scale_box, target_size

log = logging.getLogger("pipeline.onnx_detector")
_COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]


def letterbox(img, size, color=114):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else img
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas = np.full((size, size, 3), color, np.uint8)
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, left, top


class OnnxDetector:
    def __init__(self, cfg: PipelineConfig, model_path: Optional[str] = None):
        import onnxruntime as ort

        self.cfg = cfg
        path = model_path or cfg.model_path
        if not Path(path).exists():
            alt = Path(__file__).resolve().parent.parent / path
            path = str(alt) if alt.exists() else path
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.inp_name = inp.name
        self.size = int(inp.shape[2]) if isinstance(inp.shape[2], int) else cfg.imgsz
        self.names: Dict[int, str] = dict(enumerate(_COCO))
        self.model_path = path
        self._lock = threading.Lock()
        t0 = time.time()
        for _ in range(2):
            self._run(np.zeros((self.size, self.size, 3), np.uint8))
        log.info("ONNX %s loaded, input %d, warmup %.0f ms", path, self.size, (time.time() - t0) * 500)

    def _run(self, letterboxed):
        x = letterboxed[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self._lock:
            return self.sess.run(None, {self.inp_name: np.ascontiguousarray(x)})[0]

    def detect(self, frame: np.ndarray, classes: Optional[Sequence[int]] = None, conf: Optional[float] = None,
               imgsz: Optional[int] = None, max_width: Optional[int] = None) -> List[dict]:
        conf = self.cfg.conf if conf is None else conf
        h, w = frame.shape[:2]
        lb, r, left, top = letterbox(frame, self.size)
        pred = self._run(lb)[0].T  # (N, 4+nc): cx, cy, w, h, class scores
        scores = pred[:, 4:]
        cls = scores.argmax(1)
        cf = scores[np.arange(len(cls)), cls]
        keep = cf >= conf
        if classes:
            keep &= np.isin(cls, list(classes))
        pred, cls, cf = pred[keep], cls[keep], cf[keep]
        if not len(cf):
            return []
        cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        boxes = np.stack([(cx - bw / 2 - left) / r, (cy - bh / 2 - top) / r, (cx + bw / 2 - left) / r, (cy + bh / 2 - top) / r], 1)
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h)
        xywh = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes]
        idx = cv2.dnn.NMSBoxesBatched(xywh, cf.tolist(), cls.tolist(), conf, self.cfg.iou)
        return [{"cls": int(cls[i]), "name": self.names.get(int(cls[i]), str(int(cls[i]))), "conf": float(cf[i]),
                 "box": [float(v) for v in boxes[i]]} for i in np.array(idx).reshape(-1)]
