"""
Global Person Tracking & Cross-Camera Re-Identification Engine

Maps local camera track IDs to system-wide Global Person IDs (e.g., P-0042) using:
1. Appearance Embedding (color histogram signatures & spatial feature distribution)
2. Camera Topology Graph (spatial adjacency & valid transition timing windows)
3. ID Switch Protection & Occlusion Buffering
"""

import os
import time
import logging
import threading
import numpy as np
from typing import Dict, List, Optional, Tuple, Set, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ============================================================================
# CAMERA TOPOLOGY GRAPH
# ============================================================================

@dataclass
class CameraTransition:
    from_camera: str
    to_camera: str
    min_time_seconds: float
    max_time_seconds: float


class CameraTopology:
    """
    Maintains spatial connections between cameras to validate cross-camera transitions.
    Prevents impossible teleportation between distant non-adjacent cameras.
    """

    def __init__(self):
        # (from_cam, to_cam) -> (min_time, max_time)
        self._transitions: Dict[Tuple[str, str], Tuple[float, float]] = {}
        self._default_min_time = 1.0
        self._default_max_time = 60.0

    def add_connection(self, from_cam: str, to_cam: str, min_time: float = 1.0, max_time: float = 45.0):
        self._transitions[(from_cam, to_cam)] = (min_time, max_time)
        self._transitions[(to_cam, from_cam)] = (min_time, max_time)

    def is_transition_valid(self, from_cam: str, to_cam: str, elapsed_seconds: float) -> bool:
        if from_cam == to_cam:
            return True  # Same camera re-entry / occlusion recovery

        if (from_cam, to_cam) in self._transitions:
            min_t, max_t = self._transitions[(from_cam, to_cam)]
            return min_t <= elapsed_seconds <= max_t

        # If no explicit topology is defined, allow default reasonable window
        return self._default_min_time <= elapsed_seconds <= self._default_max_time


# ============================================================================
# APPEARANCE EMBEDDER
# ============================================================================

class AppearanceEmbedder:
    """
    Extracts normalized color-spatial appearance signatures from person crops.
    """

    def extract(self, crop: np.ndarray) -> Optional[np.ndarray]:
        if crop is None or crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return None

        try:
            import cv2
            # Resize crop to standard dimension
            resized = cv2.resize(crop, (64, 128))
            hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

            # Extract 3-zone color histogram (Upper head/torso, Middle body, Lower legs)
            h, w = hsv.shape[:2]
            top_half = hsv[0:int(h * 0.5), :]
            bottom_half = hsv[int(h * 0.5):, :]

            hist_top = cv2.calcHist([top_half], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten()
            hist_bot = cv2.calcHist([bottom_half], [0, 1], None, [16, 8], [0, 180, 0, 256]).flatten()

            combined = np.concatenate([hist_top, hist_bot]).astype(np.float32)
            norm = np.linalg.norm(combined)
            return combined / (norm + 1e-6)
        except Exception as e:
            logger.debug(f"Appearance embedding error: {e}")
            return None


# ============================================================================
# GLOBAL PERSON TRACKER & GALLERY
# ============================================================================

@dataclass
class GlobalTrackEntry:
    global_id: str
    embeddings: List[np.ndarray] = field(default_factory=list)
    camera_history: List[Tuple[str, float]] = field(default_factory=list)  # (cam_id, timestamp)
    last_camera: str = ""
    last_seen: float = 0.0
    first_seen: float = 0.0
    total_sightings: int = 0


class GlobalPersonTracker:
    """
    Maintains persistent Global Person IDs (P-0001, P-0002) across all cameras.
    Features:
    - Cosine similarity matching against gallery embeddings
    - Camera topology transition verification
    - Occlusion memory buffering (tracks persist through temporary absences)
    - ID switch dampening
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, similarity_threshold: float = 0.72, gallery_ttl: float = 120.0):
        if self._initialized:
            return

        self.similarity_threshold = similarity_threshold
        self.gallery_ttl = gallery_ttl
        self.topology = CameraTopology()
        self.embedder = AppearanceEmbedder()

        self._next_id = 1
        self._gallery: Dict[str, GlobalTrackEntry] = {}
        # (camera_id, local_track_id) -> global_id
        self._local_to_global: Dict[Tuple[str, int], str] = {}
        self._initialized = True

    def assign_global_id(
        self,
        camera_id: str,
        local_track_id: int,
        frame: np.ndarray,
        bbox: List[int],
        timestamp: Optional[float] = None,
    ) -> Tuple[str, float]:
        """
        Map a local tracker detection to a Global Person ID (P-XXXX).
        Returns: (global_id, confidence_score)
        """
        now = timestamp or time.time()
        local_key = (camera_id, local_track_id)

        with self._lock:
            self._cleanup_expired(now)

            # 1. Check if this local track in this camera already has a mapped global ID
            if local_key in self._local_to_global:
                gid = self._local_to_global[local_key]
                if gid in self._gallery:
                    entry = self._gallery[gid]
                    entry.last_seen = now
                    entry.last_camera = camera_id
                    return gid, 1.0

            # 2. Extract appearance embedding from person crop
            x1, y1, x2, y2 = bbox
            h, w = frame.shape[:2]
            x1_c, y1_c = max(0, x1), max(0, y1)
            x2_c, y2_c = min(w, x2), min(h, y2)
            crop = frame[y1_c:y2_c, x1_c:x2_c]
            emb = self.embedder.extract(crop)

            best_gid = None
            best_sim = 0.0

            if emb is not None:
                for gid, entry in self._gallery.items():
                    elapsed = now - entry.last_seen
                    # Validate camera topology transition
                    if not self.topology.is_transition_valid(entry.last_camera, camera_id, elapsed):
                        continue

                    # Compare with stored embeddings for this global track
                    for stored_emb in entry.embeddings[-3:]:
                        sim = float(np.dot(emb, stored_emb))
                        if sim > best_sim:
                            best_sim = sim
                            best_gid = gid

            # 3. If match crosses similarity threshold, associate with existing global ID
            if best_gid is not None and best_sim >= self.similarity_threshold:
                entry = self._gallery[best_gid]
                entry.last_seen = now
                entry.last_camera = camera_id
                entry.total_sightings += 1
                if emb is not None and len(entry.embeddings) < 5:
                    entry.embeddings.append(emb)
                entry.camera_history.append((camera_id, now))

                self._local_to_global[local_key] = best_gid
                return best_gid, round(best_sim, 2)

            # 4. Otherwise, register a new Global Person ID
            new_gid = f"P-{self._next_id:04d}"
            self._next_id += 1

            new_entry = GlobalTrackEntry(
                global_id=new_gid,
                embeddings=[emb] if emb is not None else [],
                camera_history=[(camera_id, now)],
                last_camera=camera_id,
                last_seen=now,
                first_seen=now,
                total_sightings=1,
            )
            self._gallery[new_gid] = new_entry
            self._local_to_global[local_key] = new_gid

            return new_gid, 1.0

    def get_person_journey(self, global_id: str) -> List[Dict[str, Any]]:
        """Return cross-camera journey history for a global person ID."""
        with self._lock:
            if global_id not in self._gallery:
                return []
            entry = self._gallery[global_id]
            return [
                {"camera_id": cam, "timestamp": ts, "time_formatted": time.strftime("%H:%M:%S", time.localtime(ts))}
                for cam, ts in entry.camera_history
            ]

    def _cleanup_expired(self, now: float):
        """Remove tracks exceeding gallery TTL."""
        expired_gids = [
            gid for gid, entry in self._gallery.items()
            if (now - entry.last_seen) > self.gallery_ttl
        ]
        for gid in expired_gids:
            del self._gallery[gid]

        # Cleanup local mapping
        expired_local = [
            k for k, gid in self._local_to_global.items()
            if gid in expired_gids
        ]
        for k in expired_local:
            del self._local_to_global[k]