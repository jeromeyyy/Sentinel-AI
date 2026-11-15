"""All pipeline tunables, read from the environment (.env). Defaults follow the repair spec."""
import os
from dataclasses import dataclass


def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _i(name, default):
    try:
        return int(float(os.getenv(name, default)))
    except ValueError:
        return int(default)


def _b(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class PipelineConfig:
    model_path: str      # MODEL_PATH: .pt, or .onnx exported with the same IMGSZ
    imgsz: int           # IMGSZ: inference size (416-640 recommended)
    conf: float          # CONF: base confidence (>=0.35 for most classes)
    iou: float           # IOU: NMS threshold
    frame_skip: int      # FRAME_SKIP: run inference every Nth captured frame
    stream_fps: float    # STREAM_FPS: cap for the encoder / what viewers get
    stream_max_width: int  # STREAM_MAX_WIDTH: downscale output (px)
    jpeg_quality: int    # JPEG_QUALITY: 70-80 is a good size/quality tradeoff
    infer_max_width: int   # INFER_MAX_WIDTH: frames are downscaled to this before inference
    device: str          # DEVICE: "cpu", "0" (CUDA) ...; "" lets ultralytics pick
    half: bool           # HALF: fp16, only honoured on CUDA
    phone_conf: float    # PHONE_CONF: lower confidence for 'cell phone' (classroom)
    phone_crop_pass: bool  # PHONE_CROP_PASS: re-run on person crops at higher imgsz
    phone_crop_imgsz: int
    confirm_phone_frames: int  # detections needed in a row before a phone event
    crowd_min_people: int
    crowd_seconds: float
    fight_seconds: float
    stopped_seconds: float
    extra_detectors: bool  # ENABLE_EXTRA_DETECTORS: fire/smoke + weapon models (heavy)
    extra_every: int       # run extra detectors every Nth inference cycle
    autostart: bool        # PIPELINE_AUTOSTART: start cameras at boot, else on first viewer
    idle_stop_seconds: float  # stop a camera with no viewers (0 = never)
    video_loop: bool
    clean_stream_default: bool  # CLEAN_STREAM: serve un-annotated video, boxes via WebSocket


def load_config() -> PipelineConfig:
    return PipelineConfig(
        model_path=os.getenv("MODEL_PATH", "models/yolov8n.pt"),
        imgsz=_i("IMGSZ", 480),
        conf=_f("CONF", 0.35),
        iou=_f("IOU", 0.5),
        frame_skip=max(1, _i("FRAME_SKIP", 3)),
        stream_fps=_f("STREAM_FPS", 15),
        stream_max_width=_i("STREAM_MAX_WIDTH", 960),
        jpeg_quality=_i("JPEG_QUALITY", 75),
        infer_max_width=_i("INFER_MAX_WIDTH", 640),
        device=os.getenv("DEVICE", "cpu"),
        half=_b("HALF", False),
        phone_conf=_f("PHONE_CONF", 0.25),
        phone_crop_pass=_b("PHONE_CROP_PASS", True),
        phone_crop_imgsz=_i("PHONE_CROP_IMGSZ", 640),
        confirm_phone_frames=_i("PHONE_CONFIRM_FRAMES", 3),
        crowd_min_people=_i("CROWD_MIN_PEOPLE", 5),
        crowd_seconds=_f("CROWD_SECONDS", 3.0),
        fight_seconds=_f("FIGHT_SECONDS", 1.5),
        stopped_seconds=_f("STOPPED_SECONDS", 2.0),
        extra_detectors=_b("ENABLE_EXTRA_DETECTORS", True),
        extra_every=max(1, _i("EXTRA_DETECTORS_EVERY", 3)),
        autostart=_b("PIPELINE_AUTOSTART", True),
        idle_stop_seconds=_f("IDLE_STOP_SECONDS", 0),
        video_loop=_b("VIDEO_LOOP", True),
        clean_stream_default=_b("CLEAN_STREAM", False),
    )
