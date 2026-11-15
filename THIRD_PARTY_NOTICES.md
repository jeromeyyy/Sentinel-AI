# Third-party notices

- **Ultralytics YOLOv8** (ultralytics package, yolov8n.pt weights, yolov8n.onnx export): AGPL-3.0, https://github.com/ultralytics/ultralytics. The original project already depended on it.
- **backend/pipeline/kalman_xyah.py**: the `KalmanFilterXYAH` class copied unchanged from Ultralytics (`ultralytics/trackers/utils/kalman_filter.py`), original AGPL-3.0 header kept in the file. Source: the Ultralytics repository above.
- **backend/pipeline/bytetrack_lite.py**: an independent compact implementation of the ByteTrack algorithm (Zhang et al., ECCV 2022, https://github.com/ifzhang/ByteTrack, MIT) modelled on the Ultralytics tracker's structure and defaults. It imports kalman_xyah.py, so treat the combined runtime as AGPL-3.0 material.
- **Test video clips** (not in the repo): Intel IoT DevKit sample videos were used locally for measurements only. Their licence was not verified and they are not redistributed.

**Open decision for the repository owner:** this repository has no LICENSE file. Because AGPL-3.0 code (Ultralytics, and the copied Kalman file) is used, and the backend is run as a network service, AGPL source-offer obligations may apply to the deployed backend. This was not decided or changed here; pick a licence deliberately (or get legal advice) before relying on the code publicly.
