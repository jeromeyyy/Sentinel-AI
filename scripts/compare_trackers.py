"""Compare ByteTrackLite with ultralytics' BYTETracker on the SAME detections (ONNX detector) from a clip.
Reports unique IDs, per-frame track-count agreement, and ID agreement (share of lite tracks whose box
matches a reference track at IoU>0.5 and whose lite-id->ref-id mapping stays consistent). No ground truth."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import cv2, numpy as np
from collections import Counter, defaultdict
from pipeline.config import load_config
from pipeline.onnx_detector import OnnxDetector
from pipeline.tracking import CameraTracker
from pipeline.bytetrack_lite import _iou

model, video, skip = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3
cfg = load_config(); det = OnnxDetector(cfg, model)
fr = 25.0 / skip
ref, lite = CameraTracker(fr, torch_free=False), CameraTracker(fr, torch_free=True)
cap = cv2.VideoCapture(video); i = n = 0
ids_r, ids_l = set(), set(); cnt_agree = 0; pairs = defaultdict(Counter); matched = total = 0
while True:
    ok, f = cap.read()
    if not ok: break
    i += 1
    if i % skip: continue
    d = det.detect(f, [0]); n += 1
    a, b = ref.update(d, det.names), lite.update(d, det.names)
    ids_r |= {t["id"] for t in a}; ids_l |= {t["id"] for t in b}
    cnt_agree += len(a) == len(b)
    if a and b:
        m = _iou(np.array([t["box"] for t in b]), np.array([t["box"] for t in a]))
        for k, t in enumerate(b):
            total += 1
            j = int(m[k].argmax())
            if m[k, j] > 0.5: matched += 1; pairs[t["id"]][a[j]["id"]] += 1
    else:
        total += len(b)
consistent = sum(c.most_common(1)[0][1] for c in pairs.values()); allm = sum(sum(c.values()) for c in pairs.values())
print(json.dumps({"video": os.path.basename(video), "frames_tracked": n, "unique_ids_ultralytics": len(ids_r), "unique_ids_lite": len(ids_l),
  "frames_same_track_count_pct": round(100 * cnt_agree / max(n, 1), 1), "lite_tracks_matching_a_ref_box_pct": round(100 * matched / max(total, 1), 1),
  "lite_id_maps_to_one_ref_id_pct": round(100 * consistent / max(allm, 1), 1)}))
