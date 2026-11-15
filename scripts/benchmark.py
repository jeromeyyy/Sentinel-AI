#!/usr/bin/env python3
"""Offline benchmark of the detection pipeline on a video (no server, no real-time pacing).

  python scripts/benchmark.py <video> [--zone corridor|outgate|school_ground|classroom|fire_only]
                              [--max-frames N] [--json out.json]

Honours the same env vars as the server (MODEL_PATH, IMGSZ, CONF, IOU, FRAME_SKIP, ENABLE_EXTRA_DETECTORS ...).
Reports: avg/p95 inference ms (per inference cycle, all model calls included), processing FPS
(frames consumed per second when inference is the only limit), detection counts per class,
unique track IDs, and which heuristic events fired. It does NOT report accuracy: that needs labels.
"""
import argparse, json, os, statistics, sys, time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import cv2  # noqa: E402

from pipeline.analytics import PERSON, PHONE, ZONE_CLASSES, ZoneAnalytics  # noqa: E402
from pipeline.config import load_config  # noqa: E402
from pipeline.detector import SharedDetector  # noqa: E402
from pipeline.geometry import target_size  # noqa: E402
from pipeline.tracking import CameraTracker  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--zone", default="corridor")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--json")
    a = ap.parse_args()
    cfg = load_config()
    det = SharedDetector(cfg)
    extra = None
    if cfg.extra_detectors:
        try:
            from pipeline.stream import ExtraDetectors
            extra = ExtraDetectors()
        except Exception as e:
            print("extra detectors unavailable:", e)
    cap = cv2.VideoCapture(a.video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    tracker = CameraTracker(max(1.0, src_fps / cfg.frame_skip))
    za = ZoneAnalytics(a.zone, cfg)
    classes = ZONE_CLASSES.get(a.zone, [])
    ms, counts, ids, events = [], Counter(), set(), Counter()
    frames = cycles = 0
    t_start = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        if a.max_frames and frames > a.max_frames:
            break
        if (frames - 1) % cfg.frame_skip:
            continue
        h, w = frame.shape[:2]
        tw, th = target_size(w, h, cfg.stream_max_width)
        if (tw, th) != (w, h):
            frame = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        t0 = time.time()
        dets = det.detect(frame, classes, cfg.conf) if classes else []
        phones = []
        if a.zone == "classroom":
            phones = det.detect(frame, [PHONE], cfg.phone_conf)
            dets = [d for d in dets if d["cls"] != PHONE]
        tracks = tracker.update(dets, det.names)
        t_sim = frames / src_fps  # video time, so temporal rules behave as in real time
        evs = za.update(tracks, phones, t_sim, (tw, th))
        if extra and cycles % cfg.extra_every == 0:
            wp, fr = extra.run(frame)
            evs += za.update_extra(wp, fr)
            for x in wp + fr:
                counts[x["name"]] += 1
        ms.append((time.time() - t0) * 1000)
        cycles += 1
        for t in tracks:
            counts[t["name"]] += 1
            ids.add((t["name"], t["id"]))
        for e in evs:
            events[e["event_type"]] += 1
    wall = time.time() - t_start
    res = {
        "video": os.path.basename(a.video), "zone": a.zone, "resolution": f"{w}x{h}->{tw}x{th}", "source_fps": round(src_fps, 2),
        "frames_read": frames, "inference_cycles": cycles, "frame_skip": cfg.frame_skip, "imgsz": cfg.imgsz,
        "model": os.path.basename(det.model_path), "extra_detectors": bool(extra),
        "avg_inference_ms": round(statistics.mean(ms), 1) if ms else None,
        "p95_inference_ms": round(sorted(ms)[int(len(ms) * 0.95) - 1], 1) if len(ms) > 20 else None,
        "processing_fps": round(frames / wall, 1), "realtime_factor": round(frames / wall / src_fps, 2),
        "detections_per_class": dict(counts), "unique_tracks": dict(Counter(n for n, _ in ids)),
        "heuristic_events_before_cooldown": dict(events),
    }
    print(json.dumps(res, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
