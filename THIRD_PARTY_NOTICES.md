# Third-party notices

## Existing obligations (unchanged by this repair)
- **Ultralytics YOLOv8** (the `ultralytics` package, yolov8n.pt and the other .pt weights already in the repo): AGPL-3.0, https://github.com/ultralytics/ultralytics. The original project already depended on it. The repo has no LICENSE file. If the backend is deployed as a network service with the Ultralytics build, AGPL-3.0 source-offer terms may apply to it. This repair did not decide or change that.

## Added by this repair
- **backend/pipeline/kalman_xyah.py**: an independently written constant-velocity Kalman filter from the standard linear Kalman equations. An earlier version of this file (commit 'backend/pipeline' on branch sentinel-ai-repair, 4cea54b) was an unchanged copy of the Ultralytics `KalmanFilterXYAH` class with its AGPL-3.0 header kept; it was replaced by this rewrite, but that earlier commit remains in the branch history. The noise constants (1/20, 1/160) are the published ByteTrack/DeepSORT tuning numbers. Numerically it matches the Ultralytics filter to ~1e-15 on a synthetic track (expected: same equations); that comparison was run only as a test, no code was taken from it.
- **backend/pipeline/bytetrack_lite.py**: independent implementation of the ByteTrack algorithm (Zhang et al., ECCV 2022, https://github.com/ifzhang/ByteTrack, MIT). Uses `lap`/`lapx` (BSD-2) for assignment.
- The **torch-free runtime** (Dockerfile.lite) uses onnxruntime (MIT), OpenCV and numpy. The yolov8n.onnx it serves is exported at build time from the Ultralytics yolov8n.pt weights, so the weights remain AGPL-3.0 material.
- **Test video clips** (not in the repo): Intel IoT DevKit sample videos were used locally for measurements only. Licence not verified, not redistributed.
