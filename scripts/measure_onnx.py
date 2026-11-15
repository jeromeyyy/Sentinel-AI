"""Measure the torch-free path: peak RSS, per-frame latency and detections for onnxruntime vs the .pt model.
Usage: python scripts/measure_onnx.py MODEL.onnx VIDEO [frames]   (asserts torch is NOT imported)"""
import json, os, resource, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import cv2
from pipeline.config import load_config
from pipeline.onnx_detector import OnnxDetector

model, video = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 150
cfg = load_config()
det = OnnxDetector(cfg, model)
cap = cv2.VideoCapture(video); ts, dets, i = [], 0, 0
while i < n:
    ok, f = cap.read()
    if not ok: break
    t = time.time(); d = det.detect(f, [0]); ts.append((time.time() - t) * 1000); dets += len(d); i += 1
ts.sort()
print(json.dumps({"torch_imported": "torch" in sys.modules, "ultralytics_imported": "ultralytics" in sys.modules,
  "frames": len(ts), "p50_ms": round(ts[len(ts)//2], 1), "mean_ms": round(sum(ts)/len(ts), 1), "person_boxes": dets,
  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}))
