#!/usr/bin/env python3
"""Measure a live MJPEG stream from a running backend (used for before/after numbers).

Usage: python scripts/measure_stream.py http://localhost:8000 CAMERA_ID [seconds] [viewers]
Reports: time to first frame, delivered FPS, p50/p95 gap between frames, and the
latency of GET /health while the stream(s) run (shows whether the server is blocked).
"""
import sys, time, threading, statistics, json
import httpx


def read_stream(url, seconds, out):
    t0 = time.time()
    frames, stamps, first = 0, [], None
    buf = b""
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(60.0)) as r:
            for chunk in r.iter_bytes(8192):
                buf += chunk
                while True:
                    a = buf.find(b"\xff\xd8")
                    b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                    if a < 0 or b < 0:
                        break
                    buf = buf[b + 2:]
                    now = time.time()
                    frames += 1
                    stamps.append(now)
                    if first is None:
                        first = now - t0
                if time.time() - t0 > seconds:
                    break
    except Exception as e:
        out["error"] = repr(e)
    dur = (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    out.update(
        first_frame_s=first, frames=frames,
        fps=(frames - 1) / dur if dur > 0 else 0,
        gap_p50_ms=statistics.median(gaps) * 1000 if gaps else None,
        gap_p95_ms=sorted(gaps)[int(len(gaps) * 0.95) - 1] * 1000 if len(gaps) > 20 else None,
        gap_max_ms=max(gaps) * 1000 if gaps else None,
    )


def probe_health(base, seconds, out):
    lat = []
    end = time.time() + seconds
    while time.time() < end:
        t = time.time()
        try:
            httpx.get(base + "/health", timeout=30.0)
            lat.append((time.time() - t) * 1000)
        except Exception:
            lat.append(30000)
        time.sleep(0.5)
    out.update(health_n=len(lat), health_p50_ms=statistics.median(lat) if lat else None,
               health_max_ms=max(lat) if lat else None)


def main():
    base, cam = sys.argv[1].rstrip("/"), sys.argv[2]
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 20
    viewers = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    res = [dict() for _ in range(viewers)]
    hp = {}
    ths = [threading.Thread(target=read_stream, args=(f"{base}/video/{cam}", seconds, r)) for r in res]
    ths.append(threading.Thread(target=probe_health, args=(base, seconds, hp)))
    [t.start() for t in ths]
    [t.join() for t in ths]
    print(json.dumps({"viewers": res, "health_probe": hp}, indent=1, default=str))


if __name__ == "__main__":
    main()
