"""Per-camera capture -> inference -> encode pipeline.

Three independent workers per camera, so the video never waits for inference:
  capture   (thread)  reads the source, keeps ONLY the latest frame (old ones are dropped).
                      Files are paced to their native FPS; RTSP/HTTP is read as fast as it arrives.
  inference (thread)  takes the latest frame every FRAME_SKIP captured frames (at whatever pace the
                      CPU allows), runs the shared model, ByteTrack, zone analytics, emits events.
  encoder   (thread)  at STREAM_FPS, draws the last known tracks on the latest frame and JPEG-encodes
                      it once for all viewers. Only runs while somebody is watching.
One CameraStream per camera, however many browser tabs are open.
"""
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2
import numpy as np

from .analytics import PERSON, PHONE, ZONE_CLASSES, ZoneAnalytics
from .config import PipelineConfig
from .cooldown import EventCooldownManager
from .detector import SharedDetector, make_detector
from .geometry import BoxSmoother, clip_box, target_size
from .tracking import CameraTracker

log = logging.getLogger("pipeline.stream")
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "snapshots"
SNAPSHOT_RETENTION_DAYS = float(os.getenv("SNAPSHOT_RETENTION_DAYS", "7"))


def prune_snapshots(days: float = SNAPSHOT_RETENTION_DAYS) -> int:
    """Delete event snapshots older than `days` (privacy/disk). 0 disables. Only evt_*.jpg files."""
    if days <= 0 or not SNAPSHOTS_DIR.exists():
        return 0
    cutoff, n = time.time() - days * 86400, 0
    for f in SNAPSHOTS_DIR.glob("evt_*.jpg"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n

COLORS = {"person": (255, 200, 0), "car": (0, 200, 255), "bus": (0, 140, 255), "truck": (0, 140, 255),
          "motorcycle": (0, 200, 255), "cell phone": (255, 100, 200)}


class _Rate:
    """Events-per-second over a sliding window."""

    def __init__(self, window=3.0):
        self.w = window
        self.t = deque()

    def tick(self, now=None):
        now = now or time.time()
        self.t.append(now)
        while self.t and now - self.t[0] > self.w:
            self.t.popleft()

    def rate(self):
        now = time.time()
        while self.t and now - self.t[0] > self.w:
            self.t.popleft()
        if len(self.t) < 2:
            return 0.0
        return (len(self.t) - 1) / max(1e-6, self.t[-1] - self.t[0])


class CameraStream:
    def __init__(self, camera_id: str, zone: str, source: str, cfg: PipelineConfig, detector: Optional[SharedDetector],
                 emit: Callable[[dict], None], cooldown: EventCooldownManager, polygon_norm=None,
                 tenant_id: str = "default", extra=None, is_file: Optional[bool] = None):
        self.camera_id, self.zone, self.source, self.cfg = camera_id, zone, source, cfg
        self.detector, self.emit, self.cooldown, self.tenant_id, self.extra = detector, emit, cooldown, tenant_id, extra
        self.is_file = (not source.lower().startswith(("rtsp://", "http://", "https://"))) if is_file is None else is_file
        self.analytics = ZoneAnalytics(zone, cfg, polygon_norm)
        self.tracker = CameraTracker(max(1.0, 25.0 / cfg.frame_skip), torch_free=cfg.model_path.lower().endswith(".onnx"))
        self.smoother = BoxSmoother(0.6)
        self.classes = ZONE_CLASSES.get(zone, ZONE_CLASSES["corridor"])

        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._cond = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._seq = 0
        self._frame_t = 0.0
        self.size = (0, 0)
        self.src_fps = 0.0
        self.total_frames = 0
        self.pos_frame = 0

        self._tracks: List[dict] = []
        self._tracks_t = 0.0
        self._tracks_seq = 0
        self._tlock = threading.Lock()

        self._jpeg: Dict[str, Optional[bytes]] = {"annotated": None, "clean": None}
        self._jpeg_seq = 0
        self._viewers = {"annotated": 0, "clean": 0}
        self._viewer_lock = threading.Lock()
        self._last_viewer_t = time.time()

        self.state = "starting"  # starting | live | reconnecting | error | stopped
        self.error: Optional[str] = None
        self.started_at = time.time()
        self.first_frame_at: Optional[float] = None
        self.m_cap, self.m_inf, self.m_out = _Rate(), _Rate(), _Rate()
        self.m_infer_ms = 0.0
        self.m_lag_ms = 0.0
        self.events_emitted = 0
        self.events_suppressed = 0

    # ---------------------------------------------------------------- control
    def start(self):
        for name, fn in (("capture", self._capture_loop), ("inference", self._inference_loop), ("encoder", self._encoder_loop)):
            th = threading.Thread(target=fn, name=f"{self.camera_id}-{name}", daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        for th in self._threads:
            th.join(timeout=3)
        self.state = "stopped"

    def add_viewer(self, kind: str):
        with self._viewer_lock:
            self._viewers[kind] += 1
            self._last_viewer_t = time.time()

    def remove_viewer(self, kind: str):
        with self._viewer_lock:
            self._viewers[kind] = max(0, self._viewers[kind] - 1)
            self._last_viewer_t = time.time()

    @property
    def viewer_count(self):
        return sum(self._viewers.values())

    def idle_seconds(self):
        return 0.0 if self.viewer_count else time.time() - self._last_viewer_t

    # ---------------------------------------------------------------- capture
    def _open(self):
        cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        if cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # drop stale frames inside the backend when supported
            except Exception:
                pass
        return cap

    def _capture_loop(self):
        backoff = 1.0
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                self.state, self.error = "reconnecting" if self.first_frame_at else "error", f"cannot open source"
                log.warning("[%s] cannot open %s, retry in %.0fs", self.camera_id, self.source, backoff)
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 15)
                continue
            backoff = 1.0
            self.src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) if self.is_file else 0
            interval = 1.0 / min(max(self.src_fps, 1.0), 60.0) if self.is_file else 0.0
            next_t = time.time()
            bad = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    if self.is_file and self.cfg.video_loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self.pos_frame = 0
                        ok2, frame = cap.read()
                        if not ok2:
                            break
                    else:
                        bad += 1
                        if bad > 30:
                            break
                        time.sleep(0.02)
                        continue
                bad = 0
                self.pos_frame += 1
                h, w = frame.shape[:2]
                tw, th_ = target_size(w, h, self.cfg.stream_max_width)
                if (tw, th_) != (w, h):
                    frame = cv2.resize(frame, (tw, th_), interpolation=cv2.INTER_AREA)
                with self._cond:
                    self._frame, self._frame_t, self._seq = frame, time.time(), self._seq + 1
                    self.size = (tw, th_)
                    self._cond.notify_all()
                self.m_cap.tick()
                if self.first_frame_at is None:
                    self.first_frame_at = time.time()
                self.state, self.error = "live", None
                if interval:  # real-time pacing for files
                    next_t += interval
                    delay = next_t - time.time()
                    if delay > 0:
                        if self._stop.wait(delay):
                            break
                    else:
                        next_t = time.time()
            cap.release()
            if not self._stop.is_set():
                self.state = "reconnecting"

    # -------------------------------------------------------------- inference
    def _wait_frame(self, last_seq):
        with self._cond:
            while not self._stop.is_set() and (self._seq - last_seq) < self.cfg.frame_skip:
                self._cond.wait(timeout=0.5)
            if self._stop.is_set():
                return None
            return self._frame, self._seq, self._frame_t

    def _inference_loop(self):
        last_seq, cycle = 0, 0
        while not self._stop.is_set():
            got = self._wait_frame(last_seq)
            if got is None:
                return
            frame, seq, ft = got
            if frame is None:
                continue
            last_seq = seq
            cycle += 1
            try:
                self._infer_once(frame, seq, ft, cycle)
            except Exception:
                log.exception("[%s] inference error", self.camera_id)
                time.sleep(0.2)

    def _infer_once(self, frame, seq, ft, cycle):
        t0 = time.time()
        pick_up_lag = (t0 - ft) * 1000
        h, w = frame.shape[:2]
        dets = self.detector.detect(frame, self.classes, self.cfg.conf) if (self.detector and self.classes) else []
        # classroom phones: lower confidence + second pass on person crops (small objects)
        phones: List[dict] = []
        if self.zone == "classroom" and self.detector:
            pdets = self.detector.detect(frame, [PHONE], self.cfg.phone_conf)
            phones += pdets
            persons_now = [d for d in dets if d["cls"] == PERSON]
            if self.cfg.phone_crop_pass and cycle % 2 == 0:
                for p in sorted(persons_now, key=lambda d: -d["conf"])[:4]:
                    x1, y1, x2, y2 = [int(v) for v in clip_box(p["box"], (w, h))]
                    pad = int(0.1 * max(x2 - x1, y2 - y1))
                    x1c, y1c, x2c, y2c = max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)
                    if x2c - x1c < 24 or y2c - y1c < 24:
                        continue
                    crop = frame[y1c:y2c, x1c:x2c]
                    for d in self.detector.detect(crop, [PHONE], self.cfg.phone_conf, imgsz=self.cfg.phone_crop_imgsz,
                                                  max_width=self.cfg.phone_crop_imgsz):
                        b = d["box"]
                        d["box"] = [b[0] + x1c, b[1] + y1c, b[2] + x1c, b[3] + y1c]
                        phones.append(d)
            dets = [d for d in dets if d["cls"] != PHONE]
            phones = _dedupe(phones)
        tracks = self.tracker.update(dets, self.detector.names if self.detector else {})
        now = time.time()
        for tr in tracks:
            tr["box"] = self.smoother.update(tr["id"], tr["box"], now)
        self.smoother.prune(now)
        events = self.analytics.update(tracks, phones, now, (w, h))
        if self.extra and (cycle % self.cfg.extra_every == 0):
            try:
                weapons, fire = self.extra.run(frame)
                events += self.analytics.update_extra(weapons, fire)
            except Exception:
                log.exception("[%s] extra detectors failed", self.camera_id)
        vel = {tr["id"]: self.analytics.motion.velocity(tr["id"]) for tr in tracks}
        for tr in tracks:
            tr["vx"], tr["vy"] = vel.get(tr["id"], (0.0, 0.0))
        for p in phones:
            tracks_phone = {"id": -1, "cls": PHONE, "name": "cell phone", "conf": p["conf"], "box": p["box"], "vx": 0.0, "vy": 0.0}
            tracks.append(tracks_phone)
        with self._tlock:
            self._tracks, self._tracks_t, self._tracks_seq = tracks, now, seq
        done = time.time()
        self.m_inf.tick(done)
        ms = (done - t0) * 1000
        self.m_infer_ms = ms if self.m_infer_ms == 0 else 0.8 * self.m_infer_ms + 0.2 * ms
        lag = pick_up_lag + ms
        self.m_lag_ms = lag if self.m_lag_ms == 0 else 0.8 * self.m_lag_ms + 0.2 * lag
        for ev in events:
            self._emit(ev, frame, tracks)

    def _emit(self, ev, frame, tracks):
        if not self.cooldown.should_emit(self.camera_id, ev["event_type"], ev["confidence"]):
            self.events_suppressed += 1
            return
        ts = time.time()
        eid = f"evt_{ev['event_type']}_{int(ts * 1000)}_{self.camera_id}"
        snap = None
        try:
            SNAPSHOTS_DIR.mkdir(exist_ok=True)
            img = _draw(frame.copy(), tracks, 0.0)
            for b in ev["boxes"]:
                x1, y1, x2, y2 = [int(v) for v in b]
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
            cv2.imwrite(str(SNAPSHOTS_DIR / f"{eid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            snap = str(SNAPSHOTS_DIR / f"{eid}.jpg")
        except Exception:
            log.exception("snapshot failed")
        self.events_emitted += 1
        self.emit({
            "event_id": eid, "tenant_id": self.tenant_id, "camera_id": self.camera_id, "zone": self.zone,
            "event_type": ev["event_type"], "confidence": ev["confidence"], "timestamp": ts,
            "bounding_boxes": ev["boxes"], "severity_score": ev["confidence"],
            "metadata": {**ev.get("metadata", {}), "live_stream": True, "frame_size": list(self.size)},
            "snapshot_path": snap,
        })

    # ---------------------------------------------------------------- encoder
    def _encoder_loop(self):
        interval = 1.0 / max(1.0, self.cfg.stream_fps)
        nxt = time.time()
        last_seq = 0
        params = [cv2.IMWRITE_JPEG_QUALITY, int(self.cfg.jpeg_quality)]
        while not self._stop.is_set():
            nxt += interval
            if self._viewer_total() == 0:
                if self._stop.wait(0.1):
                    return
                nxt = time.time()
                continue
            with self._cond:
                frame, seq, ft = self._frame, self._seq, self._frame_t
            if frame is not None and seq != last_seq:
                last_seq = seq
                with self._tlock:
                    tracks, tt = self._tracks, self._tracks_t
                if self._viewers["annotated"]:
                    img = _draw(frame.copy(), tracks, min(0.4, time.time() - tt))
                    ok, buf = cv2.imencode(".jpg", img, params)
                    if ok:
                        self._jpeg["annotated"] = buf.tobytes()
                if self._viewers["clean"]:
                    ok, buf = cv2.imencode(".jpg", frame, params)
                    if ok:
                        self._jpeg["clean"] = buf.tobytes()
                self._jpeg_seq += 1
                self.m_out.tick()
            delay = nxt - time.time()
            if delay > 0:
                if self._stop.wait(delay):
                    return
            else:
                nxt = time.time()

    def _viewer_total(self):
        return self._viewers["annotated"] + self._viewers["clean"]

    def latest_jpeg(self, kind: str):
        return self._jpeg_seq, self._jpeg.get(kind)

    # ----------------------------------------------------------- introspection
    def detections_json(self) -> dict:
        with self._tlock:
            tracks, tt, seq = list(self._tracks), self._tracks_t, self._tracks_seq
        w, h = self.size or (1, 1)
        age = time.time() - tt
        out = []
        for tr in tracks:
            dx, dy = tr.get("vx", 0.0) * min(0.4, age), tr.get("vy", 0.0) * min(0.4, age)
            x1, y1, x2, y2 = tr["box"]
            out.append({"id": tr["id"], "class": tr["name"], "conf": round(tr["conf"], 3),
                        "box": [round((x1 + dx) / w, 4), round((y1 + dy) / h, 4), round((x2 + dx) / w, 4), round((y2 + dy) / h, 4)]})
        return {"camera_id": self.camera_id, "frame_size": [w, h], "age_ms": round(age * 1000), "tracks": out}

    def metrics(self) -> dict:
        prog = (self.pos_frame / self.total_frames) if (self.is_file and self.total_frames) else None
        return {
            "camera_id": self.camera_id, "zone": self.zone, "state": self.state, "error": self.error,
            "source_type": "file" if self.is_file else "stream",
            "capture_fps": round(self.m_cap.rate(), 1), "inference_fps": round(self.m_inf.rate(), 1),
            "inference_ms": round(self.m_infer_ms, 1), "stream_fps": round(self.m_out.rate(), 1),
            "queue_lag_ms": round(self.m_lag_ms, 1),
            "overlay_age_ms": round((time.time() - self._tracks_t) * 1000) if self._tracks_t else None,
            "viewers": self.viewer_count,
            "frame_size": list(self.size), "events_emitted": self.events_emitted,
            "events_suppressed": self.events_suppressed, "file_progress": prog,
            "time_to_first_frame_s": round(self.first_frame_at - self.started_at, 2) if self.first_frame_at else None,
        }


def _dedupe(dets, thr=0.5):
    from .geometry import iou
    keep = []
    for d in sorted(dets, key=lambda x: -x["conf"]):
        if all(iou(d["box"], k["box"]) < thr for k in keep):
            keep.append(d)
    return keep


def _draw(img, tracks, age):
    h, w = img.shape[:2]
    for tr in tracks:
        x1, y1, x2, y2 = tr["box"]
        dx, dy = tr.get("vx", 0.0) * age, tr.get("vy", 0.0) * age
        x1, y1, x2, y2 = [int(v) for v in clip_box([x1 + dx, y1 + dy, x2 + dx, y2 + dy], (w, h))]
        color = COLORS.get(tr["name"], (0, 255, 120))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"{tr['name']} #{tr['id']} {tr['conf']:.2f}" if tr["id"] >= 0 else f"{tr['name']} {tr['conf']:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ytop = max(0, y1 - th - 6)
        cv2.rectangle(img, (x1, ytop), (min(w - 1, x1 + tw + 6), ytop + th + 6), color, -1)
        cv2.putText(img, label, (x1 + 3, ytop + th + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return img


class ExtraDetectors:
    """Optional fire/smoke + weapon models from worker/detectors.py (heavy: extra models)."""

    def __init__(self):
        from worker.registry import ModelRegistry
        from worker.detectors import FireSmokeDetector, WeaponDetector
        reg = ModelRegistry()
        self.fire, self.weapon = FireSmokeDetector(reg), WeaponDetector(reg)

    def run(self, frame):
        w = self.weapon.detect(frame) if self.weapon.is_available else []
        f = self.fire.detect(frame)
        conv = lambda L: [{"name": x["class_name"], "conf": x["confidence"], "box": list(map(float, x["bbox"]))} for x in L]
        return conv(w), conv(f)


class StreamManager:
    def __init__(self, cfg: PipelineConfig, emit: Callable[[dict], None]):
        self.cfg, self.emit = cfg, emit
        self.cooldown = EventCooldownManager()
        self.detector: Optional[SharedDetector] = None
        self.extra: Optional[ExtraDetectors] = None
        self.streams: Dict[str, CameraStream] = {}
        self._lock = threading.Lock()
        self._reaper = None
        self.model_error: Optional[str] = None

    def init_models(self):
        """Load the model ONCE (blocking; call from startup in a thread) and warm it up."""
        try:
            self.detector = make_detector(self.cfg)
        except Exception as e:
            self.model_error = repr(e)
            log.exception("model load failed")
            return
        if self.cfg.extra_detectors:
            try:
                self.extra = ExtraDetectors()
            except Exception:
                log.exception("extra detectors unavailable; continuing without fire/weapon models")

    def ensure(self, camera_id, zone, source, polygon_norm=None, tenant_id="default", restart=False) -> CameraStream:
        with self._lock:
            cs = self.streams.get(camera_id)
            if cs and (restart or cs.source != source or cs.zone != zone or cs._stop.is_set()):
                cs.stop()
                cs = None
            if cs is None:
                cs = CameraStream(camera_id, zone, source, self.cfg, self.detector, self.emit, self.cooldown,
                                  polygon_norm, tenant_id, self.extra)
                self.streams[camera_id] = cs
                cs.start()
            return cs

    def get(self, camera_id) -> Optional[CameraStream]:
        return self.streams.get(camera_id)

    def stop(self, camera_id):
        with self._lock:
            cs = self.streams.pop(camera_id, None)
        if cs:
            cs.stop()

    def stop_all(self):
        for cid in list(self.streams):
            self.stop(cid)

    def metrics(self) -> dict:
        return {"model": os.path.basename(self.detector.model_path) if self.detector else None,
                "model_error": self.model_error,
                "config": {"frame_skip": self.cfg.frame_skip, "imgsz": self.cfg.imgsz, "conf": self.cfg.conf,
                           "iou": self.cfg.iou, "stream_fps": self.cfg.stream_fps, "jpeg_quality": self.cfg.jpeg_quality,
                           "stream_max_width": self.cfg.stream_max_width, "device": self.cfg.device,
                           "extra_detectors": bool(self.extra)},
                "cameras": {cid: s.metrics() for cid, s in self.streams.items()}}

    def start_reaper(self):
        if self.cfg.idle_stop_seconds <= 0 or self._reaper:
            return

        def loop():
            while True:
                time.sleep(5)
                for cid, s in list(self.streams.items()):
                    if s.idle_seconds() > self.cfg.idle_stop_seconds:
                        log.info("stopping idle camera %s", cid)
                        self.stop(cid)
        self._reaper = threading.Thread(target=loop, daemon=True)
        self._reaper.start()
