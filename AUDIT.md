# Sentinel-AI audit (Step 0, before any code change)

Scope read: `backend/main.py`, `backend/worker/*`, `backend/zones/*`, `backend/engine.py`/`service.py` (not on the live stream path), `frontend/src/app/monitor/*`, stream components, `backend/Dockerfile`, `render.yaml`, `requirements.txt`.
Line numbers refer to commit `e852115`. Each finding says whether it was confirmed from source. Nothing here is a measured number; measurements go in `RESULTS.md`.

## Answers to the specific checks

| Question | Answer | Where |
|---|---|---|
| Is YOLO inference on every frame inside the same loop that reads the camera and encodes the MJPEG? | **Yes.** `generate_frames` does `cap.read()` -> `process_and_annotate()` (YOLO + fire + weapon, all synchronous) -> `imencode` -> `yield`, per frame. | `backend/main.py:1728`, `1754`, `1788-1791` |
| Does it block the event loop? | **Yes.** The generator is `async` but the inference, `cap.read()` and `imencode` are plain blocking calls, so one stream stalls the whole FastAPI server (every other stream, `/health`, the WebSocket). | `main.py:1701`, `1728`, `1529` |
| Frame queue that grows? | No queue. Instead each HTTP client gets its **own** `VideoCapture` and loop, so N viewers = N decoders + N inference loops on the same file. For a file the loop runs as fast as inference allows (then sleeps 33 ms on top), so latency does not build in a queue but video speed is tied to inference speed. | `main.py:1706`, `1805` |
| Models loaded per request/camera? | Mostly once (`ModelRegistry` singleton, `LiveStreamPipeline` singleton), **but**: `LiveStreamPipeline()` is constructed at import time (loads weapon/fire models during startup, slow cold start); and `main.py:282` was *meant* to spawn a separate worker subprocess per camera (`worker/worker.py`) with its own models - **but it never ran** (corrected after testing: `_sync_camera_worker` calls the undefined `_resolve_stream_source` at `main.py:252`, so it raised NameError before reaching `Popen`; reproduce: start the server at `e852115`, `POST /api/camera` with a valid `video_path` -> HTTP 500, log `NameError: name '_resolve_stream_source' is not defined`, `pgrep -f worker.py` empty; the camera is still saved). So the duplicate-inference claim is withdrawn; see 'Corrections' below. No warmup call anywhere. | `main.py:1698`, `1499`, `282`; `worker/worker.py:432-458` |
| imgsz / model size / half / device / conf / iou | Live stream: `imgsz=384, conf=0.35`, **no `iou`, no `classes`, no `half`, no `device`**. Zone model sizes come from the registry: classroom `yolov8m`, corridor/school_ground `yolov8s` (heavy for a CPU-only free instance). Separate worker uses model defaults (imgsz 640). Detectors: `imgsz=384`. | `main.py:1529`; `worker/registry.py:109-225`; `worker/worker.py:642`; `worker/detectors.py:354`, `533` |
| Box scale mismatch? | **Not in the live stream:** inference and drawing both use the original frame (no resize), so boxes are in the right coordinate space. The real accuracy problems are elsewhere (below). The displayed `<img>` uses `object-cover`, which **crops** the frame to fill a 16:9 tile, so boxes near edges can fall outside the visible area (display-side, not coordinate-math). | `main.py:1529-1546`; `MonitorClient.jsx:408-413` |
| `VideoCapture` buffering / real-time pace? | `CAP_PROP_BUFFERSIZE=1` and a 15 FPS hint are only set for RTSP, and for RTSP after open. Files get no pacing: read speed is whatever inference allows, not the file's native FPS. `CAP_PROP_FOURCC` set on a capture is a no-op for decoding. | `main.py:1415-1421` |
| JPEG quality / resolution / blocking | Quality 85 with `OPTIMIZE=1` (slower encode), no downscale, full source resolution sent. Placeholder stream is 1 FPS. | `main.py:1788-1791` |
| Fake telemetry | `fps` and `latency_ms` shown in the UI are **hard-coded** (`25.0`, `14.2`; defaults 25.0/14.5), not measured. | `main.py:1690-1691`, `835-836` |

## Root causes by user-reported problem

### 1. Detection inaccurate / flickering / wrong IDs
1. **No real tracking in the live path.** `track_id` is read from `boxes.id`, but the model is called as `model(frame)` (not `.track()`), so `boxes.id` is always `None` and the ID falls back to the box's **index in the result list** (`i + 1`). IDs change whenever detection order changes -> flicker and meaningless labels. `main.py:1529`, `1548`.
2. **Class filter is applied after inference and uses names, not IDs;** `classes=` and `iou=` are not passed to YOLO, so NMS and class pruning use defaults. `main.py:1529`, `1535-1539`.
3. **Per-frame, single-shot logic with no temporal confirmation** for fall (`pw > ph*1.25` on one frame, fixed 0.90 confidence), phone and fight; only a 4 s alert cooldown. A person walking sideways or sitting can trigger "fall". `main.py:1600-1612`.
4. **The zone processors in `backend/zones/*` (crowd polygons, outgate stopped-vehicle logic, EventCooldownManager, ByteTrack-style tracker) are not used by `/video/{id}`.** They run only in the separate subprocess worker, whose results are not drawn on the stream. So what the user sees and what the zone logic decides come from two different pipelines. `main.py:1507` vs `worker/worker.py:506-640`.
5. **No zone polygon filtering in the live stream**; any detection anywhere in the frame counts.
6. **No smoothing**; raw boxes every frame.
7. Weapon/fire models are custom `.pt` files whose real accuracy is unknown here; the fire path has a colour-heuristic ensemble (`worker/detectors.py:~415`). These produce false positives by nature. Needs a measured eval on labelled data, not a code fix.
8. Fight detection is a proximity heuristic (`worker/behaviours.py`), not a trained classifier. Must be labelled as heuristic.

### 2. Video freezes / lags / slow start
1. Inference + decode + encode serialised in one blocking loop on the event loop (see table). Throughput = 1 / (inference + encode); the file plays slower than real time and every other request stalls. `main.py:1728-1805`.
2. Per-viewer capture + inference (N tabs = N pipelines). The monitor grid opens one `<img>` per camera, and `MonitorClient.jsx` also renders a second `<img>` in other views (`:489`, `:542`), multiplying work. `main.py:1706`.
3. Extra subprocess worker per camera duplicates inference on the same CPU. `main.py:282`.
4. Slow start: `LiveStreamPipeline()` loads models at import (`main.py:1698`), no warmup so the first frame also pays lazy init; MJPEG begins only after the first full inference. Render free tier also sleeps after ~15 min idle.
5. Render free tier: 0.1 CPU-class share / 512 MB RAM (stated Render limits; confirm in your dashboard). `torch` + `ultralytics` + several `.pt` models + one extra process per camera can exceed 512 MB -> OOM restarts that look like "stuck". `requirements.txt` pins nothing (`ultralytics>=8`, `torch>=2.0`) and installs the full CUDA-less-or-not wheel set; image is large and slow to build.
6. `uploaded_videos/` and `test_videos/` are git-ignored (`.gitignore`), so the deployed container has none of the demo videos referenced in `data/cameras.json`; cameras fall back to the 1 FPS placeholder (`main.py:1463-1468`). On the deployed site, "video" is therefore either a placeholder or a very slow CPU stream.
7. Frontend `<img>` MJPEG has `onError` that just swaps in a static placeholder: no reconnect, no status, no cold-start message. `MonitorClient.jsx:408-413`.

### 3. Does not feel like a product
- Hard-coded FPS/latency in UI (above).
- 16 markdown status/debug files in the repo root, dead code (`worker/worker_old.py`, `test_rtsp_*.py` in root, `diagnose_school_ground.py`), two near-duplicate API routes (`api/test-video` and `api/test_video`, `camera-feed` and `camera_feed_proxy`), duplicate alert popups (`AlertPopup.jsx`, `AlertPopupNew.jsx`).
- `/api/camera-feed` buffers a whole MJPEG response with `arrayBuffer()` which never terminates for an infinite stream. `frontend/src/app/api/camera-feed/route.js:17-24`.
- No `/api/health`/`/api/metrics` (only `/health`); no visible stream state.

## Deployment / CORS checks
- CORS: `allow_origins` is `["*"]` when `FRONTEND_URL` is unset, combined with `allow_credentials=True` (browsers reject `*` with credentials for fetch). With `FRONTEND_URL` set it allows only that exact origin, so Vercel preview URLs will fail. `main.py:192-203`.
- Browser loads MJPEG straight from Render (`BACKEND_URL/video/..`), not through Vercel, so Vercel proxying is not the bottleneck; but `constants.js:5-10` has a hard-coded production fallback URL, and `NEXT_PUBLIC_*` values are baked at build time.
- WebSocket: `useWebSocket.js` already has exponential-backoff reconnect (good); it does not show a "waking server" state.
- `render.yaml` has `healthCheckPath: /health`, `PORT=8000` set manually, no `FRONTEND_URL`, no tuning env vars. `Dockerfile` installs `build-essential`, runs uvicorn with one worker (correct for in-memory state).

## What the user's hypotheses got right / wrong
- Confirmed: inference in the stream loop; hard blocking; heavy model; no frame dropping; no tracking IDs; no real-time pacing.
- Not confirmed: "boxes drawn on resized frame but coordinates from original" - no resize exists in the live path. We will add downscaling in Step 1 and must therefore add explicit scale-back (tested in Step 4).
- Not confirmed: unbounded queue growth - there is no queue.

## Limits that code cannot fix
- Render free tier is CPU-only and tiny. We will get a smooth video stream there, but detection will be low-FPS. Real-time multi-camera detection needs a paid CPU/GPU instance (needs the user's approval; none added).
- Fight/accident/crowd are heuristics. Reliable versions need a fine-tuned model and labelled clips.

---
## Corrections after testing (added after the code changes, original text above is unchanged)

* **The per-camera subprocess worker never ran.** `_sync_camera_worker` called `_resolve_stream_source`, which does not exist
  (`main.py` at `e852115`, line ~252), so every `POST /api/camera`, `/zone` and `/source` call saved the camera and then returned
  HTTP 500. Reproduced locally. The audit text above says the worker "duplicates inference"; in practice it was dead code, so the
  stalls came from the in-process stream alone. The in-process pipeline replaces it.
* **Measured, not just read from source** (RESULTS.md): the old server delivered 2-4 FPS and `/health` took about 1.5 s while a stream was playing.
* **WebSocket alert fan-out bug (new finding):** every `/ws/alerts` handler pulled from one shared `asyncio.Queue`, so with N dashboards open each alert reached only one of them (`main.py` `alerts_ws`). Fixed with a single broadcaster task.
* Models loaded at `e852115`: 3 at import (fire, weapon, gun) plus the zone model on first viewer = 4 loads in the log.
