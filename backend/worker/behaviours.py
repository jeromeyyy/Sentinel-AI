"""
Behavior Modules for SentinelAI

Stateful, cross-frame behavior analysis that runs OUTSIDE zone processors:

- AfterHoursChecker : Escalates / flags events outside school schedule.
                      Also generates after_hours_intrusion events for
                      any person detected outside configured hours.
                      
                      NOTE: After-hours is now strictly >= 23:00 IST (11 PM),
                      NOT based on school hours (07:30-17:00).

- LoiteringTracker  : Tracks how long each person has been stationary
                      (utility — zone processors can instantiate this).
"""

import os
import time
import logging
from datetime import datetime, time as dtime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

# IST timezone support
try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
    PYTZ_AVAILABLE = True
except ImportError:
    IST = None
    PYTZ_AVAILABLE = False
    logging.warning("pytz not available - after-hours check will use local time")

# ============================================================================
# SCHEDULE CONFIGURATION
# ============================================================================

# After-hours intrusion starts at 23:00 IST (11 PM) - NOT school hours!
# This is strictly enforced: current_IST_hour >= 23
AFTER_HOURS_START_HOUR = int(os.getenv("AFTER_HOURS_START_HOUR", "23"))

# DEPRECATED: School hours config (kept for backward compatibility but NOT used for intrusion)
DEFAULT_SCHOOL_START = os.getenv("SCHOOL_HOURS_START", "07:30")
DEFAULT_SCHOOL_END   = os.getenv("SCHOOL_HOURS_END",   "17:00")

# Zones that should be EMPTY after hours (person = intrusion)
RESTRICTED_ZONES_AFTER_HOURS = {"corridor", "classroom", "school_ground"}

# Zones where vehicles are normal even after hours (e.g. staff parking)
VEHICLE_ALLOWED_AFTER_HOURS  = {"outgate"}

# Severity multiplier applied to events detected after hours
AFTER_HOURS_SEVERITY_MULTIPLIER = 1.5
AFTER_HOURS_SEVERITY_CAP        = 1.0


# ============================================================================
# AFTER HOURS CHECKER
# ============================================================================

class AfterHoursChecker:
    """
    Checks whether events occur outside school operating hours and:

    1. Tags every event with after_hours=True/False in metadata
    2. Escalates severity_score for after-hours events
    3. Injects after_hours_intrusion events for person detections
       outside operating hours in restricted zones

    IMPORTANT: After-hours is defined as >= 23:00 IST (11 PM), NOT school hours.
               This is strictly enforced across all zones.
    
    Called by worker.py AFTER zone processors run, before backend send.
    """

    def __init__(
        self,
        school_start: str = DEFAULT_SCHOOL_START,
        school_end:   str = DEFAULT_SCHOOL_END,
    ):
        # Keep school hours for backward compatibility but NOT used for intrusion detection
        self._start = self._parse_time(school_start)
        self._end   = self._parse_time(school_end)
        self._after_hours_start = AFTER_HOURS_START_HOUR  # 23:00 IST (11 PM)
        logging.info(
            f"AfterHoursChecker: intrusion detection starts at {self._after_hours_start}:00 IST (NOT school hours)"
        )

    @staticmethod
    def _parse_time(t: str) -> dtime:
        h, m = t.split(":")
        return dtime(int(h), int(m))

    def is_after_hours(self, ts: Optional[float] = None) -> bool:
        """
        Return True if the given timestamp (or now) is >= 23:00 IST.
        
        STRICTLY enforces: current_IST_hour >= 23 (11 PM IST)
        Does NOT use school hours (07:30-17:00).
        """
        if PYTZ_AVAILABLE:
            # Use IST timezone
            if ts:
                current_time_ist = datetime.fromtimestamp(ts, tz=IST)
            else:
                current_time_ist = datetime.now(IST)
            current_hour = current_time_ist.hour
        else:
            # Fallback to local time if pytz not available
            now = datetime.fromtimestamp(ts) if ts else datetime.now()
            current_hour = now.hour
        
        # Strictly enforce: after-hours = current hour >= 23 (11 PM)
        is_after = current_hour >= self._after_hours_start
        return is_after

    def filter(
        self,
        events:    List[Any],          # List[DetectionEvent]
        zone:      str,
        timestamp: Optional[float] = None,
    ) -> List[Any]:
        """
        Process a list of DetectionEvents:
        - Tag each with after_hours metadata
        - Escalate severity if after hours
        - Inject after_hours_intrusion event if person seen in restricted zone

        Returns the (possibly modified/extended) list.
        """
        after_hours = self.is_after_hours(timestamp)

        for event in events:
            if event.metadata is None:
                event.metadata = {}
            event.metadata["after_hours"] = after_hours

            if after_hours:
                # Escalate confidence/severity
                event.confidence = min(
                    AFTER_HOURS_SEVERITY_CAP,
                    event.confidence * AFTER_HOURS_SEVERITY_MULTIPLIER,
                )

        # Inject intrusion event if person detected in restricted zone after hours
        if after_hours and zone in RESTRICTED_ZONES_AFTER_HOURS:
            # Check if any existing event involves a person
            has_person_event = any(
                e.event_type not in ("vehicle_detected", "license_plate_detected")
                for e in events
            )
            if has_person_event or self._any_persons_in_events(events):
                intrusion = self._make_intrusion_event(events, zone)
                if intrusion:
                    events.append(intrusion)

        return events

    def _any_persons_in_events(self, events) -> bool:
        return any(
            e.event_type in (
                "mobile_usage", "fight", "crowd_formation",
                "weapon_detected", "fall_detected",
            )
            for e in events
        )

    def _make_intrusion_event(self, events, zone):
        """Build an after_hours_intrusion DetectionEvent."""
        # Import here to avoid circular imports
        try:
            from zones.base import DetectionEvent
        except ImportError:
            return None

        # Collect bboxes from existing events
        bboxes = []
        for e in events:
            bboxes.extend(e.bounding_boxes[:2])   # max 2 per event

        return DetectionEvent(
            event_type="after_hours_intrusion",
            confidence=0.90,
            bounding_boxes=bboxes[:4],
            metadata={
                "zone":        zone,
                "after_hours": True,
                "triggered_by": [e.event_type for e in events],
            },
        )


# ============================================================================
# LOITERING TRACKER
# ============================================================================

@dataclass
class LoiterRecord:
    object_id:     int
    first_seen:    float
    last_seen:     float
    last_center:   tuple
    total_movement: float = 0.0


class LoiteringTracker:
    """
    Tracks how long each person has been in approximately the same location.

    Zone processors can instantiate this to detect loitering.

    Usage:
        tracker = LoiteringTracker(threshold_seconds=60, movement_radius=40)

        # In process_frame:
        loiterers = tracker.update(persons, metadata.timestamp)
        for person_id, duration in loiterers:
            # emit loitering event
    """

    def __init__(
        self,
        threshold_seconds: float = 60.0,    # seconds before loitering alert
        movement_radius:   float = 40.0,    # pixels — max movement to be "stationary"
        expiry_seconds:    float = 10.0,    # remove record if unseen for this long
    ):
        self._threshold  = threshold_seconds
        self._radius     = movement_radius
        self._expiry     = expiry_seconds
        self._records:   Dict[int, LoiterRecord] = {}

    def update(
        self,
        persons:   List[Any],    # List[TrackedObject]
        timestamp: float,
    ) -> List[tuple]:
        """
        Update loitering state.

        Returns list of (object_id, duration_seconds) for confirmed loiterers.
        """
        import numpy as np

        now = timestamp

        # Update records
        seen_ids = set()
        for person in persons:
            pid    = person.object_id
            center = person.center
            seen_ids.add(pid)

            if pid not in self._records:
                self._records[pid] = LoiterRecord(
                    object_id=pid,
                    first_seen=now,
                    last_seen=now,
                    last_center=center,
                )
            else:
                rec = self._records[pid]
                dist = float(np.hypot(
                    center[0] - rec.last_center[0],
                    center[1] - rec.last_center[1],
                ))
                rec.total_movement += dist
                rec.last_seen       = now

                # If person moved significantly, reset timer
                if dist > self._radius:
                    rec.first_seen  = now
                    rec.last_center = center
                    rec.total_movement = 0.0

        # Expire unseen records
        for pid in list(self._records):
            if pid not in seen_ids:
                if now - self._records[pid].last_seen > self._expiry:
                    del self._records[pid]

        # Return loiterers
        loiterers = []
        for pid, rec in self._records.items():
            duration = rec.last_seen - rec.first_seen
            if duration >= self._threshold:
                loiterers.append((pid, duration))

        return loiterers

    def get_duration(self, object_id: int) -> float:
        """Get stationary duration for a specific object."""
        rec = self._records.get(object_id)
        if rec is None:
            return 0.0
        return rec.last_seen - rec.first_seen

    def reset(self, object_id: int):
        """Manually reset a loitering record (e.g. after event emitted)."""
        self._records.pop(object_id, None)

    def reset_all(self):
        self._records.clear()