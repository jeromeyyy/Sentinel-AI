#!/usr/bin/env python3
"""Export a YOLO .pt to ONNX for faster CPU inference (e.g. on Render free/starter).

  python scripts/export_onnx.py backend/models/yolov8n.pt 480
Then set MODEL_PATH=models/yolov8n.onnx and IMGSZ=480 (they must match: the export is fixed-size).
"""
import sys
from ultralytics import YOLO

pt = sys.argv[1] if len(sys.argv) > 1 else "backend/models/yolov8n.pt"
imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 480
print(YOLO(pt).export(format="onnx", imgsz=imgsz, simplify=False, dynamic=False))
