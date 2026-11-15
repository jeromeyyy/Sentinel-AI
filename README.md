# Sentinel-AI

School safety monitoring: YOLOv8 detection on camera/video streams with per-zone rules
(outgate, corridor, school_ground, classroom), live MJPEG video, WebSocket alerts and a Next.js dashboard.

**Read this first:** object detection (person, vehicle, cell phone) is a real detector (COCO YOLOv8n).
Fight, accident, crowd and fall alerts are **heuristics on top of tracked boxes**, not trained classifiers
(see [Limitations](#limitations)). Fire/smoke and weapon alerts depend on the custom `.pt` models in
`backend/models/`, whose accuracy has not been measured in this repo.

## Architecture

```
                 ┌──────────────── backend (FastAPI, one process) ─────────────────┐
 camera/file ──► │ capture thread ─► latest frame ─► inference thread ─► tracks    │
 (RTSP/MP4)      │  (drops old,        (only 1)      (every FRAME_SKIP-th frame,   │
                 │   real-time pace)        │         shared YOLO + ByteTrack,     │
                 │                          │         zone analytics, cooldown)    │
                 │                          ▼                  │ events            │
                 │                    encoder thread ◄─ last tracks (EMA-smoothed) │
                 │                    (STREAM_FPS, JPEG)       ▼                   │
                 └──────────┬───────────────────────────── /event ─► alerts ───────┘
                            │ /video/{id}        /ws/alerts      /api/metrics
                            ▼                        ▼                 ▼
                       Next.js dashboard (Vercel): StreamTile (status, auto-reconnect, FPS badge),
                       alert feed, incidents
```

* Video never waits for inference: capture keeps only the newest frame, the encoder draws the last known
  tracks on it, inference runs at its own pace on a separate thread.
* One model instance, loaded and warmed up at startup, shared by all cameras. One pipeline per camera,
  regardless of how many browser tabs watch it.
* `?clean=1` on `/video/{id}` serves plain video; the browser then draws boxes from `/ws/detections/{id}`
  on a canvas. Tradeoff: smoother and exact alignment with the picture, but needs a second WebSocket
  per tile. Server-drawn boxes (default) work in any `<img>` and in saved snapshots. The dashboard uses
  clean mode in the fullscreen view.
* Zone polygons: `POST /api/camera/{id}/polygon` with `{"polygon": [[x,y],...]}` (0..1 fractions).
  Detections count only when the box's foot point is inside. The dashboard does not have a polygon
  editor yet; use the API.

## Run locally

```bash
cp .env.example .env                       # edit as needed
cd backend && pip install -r requirements.txt && uvicorn main:app --port 8000
cd frontend && npm install && NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
# add a camera (video file path on the backend machine, or rtsp://...)
curl -X POST localhost:8000/api/camera -H 'content-type: application/json' \
     -d '{"name":"Gate","zone":"outgate","video_path":"/path/to/clip.mp4"}'
```

Useful endpoints: `/api/health`, `/api/metrics` (capture FPS, inference ms, stream FPS, queue lag per camera),
`/api/detections/{id}`, `/video/{id}`, `/ws/alerts`.

## Tests and benchmark

```bash
cd backend && python -m pytest tests -q                      # polygon filtering, cooldown, scaling, zone rules
python scripts/benchmark.py clip.mp4 --zone corridor         # avg inference ms, FPS, detection counts
python scripts/measure_stream.py http://localhost:8000 CAMERA_ID 30 2   # delivered FPS, /health latency, 2 viewers
python scripts/export_onnx.py backend/models/yolov8n.pt 480  # optional ONNX export
```
Results: [RESULTS.md](RESULTS.md). Root-cause audit: [AUDIT.md](AUDIT.md). Old status notes are in `docs/archive/`.

## Configuration

Everything is an env var; see `.env.example` (FRAME_SKIP, IMGSZ, CONF, IOU, MODEL_PATH, STREAM_FPS, JPEG_QUALITY, ...).

## Deploy

See [docs/DEPLOY.md](docs/DEPLOY.md) (Render backend, Vercel frontend, env vars).

## Limitations

* **Fight / accident / fall / crowd** are rule-based on tracked boxes (proximity, motion, count over time).
  They will miss real events and fire on harmless ones. A production version needs a model fine-tuned on
  labelled clips (collect clips per event type, label with a tool such as CVAT or Roboflow, train a
  classifier on short tracked crops or pose sequences, evaluate on held-out footage).
* **Accuracy has not been measured.** No labelled ground truth is in the repo, so results report speed
  and detection counts only.
* COCO YOLOv8n will miss small, distant or occluded objects, and phones in particular.
* Render's free instance is CPU-only and sleeps when idle (cold start about a minute).
