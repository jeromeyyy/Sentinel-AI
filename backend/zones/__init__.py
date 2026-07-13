"""
Zone-specific detection processors.

Each zone has isolated detection logic with:
- Multi-frame buffering
- Suspicion scoring
- Threshold verification

No cross-zone logic allowed.
"""

from .outgate import OutgateProcessor
from .corridor import CorridorProcessor
from .school_ground import SchoolGroundProcessor
from .classroom import ClassroomProcessor
from .fire_only import FireOnlyProcessor

ZONE_PROCESSORS = {
    "outgate": OutgateProcessor,
    "corridor": CorridorProcessor,
    "school_ground": SchoolGroundProcessor,
    "classroom": ClassroomProcessor,
    "fire_only": FireOnlyProcessor,
}

__all__ = [
    "ZONE_PROCESSORS",
    "OutgateProcessor",
    "CorridorProcessor",
    "SchoolGroundProcessor",
    "ClassroomProcessor",
    "FireOnlyProcessor",
]
