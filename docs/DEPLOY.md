# Deploy

Targets already in use: frontend https://sentinel-ai-live.vercel.app/ (Vercel), backend https://sentinelai-backend-c81f.onrender.com (Render).
Nothing here adds paid services.

## 1. Render (backend)
1. Push this branch to `main` of github.com/jeromeyyy/Sentinel-AI (Render auto-deploys on push if it is connected, otherwise Manual Deploy).
2. Service settings: Environment **Docker**, Dockerfile path `backend/Dockerfile.lite` (torch-free, fits the free plan; use `backend/Dockerfile` only on a plan with >= 1 GB RAM, it needs torch and fire/weapon models), Docker context `.` (as in `render.yaml`). If your existing Render service already uses another Dockerfile path, check it before merging: render.yaml only applies to Blueprint-created services. Nothing was deployed or changed on Render by this repair; the Docker image build is checked only by the `docker-lite-smoke` GitHub Actions workflow if it has run (see its result on the Actions tab), Health check path `/api/health`.
3. Environment variables:

| Var | Value | Notes |
|---|---|---|
| `PORT` | `8000` | Dockerfile now reads `$PORT` |
| `FRONTEND_URL` | `https://sentinel-ai-live.vercel.app` | exact origin, no trailing slash. Several: comma separated |
| `CORS_ORIGIN_REGEX` | optional | only if you want Vercel preview URLs, e.g. `https://sentinel-ai-.*\.vercel\.app` |
| `MONGO_URL`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | as today | unchanged |
| `MODEL_PATH` | `models/yolov8n.pt` | |
| `IMGSZ` | `416` | 416-640 |
| `FRAME_SKIP` | `3` | |
| `CONF` / `IOU` | `0.35` / `0.5` | |
| `STREAM_FPS` | `12` | |
| `JPEG_QUALITY` | `70` | |
| `ENABLE_EXTRA_DETECTORS` | `false` | fire/smoke + weapon models; turn on only on a bigger instance |
| `PIPELINE_AUTOSTART` | `false` | camera starts when opened |
| `IDLE_STOP_SECONDS` | `120` | stop cameras nobody watches |

4. Demo videos are not in the repo, so a deployed backend has no video sources until you add RTSP/HTTP cameras (or upload a video through the dashboard). Uploaded files on the free plan are lost on restart.
5. **Memory (measured, sandbox, not yet on Render):** two runtimes exist. (a) torch + ultralytics (`backend/Dockerfile`, MODEL_PATH=models/yolov8n.pt): ~445 MB idle, ~665 MB with 2 cameras streaming: **will not fit Render's 512 MB free plan**. (b) torch-free (`backend/Dockerfile.lite`, `requirements-lite.txt`, MODEL_PATH=models/yolov8n.onnx, now the render.yaml default; the Dockerfile.lite build stage exports the .onnx from the tracked yolov8n.pt with torch, and the final image has no torch; the build stage was NOT test-built here, only the export script and runtime were run separately): ~210 MB idle, ~326 MB after 2 cameras with viewers, 12-15 fps delivered, in a clean venv with no torch or ultralytics (docs/benchmarks/torchfree_clean_venv.txt). That plausibly fits 512 MB but was NOT run on Render: watch Render's memory graph after deploy. The lite build has NO fire/smoke or weapon models (ENABLE_EXTRA_DETECTORS must stay false), so fire clips get person/vehicle detection only. The tracker in lite mode is `pipeline/bytetrack_lite.py`, a torch-free ByteTrack port, not Ultralytics' tracker.
6. **Incident thumbnails are OFF by default.** They turn on only when SNAPSHOT_SECRET (>=16 chars, stable across restarts) is set. When on, the image URL is an HMAC-signed *expiring bearer link* (SNAPSHOT_URL_TTL_S, default 3600): anyone holding the link can view that image until it expires. This is NOT a privacy guarantee: the refresh route /api/snapshot-link/{file} and the rest of the API are unauthenticated as in the original code, so anyone who can reach the API and knows an evt_*.jpg name can obtain a fresh link. Do not enable thumbnails on a public deployment with real camera feeds until API authentication exists. Snapshots older than SNAPSHOT_RETENTION_DAYS (7) are deleted at startup.


## Uploaded videos do not persist on free hosting
Videos uploaded through the UI (`/api/upload-video`) are written to the server's local disk (`backend/uploaded_videos`). Render's free web services have an ephemeral filesystem: files vanish on every restart, redeploy or spin-down, and the camera then reports `No video source found`. The UI now shows "Video source unavailable" with this note, and the setup wizard warns before upload. Re-upload the video, or use an RTSP/camera URL. No persistent storage was added (that would be a paid Render disk or external storage, which was not requested).

## Older backend compatibility
If the frontend is deployed before the backend, it detects a backend without `/api/health` and shows an "Older backend detected (degraded mode)" banner. Unavailable in that mode: FPS/latency badge, browser-drawn overlay, zone editing, signed snapshot links. Tested only in a local browser against the live old backend using a test-side CORS proxy; production CORS from the Vercel origin was not verified (the old backend's own config decides it).
