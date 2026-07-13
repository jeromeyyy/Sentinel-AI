"""
Fire-Only Zone Processor

Events:
- fire_smoke_detected: Fire or smoke detected via shared fire/smoke model
"""

import numpy as np
from typing import List, Dict
from .base import (
    BaseZoneProcessor,
    TrackedObject,
    FrameMetadata,
    DetectionEvent,
)


class FireOnlyProcessor(BaseZoneProcessor):
    """Zone processor that emits only fire/smoke events."""

    ZONE_NAME = "fire_only"
    EVENT_TYPES = ["fire_smoke_detected"]
    MODEL_NAME = "fire_smoke_model.pt"

    def process_frame(
        self,
        frame: np.ndarray,
        tracked_objects: List[TrackedObject],
        metadata: FrameMetadata,
        shared_detections: Dict[str, list] = None,
    ) -> List[DetectionEvent]:
        self.temporal_buffer.add_frame(tracked_objects, metadata.timestamp)
        shared = shared_detections or {}

        fire_event = self._process_shared_fire_smoke(shared)
        if fire_event:
            return [fire_event]
        return []
