"""
SentinelAI Incident Lifecycle & Rules Engine

Responsibilities:
- Multi-environment rule evaluation across School, Home, and Office
- Multi-frame temporal verification & suspicion scoring
- Stateful incident deduplication (preventing alert flooding for continuous events)
- Incident lifecycle management: DETECTED -> ACTIVE -> RESOLVED
- Scenario playbook attachment for automated alerting & multi-channel dispatch
"""

import os
import time
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)

# ============================================================================
# COMPREHENSIVE EVENT CONFIGURATION
# ============================================================================

EVENT_CONFIG: Dict[str, Dict[str, Any]] = {
    # ── SCHOOL SCENARIOS ───────────────────────────────────────────────────
    "fight": {
        "window_sec": 4.0,
        "min_frames": 2,
        "threshold": 0.55,
        "priority": "high",
        "playbook": {
            "scenario": "fight_altercation",
            "send_high_priority_alert": True,
            "include_snapshot": True,
            "include_llm_explanation": True,
            "notify_nearest_staff": True,
        },
    },
    "fight_suspected": {
        "window_sec": 4.0,
        "min_frames": 2,
        "threshold": 0.50,
        "priority": "high",
        "playbook": {
            "scenario": "fight_altercation",
            "send_high_priority_alert": True,
            "include_snapshot": True,
            "include_llm_explanation": True,
        },
    },
    "mobile_phone_use": {
        "window_sec": 5.0,
        "min_frames": 2,
        "threshold": 0.50,
        "priority": "medium",
        "playbook": {
            "scenario": "mobile_phone_use",
            "log_violation": True,
            "include_snapshot": True,
            "suggest_evidence_summary": True,
        },
    },
    "mobile_usage": {
        "window_sec": 5.0,
        "min_frames": 2,
        "threshold": 0.45,
        "priority": "medium",
        "playbook": {
            "scenario": "mobile_phone_use",
            "include_snapshot": True,
        },
    },
    "exam_malpractice": {
        "window_sec": 8.0,
        "min_frames": 2,
        "threshold": 0.55,
        "priority": "high",
        "playbook": {
            "scenario": "exam_malpractice",
            "lock_clip_in_evidence_store": True,
            "notify_invigilator": True,
        },
    },

    # ── SHARED CRITICAL SCENARIOS ──────────────────────────────────────────
    "fire_detected": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.60,
        "priority": "critical",
        "playbook": {
            "scenario": "fire_smoke",
            "immediate_emergency_notification": True,
            "auto_call_fire_service": True,
            "open_evacuation_map": True,
        },
    },
    "smoke_detected": {
        "window_sec": 4.0,
        "min_frames": 2,
        "threshold": 0.55,
        "priority": "high",
        "playbook": {
            "scenario": "fire_smoke",
            "emergency_panel_alert": True,
        },
    },
    "fire_smoke": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.60,
        "priority": "critical",
        "playbook": {
            "scenario": "fire_smoke",
            "immediate_emergency_notification": True,
        },
    },
    "weapon_detected": {
        "window_sec": 2.0,
        "min_frames": 1,
        "threshold": 0.50,
        "priority": "critical",
        "playbook": {
            "scenario": "weapon_detected",
            "immediate_lockdown_alert": True,
            "notify_law_enforcement": True,
        },
    },
    "gun_detected": {
        "window_sec": 1.5,
        "min_frames": 1,
        "threshold": 0.50,
        "priority": "critical",
        "playbook": {
            "scenario": "weapon_detected",
            "immediate_lockdown_alert": True,
            "notify_law_enforcement": True,
        },
    },

    # ── HOME & PERIMETER SCENARIOS ─────────────────────────────────────────
    "intrusion_detected": {
        "window_sec": 4.0,
        "min_frames": 2,
        "threshold": 0.65,
        "priority": "high",
        "playbook": {
            "scenario": "unauthorized_entry",
            "notify_homeowner": True,
            "start_high_fidelity_recording": True,
        },
    },
    "intrusion": {
        "window_sec": 4.0,
        "min_frames": 2,
        "threshold": 0.65,
        "priority": "high",
        "playbook": {
            "scenario": "unauthorized_entry",
            "notify_security": True,
        },
    },
    "fall_collapse": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.65,
        "priority": "critical",
        "playbook": {
            "scenario": "person_down",
            "auto_call_ambulance": True,
            "immediate_emergency_notification": True,
        },
    },
    "fall_detected": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.65,
        "priority": "critical",
        "playbook": {
            "scenario": "person_down",
            "immediate_emergency_notification": True,
        },
    },

    # ── OFFICE & FACILITY SCENARIOS ────────────────────────────────────────
    "after_hours_presence": {
        "window_sec": 5.0,
        "min_frames": 2,
        "threshold": 0.60,
        "priority": "high",
        "playbook": {
            "scenario": "after_hours_presence",
            "notify_security": True,
            "flag_for_audit": True,
        },
    },
    "restricted_area_entry": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.70,
        "priority": "high",
        "playbook": {
            "scenario": "restricted_area_entry",
            "notify_security": True,
            "log_badge_audit": True,
        },
    },
    "crowd_detected": {
        "window_sec": 4.0,
        "min_frames": 1,
        "threshold": 0.50,
        "priority": "medium",
        "playbook": {
            "scenario": "crowd_formation",
            "notify_duty_staff": True,
        },
    },
    "crowd_formation": {
        "window_sec": 4.0,
        "min_frames": 1,
        "threshold": 0.50,
        "priority": "medium",
        "playbook": {
            "scenario": "crowd_formation",
            "notify_duty_staff": True,
        },
    },
    "loitering_detected": {
        "window_sec": 10.0,
        "min_frames": 2,
        "threshold": 0.60,
        "priority": "medium",
        "playbook": {
            "scenario": "loitering_dwell",
            "notify_patrol": True,
        },
    },
    "abandoned_object": {
        "window_sec": 15.0,
        "min_frames": 2,
        "threshold": 0.65,
        "priority": "high",
        "playbook": {
            "scenario": "abandoned_object",
            "run_reid_probe": True,
        },
    },
    "gate_accident": {
        "window_sec": 3.0,
        "min_frames": 1,
        "threshold": 0.55,
        "priority": "critical",
        "playbook": {
            "scenario": "gate_accident",
            "auto_call_ambulance": True,
        },
    },
}

# ============================================================================
# STATEFUL INCIDENT LIFECYCLE & DEDUPLICATION
# ============================================================================

# Key: (tenant_id, camera_id, event_type) -> Deque of (timestamp, confidence)
_sliding_windows: Dict[Tuple[str, str, str], Deque[Tuple[float, float]]] = defaultdict(deque)

# Deduplication store: (tenant_id, camera_id, event_type) -> {
#   "incident_id": str, "first_seen": float, "last_seen": float, "status": str, "peak_confidence": float
# }
_active_incidents: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
DEDUP_COOLDOWN_SECONDS = 30.0


def _clean_window(window: Deque[Tuple[float, float]], now: float, max_age: float) -> None:
    while window and (now - window[0][0]) > max_age:
        window.popleft()


def process_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates an incoming detection event across temporal sliding windows
    and stateful deduplication.

    Returns:
    {
        "incident": bool,
        "is_update": bool,
        "incident_id": str,
        "status": "DETECTED" | "ACTIVE" | "RESOLVED",
        "suspicion_score": float,
        "priority": "critical" | "high" | "medium" | "low",
        "playbook": dict,
        "timeline": dict,
        "event": dict,
    }
    """
    tenant_id = event.get("tenant_id", "default")
    camera_id = event.get("camera_id", "unknown")
    event_type = event.get("event_type", "unknown")
    raw_confidence = float(event.get("confidence", 0.0) or 0.0)
    now = float(event.get("timestamp") or time.time())

    cfg = EVENT_CONFIG.get(event_type, {
        "window_sec": 5.0,
        "min_frames": 1,
        "threshold": 0.50,
        "priority": "medium",
        "playbook": {"scenario": "generic_detection"},
    })

    window_key = (tenant_id, camera_id, event_type)
    window = _sliding_windows[window_key]
    window.append((now, raw_confidence))
    _clean_window(window, now, cfg["window_sec"])

    frames_considered = len(window)
    if frames_considered == 0:
        return {"incident": False, "suspicion_score": 0.0}

    avg_conf = sum(c for _, c in window) / frames_considered
    max_conf = max(c for _, c in window)
    suspicion_score = round(0.4 * avg_conf + 0.6 * max_conf, 3)

    min_frames = cfg.get("min_frames", 1)
    threshold = cfg.get("threshold", 0.50)

    # Multi-frame verification check
    is_incident = (frames_considered >= min_frames) and (suspicion_score >= threshold)

    if not is_incident:
        return {
            "incident": False,
            "suspicion_score": suspicion_score,
            "priority": cfg.get("priority", "medium"),
            "playbook": cfg.get("playbook", {}),
            "timeline": {
                "frames_considered": frames_considered,
                "window_sec": cfg["window_sec"],
            },
            "event": event,
        }

    # ── Deduplication & Lifecycle ───────────────────────────────────────────
    dedup_key = (tenant_id, camera_id, event_type)
    active = _active_incidents.get(dedup_key)

    if active and (now - active["last_seen"]) <= DEDUP_COOLDOWN_SECONDS:
        # Existing incident continuous occurrence
        active["last_seen"] = now
        active["peak_confidence"] = max(active["peak_confidence"], suspicion_score)
        active["update_count"] += 1
        incident_id = active["incident_id"]
        status = "ACTIVE"
        is_update = True
        duration = round(now - active["first_seen"], 1)
    else:
        # Fresh incident creation
        incident_id = event.get("event_id") or f"INC-{int(now * 1000)}"
        _active_incidents[dedup_key] = {
            "incident_id": incident_id,
            "first_seen": now,
            "last_seen": now,
            "peak_confidence": suspicion_score,
            "update_count": 1,
            "status": "DETECTED",
        }
        status = "DETECTED"
        is_update = False
        duration = 0.0

    return {
        "incident": True,
        "is_update": is_update,
        "incident_id": incident_id,
        "status": status,
        "suspicion_score": suspicion_score,
        "priority": cfg.get("priority", "medium"),
        "playbook": cfg.get("playbook", {}),
        "duration": duration,
        "timeline": {
            "first_detected": _active_incidents[dedup_key]["first_seen"],
            "last_updated": now,
            "frames_considered": frames_considered,
            "window_sec": cfg["window_sec"],
        },
        "event": event,
    }
