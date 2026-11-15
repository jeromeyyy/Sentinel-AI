# Results

All numbers are **measured**, on one machine: a 2 vCPU / 2 GB Linux sandbox, CPU only (no GPU), torch 2.14 CPU,
ultralytics 8.4.213. That is not the same as Render's free instance (see "Render" below), so absolute
numbers will differ there. Raw outputs are in `docs/benchmarks/`.

**What this does not show:** detection accuracy. There is no labelled ground truth, so detection counts
below are model outputs, not correct/incorrect scores.

## Clips used

| Clip | Source | Used for |
|---|---|---|
| 3 user-supplied videos (office surveillance with overlay captions; two home-camera news clips, one vertical 1080x1920) | Supplied by the user over WhatsApp. **Not in the repo and not published.** | Same-environment before/after, mapped to `fire_only` (see note) |
| people-detection, car-detection, classroom, one-by-one-person-detection (768x432 or 1920x1080) | Public clips from github.com/intel-iot-devkit/sample-videos (licence not verified; not redistributed here) | Speed and sanity checks for the zones the user clips did not cover |

Note on user clips: all three look like fire/smoke footage (a laptop fire in an office; smoke/fire in a home).
I mapped them to the `fire_only` zone. That mapping is my reading of the pictures, not something the user told me.
None of them is a corridor/outgate/school_ground/classroom clip. The user's school-zone clips were not available
(`/test_videos` is git-ignored), so **no school-zone behaviour has been validated on real school footage.**

## Before vs after: live stream (what a browser gets)

Before = commit `e852115` (original code). After = this branch. Same machine, same clip, measured with
`scripts/measure_stream.py` (30 s, or 20 s for user clips) while also polling `GET /health`.
The "before" server ran its default zone models (yolov8s for corridor) plus fire/weapon detectors;
the "after" server for the public clip ran yolov8n with extra detectors off, and for the user clips with extra detectors on (same as before).

| Case | Delivered FPS (before -> after) | Frame gap p50 (ms) | `/health` latency p50 / max (ms) |
|---|---|---|---|
| public people clip (12 fps source), 1 viewer | 3.6 -> 12.0 (= source rate) | 279 -> 66 | 57 / 1495 -> 30 / 109 |
| same, 2 viewers | 2.0 each -> 12.0 each | 497 -> 67 | 1489 / 1554 -> 30 / 89 |
| user clip 1 (office, 1920x1080, 25 fps) | 2.9 -> 15.0 (cap `STREAM_FPS`) | 340 -> 66 | 180 / 1624 -> 82 / 244 |
| user clip 2 (home, 1920x1080) | 2.9 -> 15.0 | 342 -> 66 | 185 / 696 -> 88 / 148 |
| user clip 3 (home, vertical 1080x1920) | 2.9 -> 14.9 | 349 -> 66 | 200 / 634 -> 89 / 127 |

* The old server was blocked while a stream ran: `/health` took about 1.5 s with two viewers. This is the measured
  version of the audit's source-based diagnosis.
* Time to first frame (server already up, model already loaded): 1.8 s -> 0.14 s on the public clip. Cold start
  (process boot + model load) was not separately timed.
* Detection latency from the pipeline's own metrics (`/api/metrics`, `queue_lag_ms`): about 30 ms for yolov8n alone,
  235-305 ms with the fire + weapon models on the 1080p user clips. Boxes are drawn on newer frames using each track's
  velocity (capped at 0.4 s) to hide this lag.
* Models per camera: before, the server loaded 4 YOLO models (fire, weapon, gun at import, plus the zone model on first
  viewer; log lines "Loading YOLO model"). The old subprocess worker never ran: `_sync_camera_worker` called an undefined
  function (NameError), so `POST /api/camera` returned 500 after saving. After: 1 shared model (+ the optional fire/weapon
  models), loaded once, warmed up.

## Offline benchmark (`scripts/benchmark.py`, yolov8n, imgsz 480, FRAME_SKIP 3)

| Clip | Zone | Avg inference (ms) | Processing FPS (x real time) | Detections (model output) | Unique track IDs | Heuristic events fired (before cooldown) |
|---|---|---|---|---|---|---|
| public people-detection | corridor | 29.4 | 98 (8.2x) | person 120 | 7 | fall_detected 5 (unverified) |
| public car-detection | outgate | 29.0 | 100 (8.0x) | car 7, bus 1 | car 4, bus 1 | none |
| public classroom (1080p) | classroom | 59.1 | 45 (1.5x) | person 1312 | 4 persons | none (no phone detections) |
| public one-by-one-person | school_ground | 30.0 | 96 (9.6x) | person 341 | 6 | none |
| user clip 1 (extra detectors on) | fire_only | 69.7 | 40 (1.6x) | fire 62, smoke 94, blade 2 | n/a | fire_smoke 104, weapon 1 |
| user clip 2 | fire_only | 70.2 | 38 (1.5x) | fire 61, smoke 21, gun 24, scissors 1 | n/a | fire_smoke 52, weapon 7 |
| user clip 3 (vertical) | fire_only | 79.3 | 31 (1.0x) | fire 270, smoke 270, gun 17 | n/a | fire_smoke 171, weapon 9 |

Things to check by eye, not conclusions:
* The weapon model reported "gun"/"blade" on all three fire clips. In the two frames I looked at per clip I saw no weapon.
  These are probably false positives, but I did not review the clips frame by frame. Treat the weapon alerts as unreliable
  until someone reviews them on labelled footage.
* `fall_detected` fired on the public corridor clip. It is an aspect-ratio rule; whether anyone fell there was not checked.
* Per-class counts are per inference cycle, so they scale with clip length and are not object counts.

ONNX: on this CPU the ONNX export of yolov8n was **slower** (44.5 ms vs 29.4 ms per cycle on the public people clip), so `.pt`
stays the default. `scripts/export_onnx.py` is there to try on the target machine (OpenVINO was not tried).

## Frontend check

Production build passes (`next build`). Loaded `/monitor` in headless Chrome against the local backend with two cameras:
no console errors, no failed requests, both streams live (`naturalWidth` 768), FPS/latency badge visible, camera tiles
show the measured values. Later browser checks are listed under "Latest verified state" below. Still not tested in a real browser:
auto-reconnect after a real backend restart, and the "waking server" banner against a sleeping Render instance.

## Unit tests

*Historical count from the original unit-test step; the current suite is 32 tests, see "Latest verified state".* `cd backend && python -m pytest tests -q` -> 24 passed: zone polygon filtering (incl. concave, foot vs centre), coordinate
scaling and clipping, EMA smoothing, `EventCooldownManager` (per-type cooldown, confidence bypass, per-camera isolation),
temporal confirmation, crowd/fight/phone/stopped-vehicle rules on synthetic tracks.

## Memory / Render

The backend process used about 497 MB RSS with one camera running and extra detectors off (torch + ultralytics + yolov8n).
**That is at Render's 512 MB free-plan limit**, so the free instance may be killed for running out of memory. I could not test on
Render. If it restarts repeatedly, the fix is a larger instance (paid; needs your approval) or a smaller footprint (no extra detectors,
`IMGSZ=416`, `PIPELINE_AUTOSTART=0`; these are already set in `render.yaml`).

## Memory (measured, 2 vCPU sandbox, CPU only, ENABLE_EXTRA_DETECTORS=0, PIPELINE_AUTOSTART=0)
| State | RSS |
|---|---|
| Server idle, 0 cameras, model loaded | ~445 MB |
| 2 cameras streaming (public clips, no viewers attached) | ~665 MB (~110 MB per camera) |

Idle RSS is dominated by the torch + ultralytics import. This is NOT proof of a 512 MB free tier fit; it suggests it will not fit without an ONNX/OpenVINO runtime. Not tested on Render.

## FPS definitions (/api/metrics)
`capture_fps` = frames read from source; `stream_fps` = JPEGs delivered to viewers; `inference_fps` = fresh detections per second (every FRAME_SKIP-th frame, ~4 fps for yolov8n on this CPU); `overlay_age_ms` = age of the tracks last drawn. The UI badge shows all three.

## Verification added later
- Alert thumbnail and incident modal were verified visually with an explicitly labeled SYNTHETIC fixture (not a real detection, fixture page not committed).
- Snapshot links are signed and expire; unsigned or expired requests get 403 (tests/test_snapshot_sig.py).

## Torch-free detector spike (onnxruntime + numpy + OpenCV; sandbox 2 vCPU, imgsz 480, 150 frames, person class only)
| Path | p50 ms/frame | peak RSS | person boxes (people clip) |
|---|---|---|---|
| ultralytics + torch (.pt) | 28.2 | ~404 MB | 49 |
| onnxruntime only (.onnx) | 27.7 | ~142 MB | 49 |
Classroom clip, onnx: 27.9 ms p50, 180 MB peak, 600 person boxes. Equal counts are agreement between two runtimes of the same weights, not accuracy. Raw: docs/benchmarks/onnx_torchfree_detector.jsonl. The process confirmed torch and ultralytics were not imported.
**Historical (superseded: the torch-free server is now wired in, see the next section).** At the time of this spike: not yet wired into the server: backend/pipeline/onnx_detector.py is the drop-in detector, but stream.py still uses SharedDetector, ultralytics' BYTETracker (imports torch), and the fire/weapon .pt models. A torch-free server needs a torch-free tracker and ONNX exports of those models; until then the full server RSS numbers above stand.

## Torch-free full server (wired in): measured
Clean venv with `requirements-lite.txt` (no torch, no ultralytics), MODEL_PATH=models/yolov8n.onnx, extra detectors off, autostart off, 2 vCPU sandbox: idle ~210 MB; after 2 cameras and viewers ~326 MB (peak 326 MB). Delivered 12.0 fps (2 viewers, 12 fps source) and 15.0 fps (30 fps source, capped); /api/health p50 ~64 ms. Raw: docs/benchmarks/torchfree_clean_venv.txt. Tracker: `bytetrack_lite.py` (torch-free ByteTrack port, unit-tested on synthetic motion only; not compared to Ultralytics IDs on real footage). Not verified on Render. No fire/smoke/weapon in this mode.

## ByteTrackLite vs Ultralytics BYTETracker (same ONNX detections, FRAME_SKIP 3, public Intel clips only)
scripts/compare_trackers.py, raw: docs/benchmarks/tracker_compare_public_clips.jsonl. people-detection: 8 vs 8 unique IDs, per-frame track count equal on 100% of 198 frames. classroom: 4 vs 4, 100% of 328. store-aisle: 11 (ultralytics) vs 14 (lite) unique IDs, count equal on 99.5% of 1307 frames. Every lite track box matched a reference box (IoU>0.5) and each lite ID mapped to a single reference ID. So the port behaves like the reference on these clips, with somewhat more ID churn on the busiest one. No ground truth: this shows agreement between two trackers, not tracking accuracy.

## Weapon-model keyframe review (bounded, 5 frames, user clips, not published)
All 5 saved weapon_detected frames were looked at by eye: three show a DVD/AV shelf (twice at the bottom-left, once a shelf under a TV), one the top of a cat photo, one a pan on a gas hob. None shows a visible weapon, so these 5 look like false alarms. Five frames is a tiny sample, not a reliability figure for the weapon model; school-zone accuracy remains unvalidated (no school footage supplied).

## Latest verified state (branch sentinel-ai-repair, local checks only)
All of these ran on a local backend (ONNX, 2 vCPU) and a local frontend. None ran on Render or Vercel production.
- Tests: 32 backend tests pass. `next build` compiles.
- Docker: GitHub Actions workflow `docker-lite-smoke` built `backend/Dockerfile.lite` and got model_loaded=true from /api/health (run 43702886052). The first run failed on an old pip in the export stage; fixed by upgrading pip. The full torch `backend/Dockerfile` was never built. Memory on Render is not measured.
- Fullscreen overlay: in a browser, the canvas drew a labelled person box over the video (public Intel sample clip, not accuracy).
- Zone editor: 4 clicks, Save, UI says "Zone saved", GET /api/camera/{id}/polygon returns the same 4 normalised points.
- Alert feed and incident dialog: tested with an explicitly SYNTHETIC fixture ("SYNTHETIC TEST FIXTURE, not a real detection"). The card, thumbnail and dialog render. No real incident was produced, so this is not detection evidence.
- Alerts socket: before the useWebSocket fix, 3 sockets opened and 2 stayed open on a dev page, with a "[WS] Error" console error. After the fix: 2 opened and 1 stayed open in dev (React StrictMode double mount); a production build (`next start`) opened 1 socket, kept it open, with no console messages and 1 backend connect.
- Camera status: tiles use /api/camera/{id}/health. An offline source shows "Video source unavailable"; LIVE labels, Online badges, counters, the top-bar badge and the empty-alerts text follow it.
- Older backend (no /api/health): degraded banner, no overlay/zone editing/metrics. Tested against the live old backend through a test-side CORS proxy only. CORS: a local run of the new backend answered a preflight carrying the Vercel production origin header correctly, and an unlisted origin was rejected. Actual CORS of the hosted old or new deployment from the Vercel origin was not tested; this does not mean it fails.
- Not verified: Render account/service/autodeploy, Render memory, school or outgate accuracy, classroom crop on real classroom footage.
