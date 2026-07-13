"""
SentinelAI Worker - Zone-Isolated AI Detection Pipeline

Architecture (MANDATORY - strictly enforced):
    Detection Model (YOLO)
            ↓
    Tracking Model (ByteTrack/SimpleTracker)
            ↓
    Shared Detectors  ← NEW: weapon + fire/smoke + pose run on every frame
            ↓
    Zone-Specific Logic Processor
            ↓
    Temporal Buffer (multi-frame verification)
            ↓
    After-Hours Filter              ← NEW: escalates severity outside school hours
            ↓
    Re-ID Enrichment                ← NEW: tags events with global_person_id
            ↓
    Event Engine (suspicion scoring)
            ↓
    Alert Pipeline

Rules (unchanged):
- YOLO NEVER directly triggers events
- All detections pass through tracker + temporal validation
- Zone logic is fully isolated
- Event emission happens only after scoring threshold is crossed
- No global detection logic branching allowed

New shared detectors (weapon / fire_smoke / pose):
- Run ONCE per frame at the pipeline level, before zone processors
- Results are passed INTO the zone processor as enriched metadata
- Zone processors decide what events to emit — they are not bypassed
"""

import os
import cv2
import time
import numpy as np
import logging
import requests
import threading
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, List, Optional, Any

# Redis support (optional - fails gracefully if unavailable)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Ensure backend root is on sys.path for package imports (zones, models)
import sys
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Load environment variables from centralized .env in project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
FRAME_FPS   = int(os.getenv("FRAME_FPS", 5))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/event")
TENANT_ID   = os.getenv("TENANT_ID",   "school1")
CAMERA_ID   = os.getenv("CAMERA_ID",   "cam1")

# Snapshots directory for event images
SNAPSHOTS_DIR = _PROJECT_ROOT / "backend" / "snapshots"
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# Redis configuration for caching and deduplication
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true" and REDIS_AVAILABLE
REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL", "300"))  # 5 minutes default

# Event flood protection config
EVENT_COOLDOWN_SECONDS = float(os.getenv("EVENT_COOLDOWN_SECONDS", "10"))
MAX_FPS_PER_CAMERA     = float(os.getenv("MAX_FPS_PER_CAMERA", "10"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if REDIS_ENABLED:
    logging.info(f"✅ Redis enabled: caching detections for {REDIS_CACHE_TTL}s via {REDIS_URL}")
else:
    logging.info("⚠️  Redis disabled or unavailable - using in-memory event cooldown only")


# ============================================================================
# REDIS CACHE SYSTEM (Distributed Detection State & Event Deduplication)
# ============================================================================

class RedisCache:
    """Redis-backed cache for detected objects and event deduplication.
    
    Provides:
    - Object detection caching (avoid re-processing same person/weapon)
    - Event deduplication (prevent duplicate alerts)
    - Cross-camera caching (future: person ID sharing between cameras)
    - Graceful fallback if Redis unavailable
    """
    
    def __init__(self, redis_url: str = REDIS_URL, ttl: int = REDIS_CACHE_TTL):
        self.ttl = ttl
        self.client = None
        self.enabled = False
        
        if not REDIS_ENABLED:
            logging.debug("Redis caching disabled in config")
            return
        
        try:
            self.client = redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            self.enabled = True
            logging.info(f"✅ Redis cache initialized (TTL: {ttl}s)")
        except Exception as e:
            logging.warning(f"⚠️  Redis cache init failed ({type(e).__name__}: {e}) - falling back to in-memory")
            self.client = None
            self.enabled = False
    
    def cache_detection(self, camera_id: str, detection_type: str, key_id: str, data: Dict) -> bool:
        """Cache detected object to avoid re-processing (e.g., same person ID)."""
        if not self.enabled:
            return False
        
        try:
            cache_key = f"detect:{camera_id}:{detection_type}:{key_id}"
            self.client.setex(cache_key, self.ttl, json.dumps(data))
            return True
        except Exception as e:
            logging.debug(f"Redis cache write failed: {e}")
            return False
    
    def get_cached_detection(self, camera_id: str, detection_type: str, key_id: str) -> Optional[Dict]:
        """Check if object was recently detected to avoid duplicate processing."""
        if not self.enabled:
            return None
        
        try:
            cache_key = f"detect:{camera_id}:{detection_type}:{key_id}"
            data = self.client.get(cache_key)
            return json.loads(data) if data else None
        except Exception as e:
            logging.debug(f"Redis cache read failed: {e}")
            return None
    
    def mark_event_sent(self, camera_id: str, event_type: str, event_hash: str) -> bool:
        """Mark event as sent to prevent duplicate alerts within cache TTL."""
        if not self.enabled:
            return False
        
        try:
            event_key = f"event:{camera_id}:{event_type}:{event_hash}"
            self.client.setex(event_key, self.ttl, "1")
            return True
        except Exception as e:
            logging.debug(f"Redis event marking failed: {e}")
            return False
    
    def is_event_duplicate(self, camera_id: str, event_type: str, event_hash: str) -> bool:
        """Check if event was already sent (deduplication)."""
        if not self.enabled:
            return False
        
        try:
            event_key = f"event:{camera_id}:{event_type}:{event_hash}"
            exists = self.client.exists(event_key) > 0
            if exists:
                logging.debug(f"Event dedup hit: {event_key}")
            return exists
        except Exception as e:
            logging.debug(f"Redis dedup check failed: {e}")
            return False
    
    def clear_camera_cache(self, camera_id: str) -> int:
        """Clear all cached detections for a camera on restart."""
        if not self.enabled:
            return 0
        
        try:
            pattern = f"detect:{camera_id}:*"
            keys = self.client.keys(pattern)
            if keys:
                count = self.client.delete(*keys)
                logging.info(f"Cleared {count} cached detections for camera {camera_id}")
                return count
            return 0
        except Exception as e:
            logging.warning(f"Redis cache clear failed: {e}")
            return 0


# ============================================================================
# EVENT COOLDOWN SYSTEM (Flood Protection)
# ============================================================================

# Per-event-type cooldowns (used by EventCooldownManager)
EVENT_TYPE_COOLDOWNS: Dict[str, float] = {
    "weapon_detected": 12.0,      # Serious: strong cooldown (increased from 10s)
    "fight": 8.0,                 # Moderate
    "gate_accident": 8.0,         # Moderate
    "vehicle_detected": 5.0,      # Frequent: shorter cooldown
    "crowd_formation": 6.0,       # Moderate
    "fire_smoke_detected": 15.0,  # Fire: strong 15s cooldown (increased from 10s)
    "mobile_usage": 4.0,          # Quick: shorter cooldown
    "fall_detected": 6.0,         # Moderate
    "after_hours_intrusion": 25.0,  # After-hours: long cooldown (new)
}


class EventCooldownManager:
    """
    Prevents event flooding by tracking per-camera event state.
    
    Key format: {camera_id}:{event_type}
    
    Features:
    - Per-event-type cooldown durations (weapon=10s, vehicle=5s, etc.)
    - Cooldown bypass on significant confidence increase (>10%)
    """
    
    def __init__(self, default_cooldown: float = EVENT_COOLDOWN_SECONDS):
        self._default_cooldown = default_cooldown
        self._lock = threading.Lock()
        # key -> {last_time, last_confidence}
        self._state: Dict[str, Dict[str, float]] = {}
    
    def _get_cooldown(self, event_type: str) -> float:
        """Get cooldown duration for specific event type."""
        return EVENT_TYPE_COOLDOWNS.get(event_type, self._default_cooldown)
    
    def should_emit(
        self, 
        camera_id: str, 
        event_type: str, 
        confidence: float,
        confidence_increase_threshold: float = 0.10
    ) -> bool:
        """
        Check if event should be emitted based on cooldown rules.
        
        Returns True if:
        - Event was never seen before
        - Cooldown expired (per-event-type duration)
        - Confidence increased by more than threshold (default 10%)
        """
        key = f"{camera_id}:{event_type}"
        now = time.time()
        cooldown = self._get_cooldown(event_type)
        
        with self._lock:
            if key not in self._state:
                # First occurrence — emit and record
                self._state[key] = {"last_time": now, "last_confidence": confidence}
                return True
            
            state = self._state[key]
            elapsed = now - state["last_time"]
            prev_conf = state["last_confidence"]
            
            # Check cooldown expiry (using per-event-type cooldown)
            if elapsed >= cooldown:
                state["last_time"] = now
                state["last_confidence"] = confidence
                return True
            
            # Check confidence increase
            if confidence > prev_conf * (1 + confidence_increase_threshold):
                state["last_time"] = now
                state["last_confidence"] = confidence
                logging.debug(
                    f"Event {key} emitted: confidence increased "
                    f"{prev_conf:.2f} -> {confidence:.2f}"
                )
                return True
            
            # Suppress duplicate
            return False
    
    def reset(self, camera_id: Optional[str] = None):
        """Clear cooldown state for a camera or all cameras."""
        with self._lock:
            if camera_id:
                keys_to_remove = [k for k in self._state if k.startswith(f"{camera_id}:")]
                for k in keys_to_remove:
                    del self._state[k]
            else:
                self._state.clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Get cooldown state statistics."""
        with self._lock:
            return {"tracked_events": len(self._state)}


# Global cooldown manager (shared across all workers)
_event_cooldown = EventCooldownManager()

# ── Zone → detectable event types ─────────────────────────────────────────────
ZONE_TYPES = {
    "outgate":      ["vehicle_detected", "gate_accident",
                     "license_plate_detected",                  # NEW
                     "weapon_detected", "fire_smoke_detected",  # NEW (shared)
                     "after_hours_intrusion"],                  # NEW
    "corridor":     ["crowd_formation", "fight",
                     "weapon_detected", "fire_smoke_detected",  # NEW
                     "after_hours_intrusion"],
    "school_ground":["crowd_formation", "fight", "weapon_detected",
                     "fall_detected",                           # NEW
                     "fire_smoke_detected",                     # NEW
                     "after_hours_intrusion"],
    "classroom":    ["mobile_usage", "fight",                   # fight is NEW
                     "weapon_detected", "fire_smoke_detected",  # NEW
                     "after_hours_intrusion"],
    "fire_only":    ["fire_smoke_detected"],
}

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


def _resolve_runtime_zone(zone: Optional[str]) -> str:
    zone_clean = (zone or "corridor").strip().lower().replace(" ", "_")
    if zone_clean in CUSTOM_ZONE_RUNTIME_MAP:
        return CUSTOM_ZONE_RUNTIME_MAP[zone_clean]
    if zone_clean in ZONE_TYPES or zone_clean == "all":
        return zone_clean
    return "corridor"

# ── COCO class map ─────────────────────────────────────────────────────────────
YOLO_CLASSES = {
    0:  "person",
    2:  "car",
    3:  "motorcycle",
    5:  "bus",
    7:  "truck",
    43: "knife",
    44: "fork",
    67: "cell phone",
    76: "scissors",
}

VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck"}
WEAPON_CLASSES  = {"knife", "scissors"}

# ── Registry / zone imports ────────────────────────────────────────────────────
from registry import (
    get_model_registry,
    get_tracker_registry,
    TrackedObjectData,
    ZONE_MODEL_CONFIGS,
    WEAPON_MODEL_CLASSES,
    FIRE_SMOKE_MODEL_CLASSES,
    COCO_WEAPON_CLASSES,
)

from zones import ZONE_PROCESSORS
from zones.base import TrackedObject, FrameMetadata, DetectionEvent

# Lazy imports — only loaded when modules are present
try:
    from detectors import WeaponDetector, FireSmokeDetector, PoseDetector
    _DETECTORS_AVAILABLE = True
except ImportError:
    _DETECTORS_AVAILABLE = False
    logging.warning("detectors.py not found — shared detectors disabled")

try:
    from reid import ReidManager
    _REID_AVAILABLE = True
except ImportError:
    _REID_AVAILABLE = False
    logging.warning("reid.py not found — cross-camera Re-ID disabled")

try:
    from behaviours import AfterHoursChecker
    _BEHAVIORS_AVAILABLE = True
except ImportError:
    _BEHAVIORS_AVAILABLE = False
    logging.warning("behaviours.py not found — after-hours check disabled")


# ============================================================================
# SHARED DETECTOR BUNDLE (SINGLETON)
# ============================================================================

class SharedDetectors:
    """
    Weapon + fire/smoke + pose detectors that run on EVERY frame across
    ALL zones.

    SINGLETON: Instantiated ONCE globally at orchestrator startup.
    All cameras share the same detector instances to avoid:
    - Model reload duplication
    - GPU memory waste
    - Repeated initialization warnings

    Loaded once at startup, results are passed to zone processors as
    extra context — zone processors remain the sole event emitters.

    Gracefully degrades if custom model files are missing:
        weapon     → falls back to COCO knife/scissors in zone model
        fire_smoke → disabled (no COCO fallback exists)
        pose       → fight/fall detection disabled
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if SharedDetectors._initialized:
            return
        
        with SharedDetectors._lock:
            if SharedDetectors._initialized:
                return
            
            registry = get_model_registry()

            self._weapon_detector     = None
            self._fire_smoke_detector = None
            self._pose_detector       = None

            if _DETECTORS_AVAILABLE:
                self._weapon_detector     = WeaponDetector(registry)
                self._fire_smoke_detector = FireSmokeDetector(registry)
                self._pose_detector       = PoseDetector(registry)
                logging.info("SharedDetectors (singleton): weapon + fire/smoke + pose loaded")
            else:
                logging.warning(
                    "SharedDetectors: detectors.py missing — "
                    "weapon/fire/pose will not run"
                )
            
            SharedDetectors._initialized = True

    def run(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Run all shared detectors on a frame.

        Returns a dict passed as `shared_detections` into each zone processor:
        {
            "weapons":    [ {class_name, confidence, bbox}, ... ],
            "fire_smoke": [ {class_name, confidence, bbox}, ... ],
            "poses":      [ {track_id, keypoints, bbox},   ... ],   (pose model output)
        }
        """
        result = {"weapons": [], "fire_smoke": [], "poses": []}

        if self._weapon_detector:
            result["weapons"]    = self._weapon_detector.detect(frame)

        if self._fire_smoke_detector:
            result["fire_smoke"] = self._fire_smoke_detector.detect(frame)

        if self._pose_detector:
            result["poses"]      = self._pose_detector.detect(frame)

        return result
    
    @property
    def weapon_available(self) -> bool:
        return self._weapon_detector is not None and self._weapon_detector.is_available
    
    @property
    def fire_smoke_available(self) -> bool:
        return self._fire_smoke_detector is not None and self._fire_smoke_detector.is_available
    
    @property
    def pose_available(self) -> bool:
        return self._pose_detector is not None and self._pose_detector.is_available


def get_shared_detectors() -> SharedDetectors:
    """Get the global SharedDetectors singleton."""
    return SharedDetectors()


# ============================================================================
# DETECTION PIPELINE (single camera)
# ============================================================================

class DetectionPipeline:
    """
    Main detection pipeline for a single camera.

    Unchanged mandatory flow:
        YOLO → Tracker → [SharedDetectors] → ZoneProcessor
             → [AfterHoursFilter] → [ReidEnrichment] → EventFormat
    """

    def __init__(
        self,
        camera_id:        str,
        zone:             str,
        shared_detectors: Optional["SharedDetectors"] = None,
        reid_manager:     Optional[Any]               = None,
        after_hours:      Optional[Any]               = None,
    ):
        self.camera_id = camera_id
        self.zone      = zone

        self._model_registry   = get_model_registry()
        self._tracker_registry = get_tracker_registry()

        self._model        = self._model_registry.get_model(zone)
        self._model_config = self._model_registry.get_config(zone)

        if self._model is None:
            raise RuntimeError(
                f"Model for zone '{zone}' is not available. "
                "Ensure dependencies are installed and the project venv is active."
            )

        self._tracker = self._tracker_registry.get_tracker(camera_id)

        processor_class = ZONE_PROCESSORS.get(zone)
        if processor_class is None:
            raise ValueError(f"No zone processor found for zone: {zone}")
        self._zone_processor = processor_class(camera_id)

        # Shared components (may be None if modules not installed)
        self._shared_detectors = shared_detectors
        self._reid_manager     = reid_manager
        self._after_hours      = after_hours

        self._frame_idx = 0

        logging.info(
            f"DetectionPipeline ready: camera={camera_id} zone={zone} "
            f"model={self._model_config.model_file} "
            f"weapon={'✓' if shared_detectors and shared_detectors._weapon_detector else '✗'} "
            f"fire={'✓' if shared_detectors and shared_detectors._fire_smoke_detector else '✗'} "
            f"pose={'✓' if shared_detectors and shared_detectors._pose_detector else '✗'} "
            f"reid={'✓' if reid_manager else '✗'} "
            f"after_hours={'✓' if after_hours else '✗'}"
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray) -> List[Dict]:
        timestamp = time.time()

        # 1. Zone-model YOLO inference
        raw_detections = self._run_yolo_inference(frame)

        # 2. Tracking — maintain object identity
        tracked_objects = self._run_tracking(raw_detections)

        # 3. Shared detectors — weapon / fire+smoke / pose
        #    Results are passed INTO the zone processor, not acted on directly.
        shared = {}
        if self._shared_detectors:
            shared = self._shared_detectors.run(frame)

        # Debug: inspect shared detections for school_ground cameras
        if self.zone == "school_ground" and self._frame_idx % 30 == 0:
            weapons = shared.get("weapons", []) if isinstance(shared, dict) else []
            max_conf = max((w.get("confidence", 0.0) for w in weapons), default=0.0)
            persons = [o for o in tracked_objects if o.class_name == "person"]
            coco_weapons = [o for o in tracked_objects if o.class_name in ("knife", "scissors")]
            all_classes = set(o.class_name for o in tracked_objects)
            logging.info(
                f"[SCHOOL_GROUND_DEBUG] camera={self.camera_id} frame={self._frame_idx} "
                f"weapons={len(weapons)} max_conf={max_conf:.2f} "
                f"persons={len(persons)} coco_weapons={len(coco_weapons)} "
                f"all_classes={all_classes}"
            )
            # Log individual weapon detections for analysis
            for w in weapons:
                logging.info(
                    f"  [WEAPON_DET] class={w.get('class_name')} "
                    f"conf={w.get('confidence', 0):.2f} bbox={w.get('bbox')}"
                )

        # 4. Zone processor — temporal buffer + suspicion scoring
        metadata = FrameMetadata(
            camera_id=self.camera_id,
            frame_idx=self._frame_idx,
            timestamp=timestamp,
            frame_size=(frame.shape[1], frame.shape[0]),
        )
        # Zone processors that support shared_detections accept it via kwarg.
        # Older zone processors that don't yet accept it still work fine.
        try:
            zone_events = self._zone_processor.process_frame(
                frame, tracked_objects, metadata, shared_detections=shared
            )
        except TypeError:
            # Backward compat: zone processor doesn't accept shared_detections yet
            zone_events = self._zone_processor.process_frame(
                frame, tracked_objects, metadata
            )

        # 5. After-hours filter — escalate severity if outside school hours
        if self._after_hours:
            zone_events = self._after_hours.filter(zone_events, self.zone)

        # 6. Format events for backend (with snapshot saving)
        events = self._format_events(zone_events, timestamp, frame)

        # 7. Re-ID enrichment — attach global_person_id where possible
        if self._reid_manager:
            events = self._reid_manager.enrich_events(
                events, tracked_objects, self.camera_id
            )

        self._frame_idx += 1
        return events

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def _run_yolo_inference(self, frame: np.ndarray) -> List[Dict]:
        """Run zone model YOLO inference. Returns raw detections (NOT events)."""
        results    = self._model(frame, verbose=False)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id     = int(boxes.cls[i].item())
                conf       = float(boxes.conf[i].item())
                xyxy       = boxes.xyxy[i].cpu().numpy().astype(int).tolist()
                class_name = YOLO_CLASSES.get(cls_id)

                if class_name is None:
                    continue
                if conf < self._model_config.confidence_threshold:
                    continue
                if cls_id not in self._model_config.classes:
                    continue

                detections.append({
                    "class_id":   cls_id,
                    "class_name": class_name,
                    "confidence": conf,
                    "bbox":       xyxy,
                })

        return detections

    def _run_tracking(self, detections: List[Dict]) -> List[TrackedObject]:
        """Run tracker → return list of TrackedObject with stable IDs."""
        tracked_data    = self._tracker.update(detections)
        tracked_objects = []

        for td in tracked_data:
            if isinstance(td, TrackedObjectData):
                tracked_objects.append(TrackedObject(
                    object_id=td.object_id,
                    class_name=td.class_name,
                    bbox=td.bbox,
                    confidence=td.confidence,
                    motion_vector=td.motion_vector,
                    timestamp=td.timestamp,
                ))
            else:
                tracked_objects.append(TrackedObject(
                    object_id=getattr(td, "object_id",    0),
                    class_name=getattr(td, "class_name",  "unknown"),
                    bbox=getattr(td, "bbox",              [0, 0, 0, 0]),
                    confidence=getattr(td, "confidence",  0.5),
                ))

        return tracked_objects

    def _format_events(
        self, zone_events: List[DetectionEvent], timestamp: float, frame: np.ndarray
    ) -> List[Dict]:
        """Format zone processor output into backend event schema with snapshot saving."""
        events = []
        for event in zone_events:
            event_id = f"evt_{event.event_type}_{int(timestamp * 1000)}"
            
            # Save snapshot for this event
            snapshot_path = None
            try:
                snapshot_filename = f"{event_id}_{self.camera_id}.jpg"
                snapshot_path = SNAPSHOTS_DIR / snapshot_filename
                cv2.imwrite(str(snapshot_path), frame)
                logging.debug(f"Saved snapshot: {snapshot_path}")
            except Exception as e:
                logging.error(f"Failed to save snapshot for {event_id}: {e}")
            
            events.append({
                "event_id":      event_id,
                "tenant_id":     TENANT_ID,
                "camera_id":     self.camera_id,
                "zone":          self.zone,
                "event_type":    event.event_type,
                "confidence":    event.confidence,
                "timestamp":     timestamp,
                "bounding_boxes": event.bounding_boxes,
                "severity_score": event.confidence,
                "metadata":      event.metadata or {},
                "snapshot_path": str(snapshot_path) if snapshot_path else None,
                # These fields are populated later by re-id enrichment
                "global_person_id": None,
                "after_hours":      event.metadata.get("after_hours", False) if event.metadata else False,
            })
        return events

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_detections_summary(self, frame: np.ndarray) -> Dict[str, int]:
        summary = {}
        for det in self._run_yolo_inference(frame):
            name = det["class_name"]
            summary[name] = summary.get(name, 0) + 1
        return summary

    def reset(self):
        self._frame_idx = 0
        self._tracker_registry.reset_tracker(self.camera_id)
        if hasattr(self._zone_processor, "temporal_buffer"):
            self._zone_processor.temporal_buffer = type(
                self._zone_processor.temporal_buffer
            )(camera_id=self.camera_id)


# ============================================================================
# MULTI-ZONE PIPELINE
# ============================================================================

class MultiZonePipeline:
    """
    Run a single video through ALL zone processors simultaneously.

    Shared components (weapon / fire+smoke / pose / reid / after-hours)
    use SINGLETON instances shared across all cameras to avoid
    running the same heavy models multiple times.
    """

    ALL_ZONES = ["outgate", "corridor", "school_ground", "classroom"]

    def __init__(self, camera_id: str):
        self.camera_id = camera_id

        # ── Shared components — singleton instances ───────────────────
        self._shared_detectors = get_shared_detectors()

        self._reid_manager = None
        if _REID_AVAILABLE:
            self._reid_manager = ReidManager()
            logging.info("MultiZonePipeline: Re-ID manager active")

        self._after_hours = None
        if _BEHAVIORS_AVAILABLE:
            self._after_hours = AfterHoursChecker()
            logging.info("MultiZonePipeline: After-hours checker active")

        # ── One DetectionPipeline per zone ────────────────────────────
        self._pipelines: Dict[str, DetectionPipeline] = {}
        for zone in self.ALL_ZONES:
            try:
                self._pipelines[zone] = DetectionPipeline(
                    camera_id=f"{camera_id}_{zone}",
                    zone=zone,
                    shared_detectors=self._shared_detectors,
                    reid_manager=self._reid_manager,
                    after_hours=self._after_hours,
                )
                logging.info(f"MultiZonePipeline: {zone} pipeline ready")
            except Exception as e:
                logging.warning(f"MultiZonePipeline: {zone} failed to init — {e}")

        self._frame_idx = 0
        logging.info(
            f"MultiZonePipeline ready: {len(self._pipelines)}/{len(self.ALL_ZONES)} zones"
        )

    def process_frame(self, frame: np.ndarray) -> List[Dict]:
        """
        Process frame through ALL zones.

        Shared detectors run ONCE inside each DetectionPipeline.process_frame()
        (the first zone to call shared_detectors.run() pays the cost; subsequent
        zones reuse the cached result for this frame via the shared reference).

        NOTE: To truly run shared detectors only once per frame, pass the
        shared result explicitly. We do that here:
        """
        all_events = []

        # Run shared detectors once for this frame
        shared = self._shared_detectors.run(frame) if self._shared_detectors else {}

        for zone, pipeline in self._pipelines.items():
            try:
                # Temporarily inject pre-computed shared detections
                # so each zone pipeline doesn't re-run the heavy models
                events = pipeline._process_frame_with_shared(frame, shared)
                for event in events:
                    event["detected_by_zone"] = zone
                all_events.extend(events)
            except AttributeError:
                # Fallback: pipeline doesn't have _process_frame_with_shared yet
                events = pipeline.process_frame(frame)
                for event in events:
                    event["detected_by_zone"] = zone
                all_events.extend(events)
            except Exception as e:
                logging.error(f"MultiZonePipeline {zone} error: {e}")

        self._frame_idx += 1
        return all_events

    def get_detections_summary(self, frame: np.ndarray) -> Dict[str, int]:
        summary = {}
        for zone, pipeline in self._pipelines.items():
            for cls_name, count in pipeline.get_detections_summary(frame).items():
                summary[f"{zone}:{cls_name}"] = summary.get(f"{zone}:{cls_name}", 0) + count
        return summary

    def reset(self):
        self._frame_idx = 0
        for p in self._pipelines.values():
            p.reset()


# Patch DetectionPipeline with _process_frame_with_shared so MultiZonePipeline
# can inject a pre-computed shared dict and skip re-running heavy models.
def _process_frame_with_shared(self, frame: np.ndarray, shared: Dict) -> List[Dict]:
    """Like process_frame() but accepts pre-computed shared detections."""
    timestamp       = time.time()
    raw_detections  = self._run_yolo_inference(frame)
    tracked_objects = self._run_tracking(raw_detections)

    metadata = FrameMetadata(
        camera_id=self.camera_id,
        frame_idx=self._frame_idx,
        timestamp=timestamp,
        frame_size=(frame.shape[1], frame.shape[0]),
    )

    try:
        zone_events = self._zone_processor.process_frame(
            frame, tracked_objects, metadata, shared_detections=shared
        )
    except TypeError:
        zone_events = self._zone_processor.process_frame(
            frame, tracked_objects, metadata
        )

    if self._after_hours:
        zone_events = self._after_hours.filter(zone_events, self.zone)

    events = self._format_events(zone_events, timestamp, frame)

    if self._reid_manager:
        events = self._reid_manager.enrich_events(events, tracked_objects, self.camera_id)

    self._frame_idx += 1
    return events

DetectionPipeline._process_frame_with_shared = _process_frame_with_shared


# ============================================================================
# CAMERA WORKER
# ============================================================================

class CameraWorker:
    """
    Per-camera worker with production-ready safeguards.

    zone="all"  → MultiZonePipeline (all detectors on every frame)
    zone=<name> → Single DetectionPipeline with shared detectors attached
    
    Features:
    - Uses singleton SharedDetectors (no model reload per camera)
    - Event cooldown filtering (prevents flood)
    - Configurable FPS throttle
    - Safe shutdown handling (no silent thread termination)
    """

    def __init__(
        self,
        camera_id:    str,
        zone:         str,
        video_source: str,
        show_preview: bool = True,
        max_fps:      Optional[float] = None,
    ):
        self.camera_id    = camera_id
        self.zone         = _resolve_runtime_zone(zone)
        self.video_source = video_source
        self.show_preview = show_preview
        self.max_fps      = max_fps or MAX_FPS_PER_CAMERA

        if self.zone.lower() == "all":
            self._pipeline    = MultiZonePipeline(camera_id)
            self._is_multizone = True
        else:
            # Use singleton SharedDetectors — same instance for all cameras
            shared     = get_shared_detectors()
            reid_mgr   = ReidManager()     if _REID_AVAILABLE     else None
            after_hrs  = AfterHoursChecker() if _BEHAVIORS_AVAILABLE else None
            self._pipeline = DetectionPipeline(
                camera_id, self.zone,
                shared_detectors=shared,
                reid_manager=reid_mgr,
                after_hours=after_hrs,
            )
            self._is_multizone = False

        # Initialize Redis cache for event deduplication and object caching
        self._redis_cache = RedisCache(REDIS_URL, REDIS_CACHE_TTL)

        self._running       = False
        self._shutdown_flag = threading.Event()
        self._cap           = None
        self._frame_count   = 0
        self._event_count   = 0
        self._suppressed_count = 0
        self._last_frame_time  = 0.0
        self._min_frame_interval = 1.0 / self.max_fps if self.max_fps > 0 else 0.0

    def start(self):
        """Start the camera worker. Blocks until stop() is called."""
        try:
            self._cap = cv2.VideoCapture(self.video_source)
            if not self._cap.isOpened():
                raise RuntimeError(f"Cannot open video: {self.video_source}")
            self._running = True
            self._shutdown_flag.clear()
            logging.info(
                f"CameraWorker started: {self.camera_id} ({self.zone}) "
                f"[max_fps={self.max_fps}]"
            )
            self._process_loop()
        except Exception as e:
            logging.error(
                f"CameraWorker {self.camera_id} crashed: {e}",
                exc_info=True
            )
        finally:
            self._safe_cleanup()

    def stop(self):
        """Signal worker to stop gracefully."""
        logging.info(f"CameraWorker {self.camera_id}: stop requested")
        self._running = False
        self._shutdown_flag.set()

    def _safe_cleanup(self):
        """Ensure all resources are released."""
        self._running = False
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        logging.info(
            f"CameraWorker stopped: {self.camera_id} "
            f"(events={self._event_count}, suppressed={self._suppressed_count})"
        )

    def _process_loop(self):
        while self._running and not self._shutdown_flag.is_set():
            # FPS throttle
            now = time.time()
            elapsed = now - self._last_frame_time
            if elapsed < self._min_frame_interval:
                sleep_time = self._min_frame_interval - elapsed
                # Use event-based wait for responsive shutdown
                if self._shutdown_flag.wait(timeout=sleep_time):
                    break
                continue
            self._last_frame_time = now

            try:
                ret, frame = self._cap.read()
                if not ret:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue

                events = self._pipeline.process_frame(frame)
                
                # Apply event cooldown filtering
                filtered_events = []
                for event in events:
                    event_type = event.get("event_type", "unknown")
                    confidence = event.get("confidence", 0.0)
                    event_id = event.get("event_id", "null")
                    
                    if _event_cooldown.should_emit(self.camera_id, event_type, confidence):
                        filtered_events.append(event)
                        logging.debug(
                            f"[EVENT_PASS_COOLDOWN] camera={self.camera_id} "
                            f"id={event_id} type={event_type} confidence={confidence:.2f}"
                        )
                        self._send_event(event)
                        self._event_count += 1
                    else:
                        self._suppressed_count += 1
                        logging.debug(
                            f"[EVENT_SUPPRESSED] camera={self.camera_id} "
                            f"id={event_id} type={event_type} confidence={confidence:.2f}"
                        )

                if self.show_preview:
                    self._show_preview(frame, filtered_events)

                if self._frame_count % 30 == 0:
                    summary = self._pipeline.get_detections_summary(frame)
                    stats = _event_cooldown.get_stats()
                    logging.info(
                        f"[WORKER_STATS] camera={self.camera_id} frame={self._frame_count} "
                        f"events={self._event_count} suppressed={self._suppressed_count} "
                        f"tracked_cooldowns={stats['tracked_events']}"
                    )

                self._frame_count += 1
                
            except Exception as e:
                logging.error(
                    f"CameraWorker {self.camera_id} frame error: {e}",
                    exc_info=True
                )
                # Don't crash — continue to next frame
                continue

    def _send_event(self, event: Dict):
        """Send event to backend via HTTP POST with Redis deduplication.
        
        Uses Redis to:
        - Prevent duplicate events (same type/camera/time window)
        - Cache event data for quick lookup
        - Gracefully falls back to in-memory if Redis unavailable
        """
        event_type = event.get("event_type", "unknown")
        event_id = event.get("event_id", "null")
        confidence = event.get("confidence", 0.0)
        camera_id = event.get("camera_id", "unknown")
        
        # Create event hash for deduplication (type + confidence threshold)
        event_hash = hashlib.md5(
            f"{event_type}:{int(confidence*100)}".encode()
        ).hexdigest()[:8]
        
        # Check Redis for recent duplicate event
        if self._redis_cache.is_event_duplicate(camera_id, event_type, event_hash):
            self._suppressed_count += 1
            logging.debug(
                f"[EVENT_DEDUP_REDIS] id={event_id} type={event_type} "
                f"camera={camera_id} (suppressed via Redis)"
            )
            return
        
        logging.debug(
            f"[EVENT_EMIT] id={event_id} camera={camera_id} type={event_type} "
            f"confidence={confidence:.2f} endpoint={BACKEND_URL}"
        )
        
        try:
            resp = requests.post(BACKEND_URL, json=event, timeout=5)
            if resp.status_code == 200:
                # Mark event as sent in Redis cache
                self._redis_cache.mark_event_sent(camera_id, event_type, event_hash)
                self._event_count += 1
                logging.info(
                    f"✓ [EVENT_DELIVERY_OK] id={event_id} type={event_type} "
                    f"camera={camera_id} status=200"
                )
            else:
                logging.warning(
                    f"⚠ [EVENT_DELIVERY_FAIL] id={event_id} type={event_type} "
                    f"camera={camera_id} status={resp.status_code} "
                    f"response={resp.text[:100]}"
                )
        except requests.exceptions.Timeout:
            logging.error(
                f"✗ [EVENT_TIMEOUT] id={event_id} type={event_type} "
                f"camera={camera_id} endpoint={BACKEND_URL}"
            )
        except requests.exceptions.ConnectionError:
            logging.error(
                f"✗ [EVENT_NO_CONNECTION] id={event_id} type={event_type} "
                f"camera={camera_id} endpoint={BACKEND_URL}"
            )
        except Exception as e:
            logging.error(
                f"✗ [EVENT_SEND_ERROR] id={event_id} type={event_type} "
                f"camera={camera_id} error={e}",
                exc_info=True
            )

    def _show_preview(self, frame: np.ndarray, events: List[Dict]):
        annotated  = frame.copy()
        zone_label = "Zone: ALL" if self._is_multizone else f"Zone: {self.zone}"
        cv2.putText(annotated, zone_label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        zone_colors = {
            "outgate":      (255, 165, 0),
            "corridor":     (0,   255, 255),
            "school_ground":(0,   255, 0),
            "classroom":    (255, 0,   255),
            "fire_only":    (0,   128, 255),
        }
        # Colour-code by event severity
        severity_colors = {
            "weapon_detected":    (0, 0, 255),      # red
            "fire_smoke_detected":(0, 128, 255),    # orange
            "fight":              (0, 0, 200),      # dark red
            "fall_detected":      (255, 0, 255),    # magenta
            "after_hours_intrusion": (0, 0, 180),   # deep red
        }

        if events:
            for event in events:
                etype  = event.get("event_type", "")
                dzone  = event.get("detected_by_zone", self.zone)
                color  = severity_colors.get(etype) or zone_colors.get(dzone, (0, 0, 255))
                label  = etype

                # Show global_person_id if present (from Re-ID)
                gpid = event.get("global_person_id")
                if gpid:
                    label += f" [G:{gpid}]"

                for bbox in event.get("bounding_boxes", []):
                    if len(bbox) == 4:
                        cv2.rectangle(annotated,
                                      (bbox[0], bbox[1]), (bbox[2], bbox[3]),
                                      color, 2)
                        cv2.putText(annotated, label,
                                    (bbox[0], bbox[1] - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

            # After-hours banner
            if any(e.get("after_hours") for e in events):
                cv2.putText(annotated, "⚠ AFTER HOURS", (10, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

        status = f"Frame: {self._frame_count} | Events: {self._event_count}"
        cv2.putText(annotated, status, (10, annotated.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow(f"SentinelAI - {self.zone} ({self.camera_id})", annotated)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            self._running = False


# ============================================================================
# LEGACY COMPATIBILITY LAYER  (unchanged from original)
# ============================================================================

_legacy_model = None

def load_yolov8():
    global _legacy_model
    if _legacy_model is None:
        registry      = get_model_registry()
        _legacy_model = registry.get_model("corridor")
    return _legacy_model


def run_inference(model, frame) -> Dict[str, List[Dict]]:
    results    = model(frame, verbose=False)
    detections: Dict[str, List[Dict]] = {
        "person": [], "car": [], "motorcycle": [],
        "bus": [], "truck": [], "cell phone": [],
    }
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for i in range(len(boxes)):
            cls_id     = int(boxes.cls[i].item())
            conf       = float(boxes.conf[i].item())
            xyxy       = boxes.xyxy[i].cpu().numpy().astype(int).tolist()
            class_name = YOLO_CLASSES.get(cls_id)
            if class_name and class_name in detections:
                detections[class_name].append({"box": xyxy, "confidence": conf})
    return detections


from collections import deque

class FrameHistory:
    def __init__(self, max_frames: int = 10):
        self.history: deque         = deque(maxlen=max_frames)
        self.crowd_frame_count: int = 0
        self.fight_frame_count: int = 0

    def add_frame(self, detections: Dict[str, List[Dict]]):
        self.history.append({"detections": detections, "timestamp": time.time()})

    def get_recent_person_positions(self, n_frames: int = 3) -> List[List[Dict]]:
        return [f["detections"].get("person", []) for f in list(self.history)[-n_frames:]]


_frame_histories: Dict[str, FrameHistory] = {}

def get_frame_history(camera_id: str) -> FrameHistory:
    if camera_id not in _frame_histories:
        _frame_histories[camera_id] = FrameHistory()
    return _frame_histories[camera_id]


def detect_all_events(detections, zone, camera_id) -> List[Dict]:
    events  = []
    history = get_frame_history(camera_id)
    history.add_frame(detections)

    if zone == "outgate":
        for fn in (_legacy_detect_vehicle, _legacy_detect_accident):
            r = fn(detections)
            if r:
                events.append(r)
    elif zone in ("corridor", "school_ground"):
        for fn in (_legacy_detect_crowd, _legacy_detect_fight):
            r = fn(detections, history)
            if r:
                events.append(r)
    elif zone == "classroom":
        r = _legacy_detect_mobile(detections)
        if r:
            events.append(r)

    return events


def _legacy_detect_vehicle(d):
    veh = [det for vt in VEHICLE_CLASSES for det in d.get(vt, [])]
    if not veh:
        return None
    best = max(veh, key=lambda x: x["confidence"])
    if best["confidence"] < 0.5:
        return None
    return {"event_type": "vehicle_detected", "confidence": best["confidence"],
            "bounding_boxes": [v["box"] for v in veh]}


def _legacy_detect_accident(d):
    persons  = d.get("person", [])
    vehicles = [det for vt in VEHICLE_CLASSES for det in d.get(vt, [])]
    if not persons or not vehicles:
        return None
    for p in persons:
        for v in vehicles:
            if _boxes_overlap(p["box"], v["box"]):
                avg = (p["confidence"] + v["confidence"]) / 2
                if avg >= 0.5:
                    return {"event_type": "gate_accident", "confidence": avg,
                            "bounding_boxes": [p["box"], v["box"]]}
    return None


def _legacy_detect_crowd(d, history):
    persons = d.get("person", [])
    if len(persons) < 4:
        history.crowd_frame_count = 0
        return None
    centers  = np.array([((b["box"][0]+b["box"][2])//2, (b["box"][1]+b["box"][3])//2) for b in persons])
    centroid = centers.mean(axis=0)
    if np.linalg.norm(centers - centroid, axis=1).mean() > 150:
        history.crowd_frame_count = 0
        return None
    history.crowd_frame_count += 1
    if history.crowd_frame_count < 3:
        return None
    return {"event_type": "crowd_formation",
            "confidence": float(np.mean([p["confidence"] for p in persons])),
            "bounding_boxes": [p["box"] for p in persons]}


def _legacy_detect_fight(d, history):
    persons = d.get("person", [])
    if len(persons) < 2:
        history.fight_frame_count = 0
        return None
    for i in range(len(persons)):
        for j in range(i+1, len(persons)):
            if _compute_iou(persons[i]["box"], persons[j]["box"]) > 0.15:
                avg = (persons[i]["confidence"] + persons[j]["confidence"]) / 2
                if avg >= 0.6:
                    history.fight_frame_count += 1
                    if history.fight_frame_count >= 3:
                        return {"event_type": "fight", "confidence": avg,
                                "bounding_boxes": [persons[i]["box"], persons[j]["box"]]}
    history.fight_frame_count = 0
    return None


def _legacy_detect_mobile(d):
    persons = d.get("person", [])
    phones  = d.get("cell phone", [])
    if not persons or not phones:
        return None
    for person in persons:
        for phone in phones:
            if _box_inside(phone["box"], person["box"]):
                avg = (person["confidence"] + phone["confidence"]) / 2
                if avg >= 0.4:
                    return {"event_type": "mobile_usage", "confidence": avg,
                            "bounding_boxes": [person["box"], phone["box"]]}
    return None


def _boxes_overlap(b1, b2):
    return _compute_iou(b1, b2) > 0.1 or _distance_between(b1, b2) < 100

def _compute_iou(b1, b2):
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    a1 = (b1[2]-b1[0]) * (b1[3]-b1[1])
    a2 = (b2[2]-b2[0]) * (b2[3]-b2[1])
    union = a1 + a2 - inter
    return inter/union if union > 0 else 0

def _distance_between(b1, b2):
    c1 = ((b1[0]+b1[2])//2, (b1[1]+b1[3])//2)
    c2 = ((b2[0]+b2[2])//2, (b2[1]+b2[3])//2)
    return np.hypot(c1[0]-c2[0], c1[1]-c2[1])

def _box_inside(inner, outer):
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])

def annotate_frame(frame, detections, zone):
    annotated = frame.copy()
    colors = {
        "person": (0, 255, 0), "car": (255, 0, 0), "motorcycle": (255, 0, 0),
        "bus": (255, 0, 0), "truck": (255, 0, 0), "cell phone": (0, 255, 255),
    }
    for class_name, dets in detections.items():
        color = colors.get(class_name, (128, 128, 128))
        for det in dets:
            box = det["box"]; conf = det["confidence"]
            cv2.rectangle(annotated, (box[0], box[1]), (box[2], box[3]), color, 2)
            cv2.putText(annotated, f"{class_name}: {conf:.2f}", (box[0], box[1]-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    cv2.putText(annotated, f"Zone: {zone}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return annotated


# ============================================================================
# BACKEND-DRIVEN MULTI-CAMERA ORCHESTRATION  (unchanged)
# ============================================================================

def _fetch_backend_cameras(module: Optional[str] = None) -> List[Dict]:
    cameras_url = BACKEND_URL.replace("/event", "/api/cameras")
    params = {"module": module} if module else {}
    try:
        resp = requests.get(cameras_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logging.error(f"Failed to load cameras from backend: {exc}")
        return []
    cameras = data.get("cameras", [])
    active  = [c for c in cameras if c.get("active", True)]
    logging.info(
        f"Camera discovery: module={data.get('module', module or 'default')} "
        f"total={len(cameras)} active={len(active)}"
    )
    return active


def _resolve_camera_source(camera: Dict) -> Optional[Any]:
    video_path = camera.get("video_path")
    if video_path:
        if isinstance(video_path, str):
            stripped = video_path.strip()
            if stripped.startswith(("rtsp://", "http://", "https://")):
                return stripped
            if os.path.isabs(stripped) and os.path.exists(stripped):
                return stripped

            # Resolve relative/manual file names against likely roots.
            worker_dir = os.path.dirname(__file__)
            backend_dir = BACKEND_ROOT
            project_root = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
            test_videos_dir = os.path.join(backend_dir, "test_videos")

            candidates = [
                os.path.abspath(stripped),
                os.path.abspath(os.path.join(worker_dir, stripped)),
                os.path.abspath(os.path.join(backend_dir, stripped)),
                os.path.abspath(os.path.join(project_root, stripped)),
                os.path.abspath(os.path.join(test_videos_dir, stripped)),
            ]

            for candidate in candidates:
                if os.path.exists(candidate):
                    return candidate

            logging.warning(
                f"Camera {camera.get('id', 'unknown')}: video_path not found as file, using raw value: {stripped}"
            )
            return stripped
        return video_path
    mode = (camera.get("mode") or "").lower()
    if mode == "webcam":
        return int(camera.get("webcam_index", 0))
    if camera.get("url"):
        return camera["url"]
    return None


def run_all_configured_cameras(module: Optional[str] = None, show_preview: bool = False):
    """
    Run all configured cameras from backend.
    
    Initializes SharedDetectors singleton once before starting any workers.
    Handles graceful shutdown on Ctrl+C.
    """
    # Initialize SharedDetectors singleton ONCE at startup
    logging.info("=" * 60)
    logging.info("Initializing shared detectors (singleton)...")
    shared = get_shared_detectors()
    logging.info(
        f"SharedDetectors ready: weapon={shared.weapon_available} "
        f"fire_smoke={shared.fire_smoke_available} pose={shared.pose_available}"
    )
    logging.info("=" * 60)
    
    cameras = _fetch_backend_cameras(module)
    if not cameras:
        logging.warning("No active cameras found.")
        return

    workers: List[CameraWorker]      = []
    threads: List[threading.Thread]  = []
    shutdown_event = threading.Event()

    def _start_safe(worker, cid, zone, source):
        try:
            worker.start()
        except Exception as exc:
            logging.error(
                f"Worker crashed: camera={cid} zone={zone} source={source}: {exc}",
                exc_info=True
            )

    for cam in cameras:
        cid    = cam.get("id") or f"cam_{len(workers)+1}"
        raw_zone = cam.get("runtime_zone") or cam.get("zone", "corridor")
        zone   = _resolve_runtime_zone(raw_zone)
        source = _resolve_camera_source(cam)
        if source is None:
            logging.warning(f"Skipping {cid}: no source")
            continue
        worker = CameraWorker(cid, zone, source, show_preview)
        workers.append(worker)
        threads.append(threading.Thread(
            target=_start_safe, args=(worker, cid, zone, source),
            name=f"worker-{cid}", daemon=True
        ))

    if not threads:
        logging.warning("No runnable workers.")
        return

    for t in threads:
        t.start()

    logging.info(f"All {len(threads)} workers started (Ctrl+C to stop)")
    logging.info(f"Event cooldown: {EVENT_COOLDOWN_SECONDS}s | Max FPS: {MAX_FPS_PER_CAMERA}")

    def _graceful_shutdown():
        logging.info("Initiating graceful shutdown...")
        shutdown_event.set()
        for w in workers:
            w.stop()
        # Give workers time to clean up
        for t in threads:
            t.join(timeout=5.0)
        logging.info("All workers stopped.")
        logging.info(f"Cooldown stats: {_event_cooldown.get_stats()}")

    try:
        while not shutdown_event.is_set():
            alive_count = sum(1 for t in threads if t.is_alive())
            if alive_count == 0:
                logging.warning("All workers stopped unexpectedly.")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        _graceful_shutdown()


# ============================================================================
# MAIN
# ============================================================================

def main():
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "run-all":
        module       = None
        show_preview = "--preview" in sys.argv
        if "--module" in sys.argv:
            idx = sys.argv.index("--module")
            if idx + 1 < len(sys.argv):
                module = sys.argv[idx + 1]
        run_all_configured_cameras(module=module, show_preview=show_preview)
        return

    if len(sys.argv) >= 3:
        zone         = sys.argv[1]
        video_path   = sys.argv[2]
        camera_id    = sys.argv[3] if len(sys.argv) > 3 else "cam1"
        show_preview = "--no-preview" not in sys.argv
        CameraWorker(camera_id, zone, video_path, show_preview).start()
    else:
        print("Usage: python worker.py <zone> <video_path> [camera_id] [--no-preview]")
        print("       python worker.py run-all [--module school|home|office] [--preview]")
        print("\nZones:", list(ZONE_TYPES.keys()))


if __name__ == "__main__":
    main()