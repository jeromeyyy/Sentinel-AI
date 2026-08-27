from fastapi import FastAPI, WebSocket, Request, Response, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import logging
import importlib.util
import sys
import os
import subprocess
import io
import json
import glob
from pathlib import Path
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from reportlab.pdfgen import canvas
import cv2
import threading
import time
from typing import Dict, List, Optional
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from centralized .env in project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ============================================================================
# OPENCV FFMPEG CONFIGURATION - Enhanced H.264 Decoding
# ============================================================================
# Configure FFmpeg for better RTSP handling (keep warnings visible for debugging)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|"           # Use TCP (more reliable than UDP)
    "max_delay;500000|"              # 500ms max delay
    "reorder_queue_size;0|"          # Disable reordering (reduce lag)
    "buffer_size;1024000|"           # 1MB buffer
    "fflags;nobuffer|"               # Reduce buffering
    "flags;low_delay"                # Prioritize low latency
)

# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================
PORT = int(os.getenv("PORT", 8000))
MODULE = os.getenv("MODULE", "school")
LLM_API_BASE = os.getenv("LLM_API_BASE", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")  # Set to your Vercel domain in production
AUTO_DISCOVER_TEST_VIDEOS = os.getenv("AUTO_DISCOVER_TEST_VIDEOS", "0").lower() in ("1", "true", "yes", "on")

VIDEO_EXTENSIONS = ("*.mp4", "*.avi", "*.mov", "*.mkv", "*.webm")
ALLOWED_UPLOAD_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
ZONE_CYCLE = ["outgate", "corridor", "school_ground", "classroom"]
SUPPORTED_MODULES = ["home", "school", "office"]
DEFAULT_MODULE = MODULE  # Use env var

CUSTOM_ZONE_RUNTIME_MAP = {
    "workspace": "fire_only",
    "hallway": "fire_only",
    "meeting_hall": "fire_only",
    "living_room": "fire_only",
    "server_room": "corridor",
    "door": "corridor",
    "parking": "school_ground",
    "ground": "school_ground",
    "main_gate": "outgate",
}

FIRE_ONLY_ZONES = {"workspace", "hallway", "meeting_hall", "living_room", "fire_only"}

# Setup logging with colors
import sys
from datetime import datetime

class ColoredFormatter(logging.Formatter):
    """Colored log formatter."""
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname:8s}{self.RESET}"
        return super().format(record)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColoredFormatter(
    fmt='%(asctime)s %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
))
logging.basicConfig(level=logging.INFO, handlers=[handler])

# Create logger instance
logger = logging.getLogger(__name__)

# Import event engine and alert service (now in same directory)
try:
    from engine import process_event
    from service import trigger_alert
except ImportError:
    process_event = lambda event: {"incident": False}
    trigger_alert = lambda incident: {"alert": False, "summary": "(mock)"}

# Import database module
try:
    from db import (
        init_db,
        close_db,
        db,
        insert_incident,
        get_incidents,
        get_all_cameras,
        get_camera_by_id,
        upsert_camera,
        delete_camera_by_id,
    )
    DB_ENABLED = True
except ImportError as e:
    logging.warning(f"Database module not available: {e}")
    DB_ENABLED = False

# Import auth module
try:
    from auth import (
        get_google_auth_url, 
        exchange_code_for_tokens, 
        get_google_user_info,
        get_or_create_user,
        create_jwt_token,
        get_current_user,
        require_auth,
        validate_oauth_state,
        User,
        TokenResponse,
        FRONTEND_URL,
        JWT_EXPIRATION_HOURS,
    )
    AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"
except ImportError as e:
    logging.warning(f"Auth module not available: {e}")
from contextlib import asynccontextmanager

# Configure lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan event handler for startup and shutdown."""
    logging.info("=" * 60)
    logging.info("🎬 SentinelAI Backend Starting...")
    logging.info("=" * 60)
    
    # Initialize MongoDB connection
    if DB_ENABLED:
        logging.info("[STARTUP] Connecting to MongoDB Atlas...")
        db_connected = await init_db()
        if db_connected:
            logging.info("[STARTUP] MongoDB connection established")
            # Load cameras from database
            db_cameras = await get_all_cameras()
            for cam in db_cameras:
                camera_configs[cam["id"]] = cam
            logging.info(f"[STARTUP] Loaded {len(db_cameras)} cameras from MongoDB")
        else:
            logging.warning("[STARTUP] MongoDB connection failed - using in-memory storage")
    
    # Also sync test videos for development
    sync_camera_configs_from_test_videos(selected_module, force=True)
    logging.info(f"📦 Active module: {selected_module}")
    logging.info(f"📹 Discovered {len(camera_configs)} cameras")
    logging.info("✓ Backend ready! Listening for events...")
    logging.info("=" * 60)

    yield

    # Shutdown logic
    logging.info("[SHUTDOWN] Cleaning up resources...")
    _stop_all_camera_workers()
    if DB_ENABLED:
        try:
            await close_db()
            logging.info("[SHUTDOWN] MongoDB connection closed")
        except Exception as e:
            logging.error(f"[SHUTDOWN] Error closing MongoDB: {e}")
    logging.info("[SHUTDOWN] Server shutdown complete")

app = FastAPI(title="SentinelAI Backend", lifespan=lifespan)

# Configure CORS - use FRONTEND_URL env var in production
allowed_origins = ["*"] if FRONTEND_URL == "*" else [
    FRONTEND_URL,
    "http://localhost:3000",  # Local development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# IN-MEMORY STATE
# ============================================================================
alerts_history: List[Dict] = []
incidents: Dict[str, Dict] = {}
active_alert_clients: List[WebSocket] = []
alert_broadcast_queue: asyncio.Queue = asyncio.Queue()

# Camera/Zone configuration
camera_configs: Dict[str, Dict] = {}
selected_module: str = DEFAULT_MODULE
camera_worker_processes: Dict[str, subprocess.Popen] = {}

# Camera sync caching (prevents repeated discovery)
_camera_sync_cache: Dict[str, float] = {}  # module -> last_sync_timestamp
_CAMERA_SYNC_CACHE_TTL: float = 60.0  # Only re-sync every 60 seconds
_missing_test_videos_logged: bool = False


def _camera_worker_script() -> Path:
    return Path(__file__).resolve().parent / "worker" / "worker.py"


def _stop_camera_worker(camera_id: str) -> None:
    process = camera_worker_processes.pop(camera_id, None)
    if not process:
        return

    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _sync_camera_worker(camera_id: str, restart: bool = False) -> bool:
    camera = camera_configs.get(camera_id)
    if not camera or not camera.get("active", True):
        _stop_camera_worker(camera_id)
        return False

    raw_source = camera.get("rtsp_url") or camera.get("video_path") or camera.get("source")
    source = _resolve_stream_source(raw_source)
    if not source:
        _stop_camera_worker(camera_id)
        return False

    zone = _resolve_runtime_zone(camera.get("runtime_zone") or camera.get("zone") or "corridor")
    if zone not in ZONE_TYPES:
        zone = "corridor"

    existing = camera_worker_processes.get(camera_id)
    if existing and existing.poll() is None and not restart:
        return True

    _stop_camera_worker(camera_id)

    worker_script = _camera_worker_script()
    if not worker_script.exists():
        logging.error(f"[WORKER_START] Missing worker script: {worker_script}")
        return False

    command = [
        sys.executable,
        str(worker_script),
        zone,
        source,
        camera_id,
        "--no-preview",
    ]

    try:
        process = subprocess.Popen(command, cwd=str(worker_script.parent))
        camera_worker_processes[camera_id] = process
        logging.info(
            f"[WORKER_START] camera={camera_id} zone={zone} source={source} pid={process.pid}"
        )
        return True
    except Exception as exc:
        logging.error(f"[WORKER_START] Failed to start worker for {camera_id}: {exc}")
        return False


def _sync_active_camera_workers() -> None:
    for camera_id, camera in list(camera_configs.items()):
        if camera.get("active", True):
            _sync_camera_worker(camera_id)


def _stop_all_camera_workers() -> None:
    for camera_id in list(camera_worker_processes.keys()):
        _stop_camera_worker(camera_id)

# Comprehensive Zone definitions across School, Home, and Office environments
ZONE_TYPES = {
    # ── SCHOOL ─────────────────────────────────────────────────────────────
    "classroom": {
        "name": "Classroom",
        "events": ["mobile_phone_use", "exam_malpractice", "loitering_detected"],
        "description": "Classroom: Student tracking, mobile phone in-use detection, and exam monitoring",
    },
    "corridor": {
        "name": "Corridor / Hallway",
        "events": ["fight_suspected", "crowd_detected", "loitering_detected", "weapon_detected"],
        "description": "Hallway: Physical altercation monitoring, crowd flow, and loitering",
    },
    "school_ground": {
        "name": "School Ground / Playground",
        "events": ["fight_suspected", "weapon_detected", "crowd_detected"],
        "description": "Outdoor Ground: Altercation detection, perimeter weapon security, vehicle perimeter",
    },
    "outgate": {
        "name": "Outgate / Gate Area",
        "events": ["vehicle_detected", "gate_accident", "intrusion_detected"],
        "description": "Main Gate: Vehicle tracking, gate boundary crossings, and unauthorized entry",
    },
    "laboratory": {
        "name": "Science Laboratory",
        "events": ["fire_detected", "smoke_detected", "after_hours_presence", "restricted_area_entry"],
        "description": "Science Lab: Fire/smoke hazard surveillance and unauthorized after-hours access",
    },
    "exam_hall": {
        "name": "Examination Hall",
        "events": ["mobile_phone_use", "exam_malpractice"],
        "description": "Exam Hall: Strict mobile phone and unauthorized device detection",
    },

    # ── HOME ───────────────────────────────────────────────────────────────
    "entrance": {
        "name": "Front Entrance / Porch",
        "events": ["intrusion_detected", "loitering_detected", "vehicle_detected"],
        "description": "Front Entrance: Intrusion detection, package delivery, and dwell time monitoring",
    },
    "living_room": {
        "name": "Living Room",
        "events": ["fall_collapse", "intrusion_detected", "fire_detected"],
        "description": "Living Room: Fall/collapse detection, unexpected presence, and fire hazards",
    },
    "backyard": {
        "name": "Backyard / Garden",
        "events": ["intrusion_detected", "restricted_area_entry"],
        "description": "Backyard: Perimeter boundary crossings and animal/intruder detection",
    },
    "kitchen": {
        "name": "Kitchen",
        "events": ["fire_detected", "smoke_detected"],
        "description": "Kitchen: High-priority fire and smoke surveillance",
    },
    "garage": {
        "name": "Garage",
        "events": ["vehicle_detected", "after_hours_presence", "intrusion_detected"],
        "description": "Garage: Vehicle presence and unauthorized entry",
    },
    "bedroom": {
        "name": "Bedroom",
        "events": ["fall_collapse", "restricted_area_entry"],
        "description": "Bedroom: Fall monitoring and private room access restriction",
    },

    # ── OFFICE ─────────────────────────────────────────────────────────────
    "open_office": {
        "name": "Open Workspace",
        "events": ["crowd_detected", "mobile_phone_use", "after_hours_presence"],
        "description": "Open Workspace: Occupancy tracking, device activity, and crowding",
    },
    "server_room": {
        "name": "Server Room (High Security)",
        "events": ["restricted_area_entry", "after_hours_presence", "fire_detected"],
        "description": "Server Room: High-security restricted zone, strict zero-tolerance entry",
    },
    "meeting_room": {
        "name": "Conference / Meeting Room",
        "events": ["crowd_detected", "loitering_detected"],
        "description": "Meeting Room: Room occupancy, dwell times, and meetings",
    },
    "lobby": {
        "name": "Reception / Lobby",
        "events": ["loitering_detected", "intrusion_detected", "crowd_detected"],
        "description": "Reception / Lobby: Visitor traffic and dwell-time monitoring",
    },
    "cafeteria": {
        "name": "Cafeteria / Dining Hall",
        "events": ["crowd_detected", "fire_detected"],
        "description": "Cafeteria: High density crowd tracking and fire safety",
    },
    "executive_suite": {
        "name": "Executive Suite",
        "events": ["restricted_area_entry", "after_hours_presence"],
        "description": "Executive Area: Confidential access perimeter",
    },

    # Legacy & Auxiliary aliases
    "workspace": {
        "name": "Workspace",
        "events": ["fire_detected", "smoke_detected"],
        "description": "Office workspace fire and smoke monitoring",
    },
    "hallway": {
        "name": "Hallway",
        "events": ["fire_detected", "smoke_detected", "crowd_detected"],
        "description": "Office hallway monitoring",
    },
    "meeting_hall": {
        "name": "Meeting Hall",
        "events": ["crowd_detected", "fire_detected"],
        "description": "Meeting hall monitoring",
    },
    "all": {
        "name": "Multi-Zone (All Detectors)",
        "events": ["vehicle_detected", "fight_suspected", "crowd_detected", "mobile_phone_use", "fire_detected"],
        "description": "Run all zone detectors simultaneously for comprehensive monitoring",
    },
}


def _normalize_zone_id(zone: Optional[str]) -> str:
    if not zone:
        return "corridor"
    zone_clean = str(zone).strip().lower().replace(" ", "_")
    if zone_clean == "ground":
        return "school_ground"
    return zone_clean


def _resolve_runtime_zone(zone: Optional[str]) -> str:
    zone_id = _normalize_zone_id(zone)
    if zone_id in CUSTOM_ZONE_RUNTIME_MAP:
        return CUSTOM_ZONE_RUNTIME_MAP[zone_id]
    return zone_id


def _get_test_videos_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), 'test_videos'))


def _normalize_module(module: Optional[str]) -> str:
    if not module:
        return DEFAULT_MODULE
    module_clean = str(module).strip().lower()
    if module_clean == "workspace":
        module_clean = "office"
    return module_clean if module_clean in SUPPORTED_MODULES else DEFAULT_MODULE


def _module_test_videos_dir(module: Optional[str]) -> str:
    base_dir = _get_test_videos_dir()
    normalized = _normalize_module(module)
    return os.path.join(base_dir, normalized)


def _normalize_stream_source(video_path: Optional[str]) -> Optional[str]:
    if video_path is None:
        return None

    raw = str(video_path).strip()
    if not raw:
        return None

    if raw.lower().startswith("rstp://"):
        return f"rtsp://{raw[7:]}"

    return raw


def _resolve_video_path(video_path: Optional[str]) -> Optional[str]:
    """Resolve local video paths against common runtime locations."""
    raw = _normalize_stream_source(video_path)
    if not raw:
        return None

    if raw.lower().startswith(("rtsp://", "http://", "https://")):
        return raw

    if os.path.isabs(raw) and os.path.exists(raw):
        return raw

    backend_dir = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(backend_dir, ".."))
    test_videos_dir = _get_test_videos_dir()

    candidates = [
        os.path.abspath(raw),
        os.path.abspath(os.path.join(backend_dir, raw)),
        os.path.abspath(os.path.join(project_root, raw)),
        os.path.abspath(os.path.join(test_videos_dir, raw)),
        os.path.abspath(os.path.join(test_videos_dir, os.path.basename(raw))),
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return None


def _get_uploaded_videos_dir() -> str:
    upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploaded_videos"))
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _normalize_camera_id_from_video(video_path: str) -> str:
    stem = Path(video_path).stem.lower().strip()
    cleaned = ''.join(ch if ch.isalnum() else '_' for ch in stem)
    while '__' in cleaned:
        cleaned = cleaned.replace('__', '_')
    cleaned = cleaned.strip('_') or 'video'
    return f"cam_{cleaned}"


def _camera_id_for_module(video_path: str, module: str) -> str:
    base_camera = _normalize_camera_id_from_video(video_path).replace("cam_", "", 1)
    return f"cam_{module}_{base_camera}"


def _friendly_name_from_video(video_path: str) -> str:
    stem = Path(video_path).stem.replace('_', ' ').replace('-', ' ').strip()
    return stem.title() if stem else "Camera"


def _infer_zone_from_name(video_path: str, fallback_index: int) -> str:
    name = Path(video_path).stem.lower()
    keyword_map = {
        "outgate": ["outgate", "gate", "vehicle", "traffic", "parking", "accident"],
        "corridor": ["corridor", "hall", "hallway", "passage", "fight"],
        "school_ground": ["ground", "playground", "field", "yard", "campus", "weapon", "crowd"],
        "classroom": ["class", "classroom", "lecture", "exam"],
    }
    for zone, keywords in keyword_map.items():
        if any(keyword in name for keyword in keywords):
            return zone
    return ZONE_CYCLE[fallback_index % len(ZONE_CYCLE)]


def _infer_zone_from_path(video_path: str, fallback_index: int) -> str:
    zone_dirs = set(ZONE_TYPES.keys()) - {"all"}
    path_parts = [part.lower() for part in Path(video_path).parts]
    for part in path_parts:
        if part in zone_dirs:
            return part
    return _infer_zone_from_name(video_path, fallback_index)


def discover_test_videos(module: Optional[str] = None) -> List[Dict]:
    global _missing_test_videos_logged
    normalized_module = _normalize_module(module or selected_module)
    test_videos_dir = _get_test_videos_dir()
    module_dir = _module_test_videos_dir(normalized_module)
    videos: List[Dict] = []
    logging.info(f"[VIDEO_DISCOVERY] module={normalized_module} base_dir={test_videos_dir} module_dir={module_dir}")
    if not os.path.exists(test_videos_dir):
        if not _missing_test_videos_logged:
            logging.warning(f"[VIDEO_DISCOVERY] test_videos base directory not found: {test_videos_dir}")
            _missing_test_videos_logged = True
        return videos

    candidates: List[str] = []
    if os.path.isdir(module_dir):
        for ext in VIDEO_EXTENSIONS:
            candidates.extend(glob.glob(os.path.join(module_dir, "**", ext), recursive=True))
        logging.info(f"[VIDEO_DISCOVERY] found {len(candidates)} candidate files under module dir")
    if not candidates:
        logging.warning(
            f"[VIDEO_DISCOVERY] no files found under module={normalized_module}; falling back to root test_videos"
        )
        for ext in VIDEO_EXTENSIONS:
            candidates.extend(glob.glob(os.path.join(test_videos_dir, ext)))
    logging.info(f"[VIDEO_DISCOVERY] total candidates={len(candidates)}")

    for index, video_path in enumerate(sorted(candidates, key=lambda p: os.path.basename(p).lower())):
        abs_path = os.path.abspath(video_path)
        mapped_zone = _infer_zone_from_path(abs_path, index)
        camera_id = _camera_id_for_module(abs_path, normalized_module)
        logging.info(
            f"[VIDEO_DISCOVERY] file={abs_path} -> camera_id={camera_id} zone={mapped_zone} module={normalized_module}"
        )
        videos.append({
            "name": os.path.basename(abs_path),
            "path": abs_path,
            "camera_id": camera_id,
            "zone": mapped_zone,
            "module": normalized_module,
        })

    videos.sort(key=lambda item: item["name"].lower())
    return videos


def sync_camera_configs_from_test_videos(module: Optional[str] = None, force: bool = False) -> None:
    """Sync camera configs from test videos. Uses caching to avoid repeated discovery."""
    if not AUTO_DISCOVER_TEST_VIDEOS:
        return

    normalized_module = _normalize_module(module or selected_module)
    
    # Check cache - skip sync if recently done (unless forced)
    if not force:
        last_sync = _camera_sync_cache.get(normalized_module, 0)
        if time.time() - last_sync < _CAMERA_SYNC_CACHE_TTL:
            return  # Skip, cache is still valid
    
    videos = discover_test_videos(normalized_module)
    discovered_ids = set()
    logging.info(f"[CAMERA_SYNC] start module={normalized_module} videos={len(videos)}")

    for camera_id, config in list(camera_configs.items()):
        if config.get("source") == "test_video":
            del camera_configs[camera_id]

    for index, video in enumerate(videos):
        camera_id = video["camera_id"]
        discovered_ids.add(camera_id)

        existing = camera_configs.get(camera_id, {})
        zone = existing.get("zone") or video.get("zone") or _infer_zone_from_name(video["path"], index)
        active = existing.get("active", True)
        name = existing.get("name") or _friendly_name_from_video(video["path"])

        camera_configs[camera_id] = {
            **existing,
            "id": camera_id,
            "name": name,
            "zone": zone,
            "runtime_zone": _resolve_runtime_zone(zone),
            "video_path": video["path"],
            "active": active,
            "source": "test_video",
            "video_name": video["name"],
            "module": normalized_module,
            "model": _get_zone_model(zone),
        }
        logging.info(
            f"[CAMERA_SYNC] mapped camera={camera_id} name={name} video={video['name']} zone={zone} module={normalized_module}"
        )

    logging.info(
        f"[CAMERA_SYNC] completed module={normalized_module} total_cameras={len(camera_configs)}"
    )
    
    # Update cache timestamp
    _camera_sync_cache[normalized_module] = time.time()


# Video capture instances for streaming
video_captures: Dict[str, cv2.VideoCapture] = {}
video_locks: Dict[str, threading.Lock] = {}

# ============================================================================
# HEALTH CHECK
# ============================================================================
@app.get("/health")
def health():
    return {"status": "ok", "cameras": len(camera_configs), "incidents": len(incidents)}


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================
@app.get("/auth/google")
async def google_auth_redirect():
    """Redirect to Google OAuth consent screen."""
    if not AUTH_ENABLED:
        return JSONResponse({"error": "Auth is disabled"}, status_code=400)
    auth_url = get_google_auth_url()
    return JSONResponse({"auth_url": auth_url})


@app.get("/auth/google/login")
async def google_login_redirect(request: Request):
    """Direct redirect to Google OAuth (for browser navigation)."""
    if not AUTH_ENABLED:
        return JSONResponse({"error": "Auth is disabled"}, status_code=400)
    from fastapi.responses import RedirectResponse
    auth_url = get_google_auth_url(request=request)
    return RedirectResponse(url=auth_url)


@app.get("/auth/google/callback")
async def google_auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    """Handle Google OAuth callback and issue JWT."""
    from fastapi.responses import RedirectResponse
    
    frontend_target = os.getenv("FRONTEND_URL", "https://sentinel-ai-live.vercel.app")
    
    if not AUTH_ENABLED:
        return JSONResponse({"error": "Auth is disabled"}, status_code=400)
    
    if error:
        return RedirectResponse(url=f"{frontend_target}?auth_error={error}")
    
    if not code:
        return RedirectResponse(url=f"{frontend_target}?auth_error=no_code")
    
    # Validate OAuth CSRF state token
    if state and not validate_oauth_state(state):
        logging.warning("[AUTH] Invalid or expired OAuth state token")
        return RedirectResponse(url=f"{frontend_target}?auth_error=invalid_state")
    
    try:
        # Exchange code for tokens
        tokens = await exchange_code_for_tokens(code, request=request)
        access_token = tokens.get("access_token")
        
        if not access_token:
            return RedirectResponse(url=f"{frontend_target}?auth_error=no_access_token")
        
        # Get user info from Google
        google_user = await get_google_user_info(access_token)
        
        # Get or create user in our system (dynamic & database-backed)
        user = await get_or_create_user(google_user)
        
        # Create JWT token
        jwt_token = create_jwt_token(user)
        
        # Redirect to frontend with token
        return RedirectResponse(
            url=f"{frontend_target}/monitor?token={jwt_token}&user={user.name}"
        )
    except Exception as e:
        logging.error(f"OAuth callback error: {e}")
        return RedirectResponse(url=f"{frontend_target}?auth_error=callback_failed")


@app.get("/auth/me")
async def get_me(user: User = Depends(require_auth)):
    """Get current authenticated user info."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
    }


@app.get("/auth/verify")
async def verify_token(user: User = Depends(get_current_user)):
    """Verify if current token is valid. Returns user if valid, null if not."""
    if user:
        return {
            "valid": True,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "picture": user.picture,
                "role": user.role,
            }
        }
    return {"valid": False, "user": None}


# ============================================================================
# ZONE CONFIGURATION ENDPOINTS
# ============================================================================
@app.get("/api/zones")
def get_zones():
    """Get all zone type definitions."""
    return {"zones": ZONE_TYPES}


@app.get("/api/modules")
def get_modules():
    """Get supported modules and current selection."""
    return {"modules": SUPPORTED_MODULES, "selected_module": selected_module}


@app.get("/api/module/current")
def get_current_module():
    """Get the current module used for test video discovery."""
    return {"module": selected_module}


@app.post("/api/module")
async def set_current_module(data: dict):
    """Set current module (home/school/office) for camera discovery."""
    global selected_module
    selected_module = _normalize_module(data.get("module"))
    sync_camera_configs_from_test_videos(selected_module)
    return {
        "success": True,
        "module": selected_module,
        "cameras": [c for c in camera_configs.values() if c.get("source") != "test_video" or c.get("module") == selected_module],
    }


@app.get("/api/cameras")
async def get_cameras(request: Request, user: Optional[User] = Depends(get_current_user)):
    """Get all camera configurations with optional tenant filtering."""
    requested_module = request.query_params.get("module")
    active_module = _normalize_module(requested_module or selected_module)
    tenant_filter = user.tenant_id if user else request.query_params.get("tenant_id")
    
    # Load cameras from MongoDB if available
    if DB_ENABLED:
        try:
            db_cameras = await get_all_cameras(tenant_id=tenant_filter)
            for cam in db_cameras:
                if cam.get("id") not in camera_configs:
                    camera_configs[cam["id"]] = cam
        except Exception as e:
            logging.error(f"[DB] Failed to load cameras: {e}")
    
    sync_camera_configs_from_test_videos(active_module)
    for cam in camera_configs.values():
        zone_id = _normalize_zone_id(cam.get("zone", "corridor"))
        cam["zone"] = zone_id
        cam.setdefault("runtime_zone", _resolve_runtime_zone(zone_id))
        cam.setdefault("model", _get_zone_model(zone_id))
    
    visible_cameras = []
    for cam in camera_configs.values():
        # Match module for test videos
        if cam.get("source") == "test_video" and cam.get("module") != active_module:
            continue
        # If tenant filter is requested and cam has tenant_id, match it
        if tenant_filter and cam.get("tenant_id") and cam.get("tenant_id") != tenant_filter:
            continue
        
        cam_copy = dict(cam)
        cam_id = cam.get("id", "")
        telemetry = camera_live_telemetry.get(cam_id, {})
        cam_copy["people_count"] = telemetry.get("people_count", 0)
        cam_copy["detected_objects"] = telemetry.get("detected_objects", [])
        cam_copy["fps"] = telemetry.get("fps", 25.0)
        cam_copy["latency_ms"] = telemetry.get("latency_ms", 14.5)
        visible_cameras.append(cam_copy)
        
    return {"module": active_module, "cameras": visible_cameras}


@app.get("/api/camera/{camera_id}")
async def get_camera(camera_id: str):
    """Get specific camera configuration."""
    # Try MongoDB first
    if DB_ENABLED:
        try:
            db_cam = await get_camera_by_id(camera_id)
            if db_cam:
                camera_configs[camera_id] = db_cam
                return db_cam
        except Exception as e:
            logging.error(f"[DB] Failed to get camera {camera_id}: {e}")
    
    sync_camera_configs_from_test_videos(selected_module)
    if camera_id not in camera_configs:
        return JSONResponse({"error": "Camera not found"}, status_code=404)
    return camera_configs[camera_id]


@app.post("/api/camera/{camera_id}")
async def update_camera(camera_id: str, config: dict):
    """Update camera configuration."""
    sync_camera_configs_from_test_videos(selected_module)

    stream_source = _normalize_stream_source(
        config.get("video_path") or config.get("rtsp_url") or config.get("source")
    )
    if stream_source:
        config["video_path"] = stream_source
        if stream_source.lower().startswith("rtsp://"):
            config["rtsp_url"] = stream_source

    zone_value = config.get("zone")
    if zone_value is not None:
        normalized_zone = _normalize_zone_id(zone_value)
        if normalized_zone not in ZONE_TYPES:
            return JSONResponse({"error": f"Invalid zone: {zone_value}"}, status_code=400)
        config["zone"] = normalized_zone
        config["runtime_zone"] = _resolve_runtime_zone(normalized_zone)
        config["model"] = _get_zone_model(normalized_zone)

    if camera_id not in camera_configs:
        camera_configs[camera_id] = {"id": camera_id}
    
    camera_configs[camera_id].update(config)
    if "runtime_zone" not in camera_configs[camera_id]:
        stored_zone = camera_configs[camera_id].get("zone", "corridor")
        camera_configs[camera_id]["runtime_zone"] = _resolve_runtime_zone(stored_zone)
    if "model" not in camera_configs[camera_id]:
        camera_configs[camera_id]["model"] = _get_zone_model(camera_configs[camera_id].get("zone", "corridor"))

    # Persist to MongoDB
    if DB_ENABLED:
        try:
            await upsert_camera(camera_configs[camera_id])
            logging.info(f"[DB] Camera {camera_id} updated in MongoDB")
        except Exception as e:
            logging.error(f"[DB] Failed to update camera {camera_id}: {e}")

    logging.info(f"Updated camera config: {camera_id} -> {camera_configs[camera_id]}")
    return {"success": True, "camera": camera_configs[camera_id]}


@app.post("/api/camera/{camera_id}/zone")
async def set_camera_zone(camera_id: str, data: dict):
    """Set zone for a camera."""
    zone = _normalize_zone_id(data.get("zone"))
    if zone not in ZONE_TYPES:
        return JSONResponse({"error": f"Invalid zone: {zone}"}, status_code=400)
    
    if camera_id not in camera_configs:
        camera_configs[camera_id] = {"id": camera_id, "name": camera_id, "active": True}
    
    camera_configs[camera_id]["zone"] = zone
    camera_configs[camera_id]["runtime_zone"] = _resolve_runtime_zone(zone)
    camera_configs[camera_id]["model"] = _get_zone_model(zone)
    
    # Persist to MongoDB
    if DB_ENABLED:
        try:
            await upsert_camera(camera_configs[camera_id])
            logging.info(f"[DB] Camera {camera_id} zone updated in MongoDB")
        except Exception as e:
            logging.error(f"[DB] Failed to update camera zone {camera_id}: {e}")
    
    logging.info(f"Camera {camera_id} zone set to: {zone}")
    _sync_camera_worker(camera_id, restart=True)
    return {"success": True, "camera": camera_configs[camera_id]}


@app.post("/api/camera/{camera_id}/source")
async def update_camera_source(camera_id: str, data: dict):
    """
    Update camera video source (RTSP URL, HTTP stream, or video file).
    
    Payload:
    {
        "source": "rtsp://username:password@192.168.1.100:554/stream1",
        // OR
        "rtsp_url": "rtsp://...",
        // OR
        "video_path": "/path/to/video.mp4"
    }
    
    Returns:
    {
        "success": true,
        "camera": {...},
        "test_result": {
            "can_open": true,
            "resolution": "1920x1080",
            "fps": 25.0,
            "type": "RTSP"
        }
    }
    """
    if camera_id not in camera_configs:
        return JSONResponse(
            {"error": f"Camera '{camera_id}' not found. Use POST /api/camera to create it first."},
            status_code=404
        )
    
    # Get source from payload
    source = data.get("source") or data.get("rtsp_url") or data.get("video_path")
    
    if not source:
        return JSONResponse(
            {"error": "Missing video source. Provide 'source', 'rtsp_url', or 'video_path'"},
            status_code=400
        )
    
    # Normalize source
    normalized_source = _normalize_stream_source(source)
    
    if not normalized_source:
        return JSONResponse(
            {"error": f"Invalid video source: {source}"},
            status_code=400
        )
    
    # Determine source type
    is_rtsp = normalized_source.startswith("rtsp://")
    is_http = normalized_source.startswith(("http://", "https://"))
    is_file = not (is_rtsp or is_http)
    
    source_type = "RTSP" if is_rtsp else "HTTP" if is_http else "FILE"
    
    # Validate file existence
    if is_file:
        resolved = _resolve_video_path(normalized_source)
        if not resolved or not os.path.exists(resolved):
            return JSONResponse(
                {"error": f"Video file not found: {normalized_source}"},
                status_code=400
            )
        normalized_source = resolved
    
    # Test connection
    logger.info(f"[API] Testing video source for '{camera_id}': {normalized_source}")
    test_cap = cv2.VideoCapture(normalized_source, cv2.CAP_FFMPEG)
    
    test_result = {
        "can_open": test_cap.isOpened(),
        "type": source_type,
        "source": normalized_source
    }
    
    if test_cap.isOpened():
        width = int(test_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(test_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = test_cap.get(cv2.CAP_PROP_FPS)
        
        test_result.update({
            "resolution": f"{width}x{height}",
            "width": width,
            "height": height,
            "fps": fps if fps > 0 else None
        })
        test_cap.release()
        
        logger.info(f"[API] ✅ Video source test passed: {width}x{height} @ {fps}fps")
    else:
        test_cap.release()
        logger.error(f"[API] ❌ Video source test failed: Cannot open {normalized_source}")
        return JSONResponse(
            {
                "error": "Failed to open video source",
                "details": f"Cannot connect to {source_type} stream: {normalized_source}",
                "test_result": test_result
            },
            status_code=400
        )
    
    # Update camera config
    camera_configs[camera_id]["video_path"] = normalized_source
    
    if is_rtsp or is_http:
        camera_configs[camera_id]["rtsp_url"] = normalized_source
        camera_configs[camera_id]["source"] = normalized_source
    
    camera_configs[camera_id]["video_name"] = os.path.basename(normalized_source)
    camera_configs[camera_id]["source_type"] = source_type
    
    # Persist to MongoDB
    if DB_ENABLED:
        try:
            await upsert_camera(camera_configs[camera_id])
            logger.info(f"[DB] Camera {camera_id} source updated in MongoDB")
        except Exception as e:
            logger.error(f"[DB] Failed to update camera {camera_id}: {e}")
    
    logger.info(f"[API] ✅ Updated camera '{camera_id}' video source to: {normalized_source}")
    _sync_camera_worker(camera_id, restart=True)
    
    return {
        "success": True,
        "camera": camera_configs[camera_id],
        "test_result": test_result
    }


# ============================================================================
# DYNAMIC CAMERA CREATION ENDPOINT
# ============================================================================
@app.post("/api/camera")
async def create_camera(data: dict, user: Optional[User] = Depends(get_current_user)):
    """
    Create a new camera dynamically from video path and zone.
    """
    video_path = _normalize_stream_source(data.get("video_path") or data.get("rtsp_url") or data.get("source"))
    zone = _normalize_zone_id(data.get("zone"))
    name = data.get("name")
    
    # Validate inputs
    if not video_path:
        return JSONResponse({"error": "video_path is required"}, status_code=400)
    
    if not zone:
        return JSONResponse({"error": "zone is required"}, status_code=400)
    
    if zone not in ZONE_TYPES:
        return JSONResponse({"error": f"Invalid zone: {zone}. Valid zones: {list(ZONE_TYPES.keys())}"}, status_code=400)
    
    # Resolve source path (keep URLs untouched, resolve local files to absolute paths)
    is_remote_source = video_path.lower().startswith(("rtsp://", "http://", "https://"))
    if is_remote_source:
        resolved_path = video_path
    else:
        resolved_path = os.path.abspath(video_path)
        if not os.path.exists(resolved_path):
            # Check in test_videos directory
            test_video_path = os.path.join(_get_test_videos_dir(), os.path.basename(video_path))
            if os.path.exists(test_video_path):
                resolved_path = test_video_path
            else:
                return JSONResponse({"error": f"Video file not found: {video_path}"}, status_code=400)
    
    # Generate unique camera ID
    camera_id = _normalize_camera_id_from_video(resolved_path)
    
    # Handle duplicate IDs
    base_id = camera_id
    counter = 1
    while camera_id in camera_configs:
        camera_id = f"{base_id}_{counter}"
        counter += 1
    
    # Generate name if not provided
    if not name:
        name = _friendly_name_from_video(resolved_path)
    
    tenant_id = user.tenant_id if user else data.get("tenant_id", "school1")
    
    # Create camera config
    camera_config = {
        "id": camera_id,
        "name": name,
        "zone": zone,
        "runtime_zone": _resolve_runtime_zone(zone),
        "video_path": resolved_path,
        "active": True,
        "source": "dynamic",
        "video_name": os.path.basename(resolved_path),
        "model": _get_zone_model(zone),
        "tenant_id": tenant_id,
        "created_at": time.time(),
    }

    if is_remote_source:
        camera_config["rtsp_url"] = resolved_path
    
    camera_configs[camera_id] = camera_config
    
    # Persist to MongoDB
    if DB_ENABLED:
        try:
            await upsert_camera(camera_config)
            logging.info(f"[DB] Camera {camera_id} stored in MongoDB")
        except Exception as e:
            logging.error(f"[DB] Failed to store camera {camera_id}: {e}")
    
    logging.info(f"🎥 Created new camera: {camera_id} -> zone={zone}, video={os.path.basename(resolved_path)}")
    _sync_camera_worker(camera_id, restart=True)
    
    return {
        "success": True,
        "camera_id": camera_id,
        "camera": camera_config,
    }


@app.post("/api/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """Upload a local test video to backend storage and return its absolute path."""
    if not file.filename:
        return JSONResponse({"error": "Invalid file name"}, status_code=400)

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return JSONResponse(
            {"error": f"Unsupported video format: {ext}. Allowed: {sorted(ALLOWED_UPLOAD_EXTENSIONS)}"},
            status_code=400,
        )

    upload_dir = _get_uploaded_videos_dir()
    safe_stem = "".join(ch if ch.isalnum() else "_" for ch in Path(file.filename).stem).strip("_") or "video"
    unique_name = f"{safe_stem}_{int(time.time() * 1000)}{ext}"
    target_path = os.path.join(upload_dir, unique_name)

    try:
        content = await file.read()
        with open(target_path, "wb") as out:
            out.write(content)
    except Exception as exc:
        logging.error(f"Video upload failed: {exc}")
        return JSONResponse({"error": "Failed to store uploaded video"}, status_code=500)

    return {
        "success": True,
        "filename": unique_name,
        "video_path": os.path.abspath(target_path),
    }


def _get_zone_model(zone: str) -> str:
    """Get the model file for a zone."""
    normalized_zone = _normalize_zone_id(zone)
    runtime_zone = _resolve_runtime_zone(normalized_zone)

    if normalized_zone in FIRE_ONLY_ZONES or runtime_zone == "fire_only":
        return "fire_smoke_model.pt"

    zone_models = {
        "outgate": "yolov8n.pt",
        "corridor": "yolov8s.pt",
        "school_ground": "yolov8s.pt",
        "classroom": "yolov8m.pt",
    }
    return zone_models.get(runtime_zone, "yolov8n.pt")


@app.delete("/api/camera/{camera_id}")
async def delete_camera(camera_id: str):
    """Delete a camera."""
    if camera_id not in camera_configs:
        # Try loading from DB
        if DB_ENABLED:
            db_cam = await get_camera_by_id(camera_id)
            if not db_cam:
                return JSONResponse({"error": "Camera not found"}, status_code=404)
        else:
            return JSONResponse({"error": "Camera not found"}, status_code=404)
    
    if camera_id in camera_configs:
        config = camera_configs.pop(camera_id)
    
    # Delete from MongoDB
    if DB_ENABLED:
        try:
            deleted = await delete_camera_by_id(camera_id)
            if deleted:
                logging.info(f"[DB] Camera {camera_id} deleted from MongoDB")
        except Exception as e:
            logging.error(f"[DB] Failed to delete camera {camera_id}: {e}")
    
    logging.info(f"🗑️ Deleted camera: {camera_id}")
    
    # Clean up video capture if exists
    if camera_id in video_captures:
        try:
            video_captures[camera_id].release()
        except:
            pass
        del video_captures[camera_id]
    
    return {"success": True, "deleted": camera_id}


@app.get("/api/camera/{camera_id}/health")
async def camera_health(camera_id: str):
    """
    Check health status of a camera.
    Returns online if camera exists and has a working video source.
    """
    if camera_id not in camera_configs:
        return JSONResponse({"status": "offline", "error": "Camera not found"}, status_code=404)
    
    config = camera_configs[camera_id]
    
    # Check if camera has a video capture
    if camera_id in video_captures:
        cap = video_captures[camera_id]
        if cap is not None and cap.isOpened():
            return {
                "status": "online",
                "camera_id": camera_id,
                "zone": config.get("zone"),
                "active": config.get("active", True),
            }
    
    # Try to check if video source is accessible
    video_path = config.get("video_path") or config.get("source")
    if video_path in ("test_video", "rtsp"):
        video_path = None
    resolved_video_path = _resolve_video_path(video_path)
    if resolved_video_path:
        return {
            "status": "online",
            "camera_id": camera_id,
            "zone": config.get("zone"),
            "active": config.get("active", True),
            "source": "file",
        }
    
    return {
        "status": "offline",
        "camera_id": camera_id,
        "zone": config.get("zone"),
        "active": config.get("active", True),
        "reason": "No video source found",
    }


@app.get("/api/system/health")
async def system_health():
    """
    Get overall system health status.
    """
    online_cameras = 0
    total_cameras = len(camera_configs)
    
    for cam_id, config in camera_configs.items():
        if cam_id in video_captures:
            cap = video_captures[cam_id]
            if cap is not None and cap.isOpened():
                online_cameras += 1
        else:
            video_path = config.get("source") or config.get("video_path")
            if video_path and os.path.exists(video_path):
                online_cameras += 1
    
    ws_connected = len(active_alert_clients)
    
    return {
        "status": "healthy" if online_cameras > 0 or total_cameras == 0 else "degraded",
        "cameras": {
            "total": total_cameras,
            "online": online_cameras,
            "offline": total_cameras - online_cameras,
        },
        "websocket_clients": ws_connected,
        "incidents_count": len(incidents),
        "alerts_count": len(alerts_history),
        "module": selected_module,
    }


# ============================================================================
# TEST VIDEO DISCOVERY
# ============================================================================
@app.get("/api/test_videos")
def list_test_videos(request: Request):
    """List available test videos for a module from test_videos/<module> folder."""
    requested_module = request.query_params.get("module")
    active_module = _normalize_module(requested_module or selected_module)
    test_videos_dir = _module_test_videos_dir(active_module)
    videos = discover_test_videos(active_module)
    return {"module": active_module, "videos": videos, "directory": test_videos_dir}


# ============================================================================
# VIDEO STREAMING ENDPOINTS
# ============================================================================
def get_video_capture(camera_id: str) -> Optional[cv2.VideoCapture]:
    """
    Get OpenCV VideoCapture with RTSP optimization and error recovery.
    
    Supports:
    - RTSP streams (rtsp://)
    - HTTP/HTTPS streams (http://, https://)
    - Local video files (absolute paths)
    
    Returns None if:
    - Camera not found in configs
    - No video source configured
    - Failed to open video source
    """
    
    if camera_id not in camera_configs:
        logger.error(f"[VIDEO_CAPTURE] ❌ Camera '{camera_id}' not found in configs")
        return None
    
    config = camera_configs[camera_id]
    camera_name = config.get("name", camera_id)
    
    # Get video source (try multiple fields)
    video_source = (
        config.get("rtsp_url") or 
        config.get("video_path") or 
        config.get("source") or 
        None
    )
    
    # Normalize and validate source
    normalized_source = _normalize_stream_source(video_source)
    
    if not normalized_source:
        logger.error(
            f"[VIDEO_CAPTURE] ❌ No video source configured for '{camera_name}' (ID: {camera_id})\n"
            f"              Expected one of: rtsp_url, video_path, or source\n"
            f"              Camera config: {config}"
        )
        return None
    
    # Determine source type
    is_rtsp = normalized_source.startswith("rtsp://")
    is_http = normalized_source.startswith(("http://", "https://"))
    is_file = not (is_rtsp or is_http)
    
    source_type = "RTSP" if is_rtsp else "HTTP" if is_http else "FILE"
    
    # Validate file existence for local files
    if is_file:
        resolved_path = _resolve_video_path(normalized_source)
        if not resolved_path or not os.path.exists(resolved_path):
            logger.error(
                f"[VIDEO_CAPTURE] ❌ Video file not found: {normalized_source}\n"
                f"              Camera: '{camera_name}' (ID: {camera_id})"
            )
            return None
        normalized_source = resolved_path
    
    logger.info(
        f"[VIDEO_CAPTURE] 🎥 Opening '{camera_name}' (ID: {camera_id})\n"
        f"              Type: {source_type}\n"
        f"              Source: {normalized_source}"
    )
    
    # Open with FFmpeg backend explicitly
    cap = cv2.VideoCapture(normalized_source, cv2.CAP_FFMPEG)
    
    if not cap.isOpened():
        logger.error(
            f"[VIDEO_CAPTURE] ❌ Failed to open '{camera_name}'\n"
            f"              Type: {source_type}\n"
            f"              Source: {normalized_source}\n"
            f"              Possible causes:\n"
            f"              - RTSP: Wrong URL, auth failed, camera offline, network issue\n"
            f"              - FILE: Corrupt file, unsupported codec, wrong path\n"
            f"              - HTTP: Server down, wrong URL, network issue"
        )
        return None
    
    # Apply RTSP optimizations (must be set AFTER opening)
    if is_rtsp:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffering
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'H264'))
        cap.set(cv2.CAP_PROP_FPS, 15)  # Limit to 15 FPS
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)  # 10s open timeout
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)  # 10s read timeout
        logger.info(f"[VIDEO_CAPTURE] ⚙️  Applied RTSP optimizations (TCP transport, H.264)")
    
    # Get actual stream properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    logger.info(
        f"[VIDEO_CAPTURE] ✅ Successfully opened '{camera_name}'\n"
        f"              Resolution: {width}x{height}\n"
        f"              FPS: {fps if fps > 0 else 'Unknown'}"
    )
    
    return cap


def create_placeholder_frame(camera_id: str):
    """Create a placeholder frame when no video source is available."""
    # Create dark placeholder
    import numpy as np
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (30, 30, 30)  # Dark gray
    
    config = camera_configs.get(camera_id, {})
    
    # Add text
    cv2.putText(frame, "No Video Source", (180, 220), cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)
    cv2.putText(frame, f"Camera: {config.get('name', camera_id)}", (160, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 80), 1)
    cv2.putText(frame, f"Zone: {config.get('zone', 'Not configured')}", (180, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)
    
    return frame


async def generate_placeholder_frames(camera_id: str):
    """Generate placeholder frames for cameras with no video source."""
    config = camera_configs.get(camera_id, {})
    camera_name = config.get("name", camera_id)
    
    logger.warning(f"[VIDEO_STREAM] {camera_name}: Streaming placeholder (no video source)")
    
    placeholder = create_placeholder_frame(camera_id)
    _, buffer = cv2.imencode('.jpg', placeholder)
    frame_bytes = buffer.tobytes()
    
    while True:
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        await asyncio.sleep(1.0)  # 1 FPS for placeholder


# ============================================================================
# REAL-TIME STREAM INFERENCE & OVERLAY PIPELINE
# ============================================================================

from worker.registry import ModelRegistry, ZONE_MODEL_CONFIGS, COCO_CLASSES
from worker.detectors import FireSmokeDetector, WeaponDetector, PoseDetector
from worker.behaviours import PhoneUseDetector, FightAltercationDetector, FireSmokeTracker

camera_live_telemetry: Dict[str, Dict] = {}

class LiveStreamPipeline:
    """Real-time multi-model vision inference and visual annotator for MJPEG streams."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.registry = ModelRegistry()
        self.fire_detector = FireSmokeDetector(self.registry)
        self.weapon_detector = WeaponDetector(self.registry)
        self.phone_detector = PhoneUseDetector(min_duration=1.5)
        self.fight_detector = FightAltercationDetector(proximity_threshold=90.0, min_frames=2)
        self.fire_tracker = FireSmokeTracker(min_confirmation_frames=2, cooldown_seconds=6.0)
        self._last_alert_time = {}
        self._initialized = True
        logger.info("LiveStreamPipeline initialized with multi-model inference and HUD overlay")

    def process_and_annotate(self, frame, camera_id: str, zone: str, module: str = "school"):
        now = time.time()
        annotated = frame.copy()
        h, w = frame.shape[:2]
        
        detections = []
        persons = []
        phones = []
        threats = []

        # Security Target Classes (no clutter from furniture or random items)
        ALLOWED_CLASSES = {
            "person", "cell phone", "phone",
            "knife", "scissors", "gun", "weapon", "blade",
            "car", "motorcycle", "bus", "truck",
            "backpack", "handbag", "suitcase"
        }

        # 1. Primary YOLO zone model detection (optimized with imgsz=384 for ultra-fast 30fps streaming)
        try:
            zone_model = self.registry.get_zone_model(zone)
            if zone_model is not None:
                results = zone_model(frame, verbose=False, imgsz=384, conf=0.35)
                for res in results:
                    boxes = res.boxes
                    if boxes is None:
                        continue
                    for i in range(len(boxes)):
                        cls_id = int(boxes.cls[i].item())
                        conf = float(boxes.conf[i].item())
                        xyxy = boxes.xyxy[i].cpu().numpy().astype(int).tolist()
                        class_name = COCO_CLASSES.get(cls_id, f"obj_{cls_id}").lower()
                        
                        # Filter to security-critical objects only (skip couch, chair, table, etc.)
                        if class_name not in ALLOWED_CLASSES:
                            continue

                        det = {
                            "class": class_name,
                            "confidence": conf,
                            "bbox": xyxy,
                            "track_id": int(boxes.id[i].item()) if (boxes.id is not None) else (i + 1)
                        }
                        detections.append(det)
                        
                        if class_name == "person":
                            persons.append(det)
                        elif class_name in ("cell phone", "phone"):
                            phones.append(det)
        except Exception as e:
            logger.debug(f"Primary detector error: {e}")

        # 2. Fire & Smoke Ensemble Detection (Chromatic + Deep model)
        try:
            fire_results = self.fire_detector.detect(frame)
            for fd in fire_results:
                f_det = {
                    "class": fd["class_name"],
                    "confidence": fd["confidence"],
                    "bbox": fd["bbox"],
                    "track_id": None
                }
                detections.append(f_det)
                threats.append({
                    "event_type": "fire_detected" if fd["class_name"] == "fire" else "smoke_detected",
                    "confidence": fd["confidence"],
                    "bbox": fd["bbox"],
                    "priority": "critical" if fd["class_name"] == "fire" else "high",
                })
        except Exception as e:
            logger.debug(f"Fire detector error: {e}")

        # 3. Weapon Ensemble Detection
        if self.weapon_detector.is_available:
            try:
                weapon_results = self.weapon_detector.detect(frame)
                for wd in weapon_results:
                    detections.append({
                        "class": wd["class_name"],
                        "confidence": wd["confidence"],
                        "bbox": wd["bbox"],
                        "track_id": None
                    })
                    threats.append({
                        "event_type": "weapon_detected",
                        "confidence": wd["confidence"],
                        "bbox": wd["bbox"],
                        "priority": "critical"
                    })
            except Exception as e:
                logger.debug(f"Weapon detector error: {e}")

        # 4. Behavioral engines
        # Fall detection (horizontal body geometry on ground)
        for p in persons:
            px1, py1, px2, py2 = p["bbox"]
            pw = px2 - px1
            ph = py2 - py1
            if pw > ph * 1.25 and p["confidence"] > 0.55 and py2 > h * 0.35:
                p["is_fall"] = True
                threats.append({
                    "event_type": "fall_detected",
                    "confidence": 0.90,
                    "bbox": p["bbox"],
                    "priority": "critical"
                })

        # Phone use
        if phones and persons:
            phone_events = self.phone_detector.update(persons, phones, timestamp=now)
            for pe in phone_events:
                threats.append({
                    "event_type": "mobile_phone_use",
                    "confidence": pe["confidence"],
                    "bbox": pe["bbox"],
                    "priority": "medium"
                })

        # Fight Altercation
        if len(persons) >= 2:
            fight_events = self.fight_detector.update(persons, timestamp=now)
            for fe in fight_events:
                threats.append({
                    "event_type": "fight_suspected",
                    "confidence": fe["confidence"],
                    "bounding_boxes": fe.get("bounding_boxes", []),
                    "priority": "high"
                })

        # 5. Draw crisp bounding boxes with sleek background tags
        for det in detections:
            cname = det["class"].lower()
            conf = det["confidence"]
            x1, y1, x2, y2 = det["bbox"]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)

            if "fire" in cname:
                color = (0, 45, 255) # Intense Fire Red
                label = f"FIRE {int(conf*100)}%"
            elif "smoke" in cname:
                color = (0, 150, 255) # Amber Smoke
                label = f"SMOKE {int(conf*100)}%"
            elif "person" in cname:
                if det.get("is_fall"):
                    color = (0, 0, 255) # Red Fall Warning
                    label = f"FALL DETECTED ({int(conf*100)}%)"
                else:
                    color = (255, 220, 0) # Cyan/Neon Blue
                    tid = det.get("track_id", 1)
                    label = f"Person #{tid} ({int(conf*100)}%)"
            elif "phone" in cname:
                color = (255, 110, 180) # Purple
                label = f"Phone {int(conf*100)}%"
            elif any(w_word in cname for w_word in ("gun", "weapon", "knife", "scissors", "blade")):
                color = (0, 0, 255) # Warning Red
                label = f"WEAPON {int(conf*100)}%"
            else:
                color = (0, 215, 255) # Gold
                label = f"{cname.title()} {int(conf*100)}%"

            # Main bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            # Pill label tag with rounded background look
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 2)
            label_y1 = max(0, y1 - th - 8)
            label_y2 = max(th + 8, y1)
            label_x2 = min(w, x1 + tw + 10)
            
            tag_overlay = annotated.copy()
            cv2.rectangle(tag_overlay, (x1, label_y1), (label_x2, label_y2), (15, 15, 15), -1)
            cv2.rectangle(tag_overlay, (x1, label_y1), (label_x2, label_y2), color, 1)
            annotated = cv2.addWeighted(tag_overlay, 0.85, annotated, 0.15, 0)
            
            cv2.putText(annotated, label, (x1 + 5, label_y2 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

        # 6. Compute live telemetry
        people_count = len(persons)
        detected_classes = list(set(d["class"] for d in detections))
        camera_live_telemetry[camera_id] = {
            "people_count": people_count,
            "detected_objects": detected_classes,
            "fps": 25.0,
            "latency_ms": 14.2,
            "last_updated": now,
        }

        return annotated, people_count, detected_classes, threats


live_stream_pipeline = LiveStreamPipeline()


async def generate_frames(camera_id: str):
    """
    Generate MJPEG frames with real-time model inference, bounding box overlay,
    and automatic event broadcasting.
    """
    cap = get_video_capture(camera_id)
    
    if not cap:
        logger.warning(f"[VIDEO_STREAM] {camera_id}: No valid source, streaming placeholder")
        async for frame_bytes in generate_placeholder_frames(camera_id):
            yield frame_bytes
        return
    
    consecutive_errors = 0
    max_consecutive_errors = 10
    total_frames = 0
    corrupted_frames = 0
    last_reconnect = 0
    
    config = camera_configs.get(camera_id, {})
    camera_name = config.get("name", camera_id)
    zone = config.get("zone", "unknown")
    
    logger.info(f"[VIDEO_STREAM] Starting real-time AI stream for {camera_name} ({camera_id})")
    
    try:
        while True:
            ret, frame = cap.read()
            
            # Loop video file seamlessly if reaching the end
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()

            if not ret or frame is None or frame.size == 0:
                consecutive_errors += 1
                corrupted_frames += 1
                
                if consecutive_errors >= max_consecutive_errors:
                    cap.release()
                    await asyncio.sleep(1)
                    cap = get_video_capture(camera_id)
                    if not cap:
                        async for frame_bytes in generate_placeholder_frames(camera_id):
                            yield frame_bytes
                        return
                    consecutive_errors = 0
                    last_reconnect += 1
                
                await asyncio.sleep(0.033)
                continue
            
            consecutive_errors = 0
            total_frames += 1
            now = time.time()
            
            # Run Live Vision Pipeline (Inference + Bounding Boxes + Telemetry)
            annotated_frame, people_count, detected_objs, threats = live_stream_pipeline.process_and_annotate(
                frame, camera_id, zone, selected_module
            )
            
            # Auto-emit threats to WebSocket & Active Alerts
            for threat in threats:
                ev_type = threat.get("event_type", "unknown")
                last_t = live_stream_pipeline._last_alert_time.get((camera_id, ev_type), 0)
                if now - last_t > 4.0:  # 4s cooldown
                    live_stream_pipeline._last_alert_time[(camera_id, ev_type)] = now
                    event_id = f"EVT_{int(now * 1000)}"
                    event_payload = {
                        "event_id": event_id,
                        "tenant_id": config.get("tenant_id", "default"),
                        "camera_id": camera_id,
                        "zone": zone,
                        "event_type": ev_type,
                        "confidence": threat.get("confidence", 0.88),
                        "timestamp": now,
                        "bounding_boxes": [threat.get("bbox")] if threat.get("bbox") else threat.get("bounding_boxes", []),
                        "metadata": {"live_stream": True, "detected_objects": detected_objs}
                    }
                    asyncio.create_task(receive_event(event_payload))

            # Add HUD Overlay (Zone + Live status + People counter)
            final_frame = add_frame_overlay(annotated_frame, camera_id, zone, people_count)
            
            # Encode frame to JPEG
            try:
                encode_params = [
                    cv2.IMWRITE_JPEG_QUALITY, 85,
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1
                ]
                ret_encode, buffer = cv2.imencode('.jpg', final_frame, encode_params)
                if not ret_encode:
                    continue
                
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + 
                    buffer.tobytes() + 
                    b'\r\n'
                )
            except Exception as e:
                logger.error(f"[VIDEO_STREAM] Encoding error: {e}")
                continue
            
            await asyncio.sleep(0.033)  # ~30 FPS
    
    except asyncio.CancelledError:
        logger.info(f"[VIDEO_STREAM] Stream cancelled for {camera_name}")
    except Exception as e:
        logger.error(f"[VIDEO_STREAM] Unexpected stream error: {e}")
    finally:
        if cap:
            cap.release()


def add_frame_overlay(frame, camera_id: str, zone: str, people_count: int = 0):
    """Add HUD header bar, live dot, and dynamic people counter to frame."""
    h, w = frame.shape[:2]
    
    # Semi-transparent top HUD bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 36), (10, 10, 15), -1)
    frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)
    
    # Zone label
    zone_label = ZONE_TYPES.get(zone, {}).get("name", zone.title())
    cv2.putText(frame, zone_label, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    
    # People count indicator
    if people_count > 0:
        ppl_text = f"PPL: {people_count}"
        cv2.putText(frame, ppl_text, (w // 2 - 40, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 235, 255), 2, cv2.LINE_AA)
    
    # Live indicator with red dot
    cv2.circle(frame, (w - 75, 18), 5, (0, 0, 255), -1)
    cv2.putText(frame, "LIVE", (w - 62, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)
    
    # Timestamp
    timestamp = time.strftime("%H:%M:%S")
    return frame


@app.get("/video/{camera_id}")
async def video_feed(camera_id: str):
    """MJPEG stream for a specific camera with enhanced error recovery."""
    return StreamingResponse(
        generate_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# Legacy camera feed endpoint
@app.get("/camera_feed")
async def camera_feed():
    """Legacy single camera feed endpoint."""
    return StreamingResponse(
        generate_frames("cam_outgate"),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/snapshot/{filename}")
def get_snapshot(filename: str):
    """Serve snapshot image for WhatsApp media attachments."""
    snapshot_path = _PROJECT_ROOT / "backend" / "snapshots" / filename
    
    if not snapshot_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "Snapshot not found"}
        )
    
    return FileResponse(
        path=str(snapshot_path),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )


# ============================================================================
# EVENT INGEST
# ============================================================================
@app.post("/event")
async def receive_event(event: dict, request: Request = None):
    camera_id = event.get('camera_id', 'unknown')
    zone = event.get('zone', 'unknown')
    event_type = event.get('event_type', 'unknown')
    detected_by_zone = event.get('detected_by_zone', zone)
    confidence = event.get('confidence', 0.0)
    event_id = event.get('event_id', 'n/a')
    timestamp = event.get('timestamp', 'n/a')
    boxes_count = len(event.get('bounding_boxes', []) or [])

    # Validate event schema
    required_fields = ['event_id', 'camera_id', 'zone', 'event_type', 'confidence', 'timestamp']
    missing = [f for f in required_fields if f not in event]
    if missing:
        logging.warning(
            f"[EVENT_SCHEMA_INVALID] event_id={event_id} camera={camera_id} "
            f"missing_fields={missing}"
        )

    logging.info(
        "[EVENT_RX_ACCEPT] "
        f"event_id={event_id} camera={camera_id} zone={zone} detected_by_zone={detected_by_zone} "
        f"event_type={event_type} confidence={confidence:.2f} boxes={boxes_count} ts={timestamp}"
    )
    
    result = process_event(event)
    suspicion_score = float(result.get("suspicion_score", 0.0) or 0.0)
    priority = result.get("priority", "n/a")
    timeline = result.get("timeline", {}) or {}
    frames_considered = timeline.get("frames_considered", 0)

    if result.get("incident"):
        alert = trigger_alert(result)
        incident_id = event.get("event_id")
        incidents[incident_id] = {"event": event, "alert": alert}
        alerts_history.append({"event": event, "alert": alert})

        # Insert incident into MongoDB
        if DB_ENABLED:
            incident_doc = {
                "event_id": event_id,
                "tenant_id": event.get("tenant_id", "default"),
                "camera_id": camera_id,
                "zone": zone,
                "event_type": event_type,
                "confidence": confidence,
                "severity_score": suspicion_score,
                "timestamp": timestamp,
                "snapshot_path": event.get("snapshot_path"),
                "summary": alert.get("summary") if alert else None,
                "resolved": False,
                "priority": priority,
                "bounding_boxes": event.get("bounding_boxes", []),
                "metadata": event.get("metadata", {}),
            }
            try:
                db_id = await insert_incident(incident_doc)
                if db_id:
                    logging.info(f"[DB] Incident {event_id} stored in MongoDB (id={db_id})")
            except Exception as e:
                logging.error(f"[DB] Failed to store incident {event_id}: {e}")

        logging.warning(
            "[EVENT_INCIDENT_DETECTED] "
            f"event_id={event_id} type={event_type} camera={camera_id} zone={zone} "
            f"priority={priority} suspicion={suspicion_score:.2f} frames={frames_considered}"
        )
        logging.debug(f"[ALERT_PAYLOAD] {str(alert)[:200]}") 
        
        # Broadcast to all connected WebSocket clients
        # Queue with id for WebSocket delivery
        await alert_broadcast_queue.put({"event": event, "alert": alert})
        logging.info(
            f"[BROADCAST_QUEUED] event_id={event_id} type={event_type} "
            f"queue_size={alert_broadcast_queue.qsize()}"
        )
        return {"received": True, "alert": alert, "incident_id": incident_id}

    logging.debug(
        "[EVENT_NO_INCIDENT] "
        f"event_id={event_id} type={event_type} camera={camera_id} zone={zone} "
        f"confidence={confidence:.2f} suspicion={suspicion_score:.2f} priority={priority} "
        f"frames={frames_considered}"
    )
    return {"received": True, "alert": None}


# ============================================================================
# WEBSOCKET FOR REAL-TIME ALERTS
# ============================================================================
@app.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    client_id = id(websocket)
    await websocket.accept()
    active_alert_clients.append(websocket)
    logging.info(f"[WS_CLIENT_CONNECTED] id={client_id} active_clients={len(active_alert_clients)}")
    
    try:
        # On connect, send the last alert if available
        if alerts_history:
            last_alert = alerts_history[-1]
            await websocket.send_json(last_alert)
            logging.debug(
                f"[WS_INITIAL_ALERT] client={client_id} "
                f"event_type={last_alert.get('event', {}).get('event_type', 'unknown')}"
            )
        else:
            await websocket.send_json({"msg": "No alerts yet."})
            logging.debug(f"[WS_INITIAL_EMPTY] client={client_id}")
        
        # Broadcast loop: listen for new alerts and send to all clients
        while True:
            alert = await alert_broadcast_queue.get()
            event_type = alert.get('event', {}).get('event_type', 'unknown')
            event_id = alert.get('event', {}).get('event_id', 'null')
            active_count = len(active_alert_clients)
            
            # STEP 1: LOG EXACT PAYLOAD BEFORE BROADCAST
            payload_to_send = {
                "id": event_id,  # ADD ID FOR FRONTEND
                "event": alert.get('event', {}),
                "alert": alert.get('alert', {})
            }
            logging.info(
                f"[WS_BROADCAST_START] event_id={event_id} type={event_type} "
                f"clients={active_count}"
            )
            logging.debug(
                f"[WS_PAYLOAD_DEBUG] Sending to {active_count} clients: "
                f"id={event_id} has_event={bool(payload_to_send['event'])} "
                f"has_alert={bool(payload_to_send['alert'])}"
            )
            
            # Broadcast to all connected clients
            failed_clients = []
            for idx, client in enumerate(active_alert_clients):
                try:
                    # Send payload WITH id field for frontend IncidentList
                    await client.send_json(payload_to_send)
                    logging.debug(
                        f"[WS_SEND_OK] event_id={event_id} client={idx} "
                        f"type={event_type}"
                    )
                except Exception as e:
                    logging.warning(
                        f"[WS_SEND_FAIL] event_id={event_id} client={idx} "
                        f"error={str(e)[:100]}"
                    )
                    failed_clients.append(client)
            
            # Remove dead clients
            for client in failed_clients:
                if client in active_alert_clients:
                    active_alert_clients.remove(client)
                    logging.info(
                        f"[WS_CLIENT_REMOVED] event_id={event_id} "
                        f"remaining={len(active_alert_clients)}"
                    )
            
            logging.info(
                f"[WS_BROADCAST_DONE] event_id={event_id} type={event_type} "
                f"success={active_count - len(failed_clients)}/{active_count}"
            )
    except Exception as e:
        logging.error(
            f"[WS_HANDLER_ERROR] client={client_id} error={e}",
            exc_info=True
        )
    finally:
        if websocket in active_alert_clients:
            active_alert_clients.remove(websocket)
        logging.info(
            f"[WS_CLIENT_DISCONNECTED] id={client_id} "
            f"remaining_clients={len(active_alert_clients)}"
        )


@app.get("/incidents")
async def list_incidents(request: Request = None, user: Optional[User] = Depends(get_current_user)):
    tenant_filter = user.tenant_id if user else (request.query_params.get("tenant_id") if request else None)
    
    # Load from MongoDB if available
    if DB_ENABLED:
        try:
            query = {"tenant_id": tenant_filter} if tenant_filter else {}
            db_incidents = await get_incidents(filter_query=query, limit=100)
            for doc in db_incidents:
                inc_id = doc.get("event_id") or doc.get("id") or str(doc.get("_id"))
                if inc_id not in incidents:
                    incidents[inc_id] = {
                        "event": {
                            "event_id": inc_id,
                            "camera_id": doc.get("camera_id"),
                            "zone": doc.get("zone"),
                            "event_type": doc.get("event_type"),
                            "confidence": doc.get("confidence", 0.0),
                            "timestamp": doc.get("timestamp"),
                            "tenant_id": doc.get("tenant_id"),
                        },
                        "alert": {
                            "priority": doc.get("priority", "medium"),
                            "summary": doc.get("summary", ""),
                            "suspicion_score": doc.get("severity_score", 0.0),
                        }
                    }
        except Exception as e:
            logging.error(f"[DB] Error loading incidents: {e}")

    data = []
    for incident_id, payload in incidents.items():
        event = payload.get("event", {})
        # Filter by tenant if specified
        if tenant_filter and event.get("tenant_id") and event.get("tenant_id") != tenant_filter:
            continue
        data.append({
            "id": incident_id,
            "event": event,
            "alert": payload.get("alert", {}),
        })

    totals = {
        "total_incidents": len(data),
        "critical_or_high": 0,
        "avg_suspicion_score": None,
    }
    by_type = {}
    by_zone = {}
    suspicion_scores = []

    for item in data:
        alert = item.get("alert") or {}
        event = item.get("event") or {}
        priority = (alert.get("priority") or "").lower()
        if priority in ("high", "critical"):
            totals["critical_or_high"] += 1
        if alert.get("suspicion_score") is not None:
            suspicion_scores.append(alert["suspicion_score"])
        
        etype = event.get("event_type") or "unknown"
        by_type[etype] = by_type.get(etype, 0) + 1
        
        zone = event.get("zone") or "unknown"
        by_zone[zone] = by_zone.get(zone, 0) + 1

    if suspicion_scores:
        totals["avg_suspicion_score"] = sum(suspicion_scores) / len(suspicion_scores)

    return {
        "incidents": data,
        "totals": totals,
        "by_type": by_type,
        "by_zone": by_zone,
    }


@app.get("/incident/{incident_id}/summary")
async def get_llm_summary(incident_id: str):
    incident = incidents.get(incident_id)
    if not incident:
        return {"error": "Incident not found"}
    return {"summary": incident["alert"].get("summary", "No summary available")}


@app.get("/incident/{incident_id}/pdf")
async def get_incident_pdf(incident_id: str):
    incident = incidents.get(incident_id)
    if not incident:
        return Response(content="Incident not found", status_code=404)
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 800, "SentinelAI Incident Report")
    p.setFont("Helvetica", 12)
    p.drawString(100, 770, f"Incident ID: {incident_id}")
    p.drawString(100, 750, f"Event Type: {incident['event'].get('event_type', 'N/A')}")
    p.drawString(100, 730, f"Zone: {incident['event'].get('zone', 'N/A')}")
    p.drawString(100, 710, f"Camera: {incident['event'].get('camera_id', 'N/A')}")
    p.drawString(100, 690, f"Confidence: {incident['event'].get('confidence', 'N/A')}")
    p.drawString(100, 670, f"Priority: {incident['alert'].get('priority', 'N/A')}")
    
    ts = incident['event'].get('timestamp')
    if ts:
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
        p.drawString(100, 650, f"Timestamp: {time_str}")
    
    p.drawString(100, 620, "Summary:")
    summary = incident['alert'].get('summary', 'No summary available')
    # Word wrap summary
    y = 600
    words = summary.split()
    line = ""
    for word in words:
        if len(line + word) < 70:
            line += word + " "
        else:
            p.drawString(100, y, line)
            y -= 15
            line = word + " "
    if line:
        p.drawString(100, y, line)
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return StreamingResponse(
        buffer, 
        media_type="application/pdf", 
        headers={"Content-Disposition": f"attachment; filename=incident_{incident_id}.pdf"}
    )


@app.get("/api/stats")
def get_stats(user: Optional[User] = Depends(get_current_user)):
    """Get real-time statistics for dashboard."""
    sync_camera_configs_from_test_videos(selected_module)
    tenant_filter = user.tenant_id if user else None
    
    cameras = [
        c for c in camera_configs.values()
        if not tenant_filter or not c.get("tenant_id") or c.get("tenant_id") == tenant_filter
    ]
    
    user_incidents = [
        inc for inc in incidents.values()
        if not tenant_filter or not inc.get("event", {}).get("tenant_id") or inc.get("event", {}).get("tenant_id") == tenant_filter
    ]
    
    by_type = {}
    for inc in user_incidents:
        etype = inc.get("event", {}).get("event_type", "other")
        by_type[etype] = by_type.get(etype, 0) + 1

    total_people = sum(t.get("people_count", 0) for t in camera_live_telemetry.values())

    return {
        "total_incidents": len(user_incidents),
        "active_cameras": sum(1 for c in cameras if c.get("active")),
        "total_cameras": len(cameras),
        "alerts_count": len(alerts_history),
        "zones_monitored": len(set(c.get("zone") for c in cameras if c.get("zone"))),
        "total_people_detected": total_people,
        "by_type": by_type,
    }


# ============================================================================
# DEBUG ENDPOINT - Verify event flow and WebSocket connectivity
# ============================================================================
@app.get("/api/debug/ping")
async def debug_ping():
    """
    Send a debug ping through the WebSocket broadcast system.
    Useful for testing end-to-end event delivery without running workers.
    
    Usage: curl http://localhost:8000/api/debug/ping
    
    Monitor logs:
    - Backend: [DEBUG_PING] messages
    - Frontend: [WS_MESSAGE_RX] console logs
    """
    debug_event = {
        "event_id": f"debug_ping_{int(time.time() * 1000)}",
        "camera_id": "DEBUG_CAMERA",
        "zone": "debug",
        "event_type": "debug_ping",
        "confidence": 1.0,
        "timestamp": time.time(),
        "bounding_boxes": [],
        "metadata": {"source": "debug_endpoint"},
    }
    
    debug_alert = {
        "event": debug_event,
        "alert": {
            "priority": "low",
            "summary": "Debug ping received - event flow working correctly",
            "suspicion_score": 0.0,
            "recommended_actions": ["Monitor WebSocket logs in frontend console"],
        }
    }
    
    logging.info(
        f"[DEBUG_PING] event_id={debug_event['event_id']} "
        f"sending to {len(active_alert_clients)} WebSocket clients"
    )
    
    # Queue the debug alert for broadcast
    await alert_broadcast_queue.put(debug_alert)
    
    return {
        "msg": "Debug ping sent",
        "event_id": debug_event["event_id"],
        "ws_clients": len(active_alert_clients),
        "queue_depth": alert_broadcast_queue.qsize(),
    }


# ============================================================================
# WHATSAPP TEST ENDPOINT
# ============================================================================
@app.get("/api/debug/whatsapp/test")
async def test_whatsapp():
    """
    Test WhatsApp notification configuration and send a test message.
    
    Usage: curl http://localhost:8000/api/debug/whatsapp/test
    
    Returns configuration status and test result.
    """
    try:
        from notifications.whatsapp import test_whatsapp_connection, is_whatsapp_configured
        
        result = test_whatsapp_connection()
        
        return {
            "whatsapp_available": True,
            "configured": result["configured"],
            "enabled": result["enabled"],
            "test_sent": result["test_sent"],
            "error": result.get("error"),
            "message": "Test message sent!" if result["test_sent"] else "Check configuration",
        }
    except ImportError:
        return {
            "whatsapp_available": False,
            "configured": False,
            "enabled": False,
            "test_sent": False,
            "error": "WhatsApp module not available. Install twilio: pip install twilio",
            "message": "WhatsApp notifications not available",
        }
    except Exception as e:
        return {
            "whatsapp_available": True,
            "configured": False,
            "enabled": False,
            "test_sent": False,
            "error": str(e),
            "message": "Error testing WhatsApp",
        }


@app.get("/api/debug/whatsapp/status")
async def whatsapp_status():
    """
    Get WhatsApp notification configuration status (without sending a message).
    
    Usage: curl http://localhost:8000/api/debug/whatsapp/status
    """
    try:
        from notifications.whatsapp import is_whatsapp_configured, _get_config
        
        config = _get_config()
        
        return {
            "whatsapp_available": True,
            "enabled": config["enabled"],
            "configured": is_whatsapp_configured(),
            "has_account_sid": bool(config["account_sid"]),
            "has_auth_token": bool(config["auth_token"]),
            "has_to_number": bool(config["to_number"]),
            "from_number": config["from_number"],
        }
    except ImportError:
        return {
            "whatsapp_available": False,
            "enabled": False,
            "configured": False,
            "error": "WhatsApp module not available",
        }


@app.get("/api/debug/whatsapp/test-alert/{camera_id}")
async def test_whatsapp_alert(camera_id: str = "cam1"):
    """
    Send a test WhatsApp alert for a specific camera with cooldown tracking.
    
    Features:
    - One alert per 30s per camera
    - After 6+ alerts, 60s extended cooldown
    - Tracks duplicate prevention
    
    Usage: curl http://localhost:8000/api/debug/whatsapp/test-alert/cam1
    """
    try:
        from notifications.whatsapp import (
            send_whatsapp_alert_nonblocking,
            format_alert_message,
            _whatsapp_cooldown,
            is_whatsapp_configured
        )
        
        if not is_whatsapp_configured():
            return {
                "success": False,
                "error": "WhatsApp not configured",
                "message": "Check TWILIO environment variables"
            }
        
        # Get current state
        alert_count = _whatsapp_cooldown.get_alert_count(camera_id)
        is_threshold = _whatsapp_cooldown.is_threshold_active(camera_id)
        remaining = _whatsapp_cooldown.get_remaining_cooldown(camera_id)
        
        # Try to send
        test_message = format_alert_message(
            zone="Test Zone",
            event_type="Test Alert",
            confidence=0.95,
            camera_id=camera_id,
            priority="high",
            extra_info="This is a test message from the debug endpoint"
        )
        
        send_whatsapp_alert_nonblocking(test_message, camera_id=camera_id)
        
        return {
            "success": True,
            "message": "Test alert queued for sending",
            "camera_id": camera_id,
            "alert_count": alert_count + 1,
            "cooldown_active": remaining > 0,
            "threshold_active": is_threshold,
            "remaining_cooldown_seconds": round(remaining, 2),
            "next_alert_allowed_in": round(remaining, 2) if remaining > 0 else 0,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Error sending test alert"
        }


@app.get("/api/debug/whatsapp/cooldown-status")
async def whatsapp_cooldown_status():
    """
    Check cooldown status for all cameras.
    
    Usage: curl http://localhost:8000/api/debug/whatsapp/cooldown-status
    """
    try:
        from notifications.whatsapp import _whatsapp_cooldown
        
        return {
            "success": True,
            "message": "Use /api/debug/whatsapp/test-alert/{camera_id} to test individual cameras",
            "noted": "Alert counter resets after 60s of no activity per camera"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    logging.info(f"Starting server on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
