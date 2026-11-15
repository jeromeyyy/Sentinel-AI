"""EventCooldownManager (moved out of worker/worker.py so it is light to import and test;
worker.py re-exports it, behaviour unchanged)."""
import logging
import os
import threading
import time
from typing import Dict, Optional

EVENT_COOLDOWN_SECONDS = float(os.getenv("EVENT_COOLDOWN_SECONDS", "10"))

# Per-event-type cooldowns (seconds)
EVENT_TYPE_COOLDOWNS: Dict[str, float] = {
    "weapon_detected": 12.0,
    "fight": 8.0,
    "gate_accident": 8.0,
    "vehicle_detected": 5.0,
    "crowd_formation": 6.0,
    "fire_smoke_detected": 15.0,
    "mobile_usage": 4.0,
    "fall_detected": 6.0,
    "after_hours_intrusion": 25.0,
}


class EventCooldownManager:
    """
    Prevents event flooding by tracking per-camera event state.
    
    Key format: {camera_id}:{event_type}
    
    Features:
    - Per-event-type cooldown durations (weapon=10s, vehicle=5s, etc.)
    - Cooldown bypass on significant confidence increase (>10%)
    """
    
    def __init__(self, default_cooldown: float = EVENT_COOLDOWN_SECONDS, clock=time.time):
        self._clock = clock
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
        now = self._clock()
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
