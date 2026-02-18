"""
Outgate Zone Processor - Vehicle detection and gate accidents.

Events:
- vehicle_detected: Vehicle (car/bus/truck/motorcycle) in gate area
- gate_accident: Vehicle-person proximity incident
"""

import time
import numpy as np
from typing import List, Dict, Tuple
from .base import (
    BaseZoneProcessor,
    TrackedObject,
    FrameMetadata,
    DetectionEvent,
)

VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck"}


class VehicleMotionAnalyzer:
    """
    Analyzes vehicle motion to detect collision risk.
    
    Tracks vehicle positions across frames to compute velocity
    and determine if vehicle is approaching a person.
    """
    
    def __init__(self):
        self._prev_positions: Dict[int, Tuple[float, float]] = {}
    
    def get_velocity(self, vehicle: TrackedObject) -> Tuple[float, float]:
        """
        Compute velocity of vehicle in pixels/frame.
        
        Returns: (vx, vy) velocity vector
        """
        vid = vehicle.object_id
        curr_pos = vehicle.center
        
        if vid not in self._prev_positions:
            self._prev_positions[vid] = curr_pos
            return (0.0, 0.0)
        
        prev_x, prev_y = self._prev_positions[vid]
        curr_x, curr_y = curr_pos
        
        vx = float(curr_x - prev_x)
        vy = float(curr_y - prev_y)
        
        self._prev_positions[vid] = curr_pos
        return (vx, vy)
    
    def is_approaching(self, vehicle: TrackedObject, person: TrackedObject, min_velocity: float = 1.0) -> bool:
        """
        Check if vehicle is moving TOWARD person.
        
        Computes dot product of vehicle velocity and vector from vehicle to person.
        Positive = moving toward, negative = moving away.
        
        Args:
            vehicle: Vehicle TrackedObject
            person: Person TrackedObject
            min_velocity: Minimum velocity threshold (pixels/frame) to consider motion
        
        Returns: True if vehicle actively approaching
        """
        vx, vy = self.get_velocity(vehicle)
        
        # Check if vehicle is actually moving
        velocity_mag = np.sqrt(vx**2 + vy**2)
        if velocity_mag < min_velocity:
            return False
        
        # Vector FROM vehicle TO person (this is direction toward target)
        dx = person.center[0] - vehicle.center[0]
        dy = person.center[1] - vehicle.center[1]
        
        # Dot product: if velocity is in direction of person vector, positive
        dot_product = vx * dx + vy * dy
        
        # Positive dot product = moving toward person
        return dot_product > 30.0  # Threshold in pixels
    
    def cleanup_lost_vehicles(self, active_vehicle_ids: List[int]):
        """Remove position tracking for vehicles no longer detected."""
        lost_ids = [vid for vid in self._prev_positions if vid not in active_vehicle_ids]
        for vid in lost_ids:
            del self._prev_positions[vid]


class OutgateProcessor(BaseZoneProcessor):
    """
    Outgate zone processor for vehicle and accident detection.
    
    Uses yolov8n.pt (speed priority for real-time vehicle tracking).
    
    Detection logic:
    1. vehicle_detected: Any vehicle with confidence > 0.5
    2. gate_accident: Vehicle + person overlap/proximity sustained 3+ frames
    """
    
    ZONE_NAME = "outgate"
    EVENT_TYPES = ["vehicle_detected", "gate_accident"]
    MODEL_NAME = "yolov8n.pt"
    
    # Zone-specific thresholds
    VEHICLE_CONFIDENCE_THRESHOLD = 0.4  # Lowered from 0.5
    ACCIDENT_IOU_THRESHOLD = 0.06  # Lowered from 0.08
    ACCIDENT_DISTANCE_THRESHOLD = 150  # Increased from 120 pixels
    MIN_ACCIDENT_FRAMES = 3  # Increased from 2 for more robust detection
    ACCIDENT_SUSPICION_INCREMENT_STATIC = 0.15  # For static proximity
    ACCIDENT_SUSPICION_INCREMENT_APPROACH = 0.40  # For vehicle approaching (higher confidence)
    
    def __init__(self, camera_id: str):
        super().__init__(camera_id)
        self._accident_frame_count = 0
        self._vehicle_detected_cooldown = 5.0  # More frequent updates allowed
        self._motion_analyzer = VehicleMotionAnalyzer()
        self._prev_poses: Dict[int, List[List[float]]] = {}  # Track previous poses for collision detection
        
        # Track vehicle presence for accident validation
        self._last_vehicle_time: float = 0.0
        self._last_vehicle_ids: List[int] = []
        self._VEHICLE_MEMORY_SECONDS: float = 2.0  # Remember vehicles for 2 seconds
    
    def process_frame(
        self, 
        frame: np.ndarray, 
        tracked_objects: List[TrackedObject], 
        metadata: FrameMetadata,
        shared_detections: Dict[str, list] = None,
    ) -> List[DetectionEvent]:
        """
        Process frame for outgate zone events.
        
        Args:
            frame: Video frame
            tracked_objects: Detected and tracked objects
            metadata: Frame metadata
            shared_detections: Shared detections {poses, weapons, fire_smoke, ...}
        """
        
        # Update temporal buffer
        self.temporal_buffer.add_frame(tracked_objects, metadata.timestamp)
        
        events = []
        
        # Separate objects by class
        vehicles = [obj for obj in tracked_objects if obj.class_name in VEHICLE_CLASSES]
        persons = [obj for obj in tracked_objects if obj.class_name == "person"]
        
        # Get poses from shared detections (for skeleton-based collision detection)
        poses = (shared_detections or {}).get("poses", [])
        
        # 1. Vehicle Detection
        vehicle_event = self._detect_vehicle(vehicles)
        if vehicle_event:
            events.append(vehicle_event)
        
        # 2. Gate Accident Detection (with skeleton-based impact detection)
        accident_event = self._detect_accident(vehicles, persons, poses)
        if accident_event:
            events.append(accident_event)
        
        # Update pose history for next frame
        self._update_pose_history(poses)
        
        return events
    
    def _detect_vehicle(self, vehicles: List[TrackedObject]) -> DetectionEvent | None:
        """Detect vehicles in gate area."""
        if not vehicles:
            self._update_suspicion("vehicle_detected", False)
            return None
        
        # Filter by confidence
        confident_vehicles = [v for v in vehicles if v.confidence >= self.VEHICLE_CONFIDENCE_THRESHOLD]
        if not confident_vehicles:
            self._update_suspicion("vehicle_detected", False)
            return None
        
        # Update suspicion score
        suspicion = self._update_suspicion("vehicle_detected", True, increment=0.2)
        
        # Need sustained detection
        frame_count = self.temporal_buffer.increment_event("vehicle_detected")
        
        if frame_count < 2 or suspicion < 0.4:
            return None
        
        if not self._can_emit_event("vehicle_detected"):
            return None
        
        # Get best vehicle
        best = max(confident_vehicles, key=lambda v: v.confidence)
        
        self._mark_event_emitted("vehicle_detected")
        self.temporal_buffer.reset_event("vehicle_detected")
        
        return DetectionEvent(
            event_type="vehicle_detected",
            confidence=best.confidence,
            bounding_boxes=[v.bbox for v in confident_vehicles[:5]],  # Max 5 vehicles
            metadata={
                "vehicle_count": len(confident_vehicles),
                "vehicle_ids": [v.object_id for v in confident_vehicles[:5]],
            }
        )
    
    def _detect_accident(
        self, 
        vehicles: List[TrackedObject], 
        persons: List[TrackedObject],
        poses: List[Dict] = None,
    ) -> DetectionEvent | None:
        """
        Detect potential gate accident using multiple indicators:
        1. Vehicle-person proximity + vehicle motion analysis
        2. Person skeleton collapse (from pose estimation)
        3. Multi-frame verification
        
        IMPORTANT: Requires vehicle presence (current or within last 2 seconds)
        to avoid false positives from person collapse alone.
        """
        # Track vehicle presence
        if vehicles:
            self._last_vehicle_time = time.time()
            self._last_vehicle_ids = [v.object_id for v in vehicles]
        
        # Check if vehicle was seen recently (even if not currently visible)
        vehicle_recently_seen = (time.time() - self._last_vehicle_time) < self._VEHICLE_MEMORY_SECONDS
        
        if not persons:
            self._accident_frame_count = 0
            self._update_suspicion("gate_accident", False)
            self.temporal_buffer.reset_event("gate_accident")
            self._motion_analyzer.cleanup_lost_vehicles([])
            return None
        
        # CRITICAL: No vehicles seen recently = no possible accident
        if not vehicles and not vehicle_recently_seen:
            self._accident_frame_count = 0
            self._update_suspicion("gate_accident", False)
            self.temporal_buffer.reset_event("gate_accident")
            self._motion_analyzer.cleanup_lost_vehicles([])
            return None
        
        # Check for close proximity or overlap
        accident_pairs = []
        active_vehicle_ids = [v.object_id for v in vehicles]
        
        for person in persons:
            for vehicle in vehicles:
                iou = self.compute_iou(person.bbox, vehicle.bbox)
                dist = self.distance_between_centers(person.center, vehicle.center)
                
                # Accident condition: overlap or very close
                if iou > self.ACCIDENT_IOU_THRESHOLD or dist < self.ACCIDENT_DISTANCE_THRESHOLD:
                    avg_conf = (person.confidence + vehicle.confidence) / 2
                    if avg_conf >= 0.4:  # Lowered from 0.5
                        # Check if vehicle is approaching (motion analysis)
                        is_approaching = self._motion_analyzer.is_approaching(vehicle, person)
                        
                        accident_pairs.append({
                            "person": person,
                            "vehicle": vehicle,
                            "iou": iou,
                            "distance": dist,
                            "confidence": avg_conf,
                            "is_approaching": is_approaching,
                        })
        
        # Cleanup motion tracker
        self._motion_analyzer.cleanup_lost_vehicles(active_vehicle_ids)
        
        # Check for skeleton-based person impact (NEW)
        impact_score = self._check_skeleton_impact(persons, poses)
        
        if not accident_pairs and impact_score < 0.5:
            self._accident_frame_count = 0
            self._update_suspicion("gate_accident", False)
            self.temporal_buffer.reset_event("gate_accident")
            return None
        
        # CASE 1: High-confidence skeleton impact (person collapsed)
        # REQUIRES: Vehicle was seen recently (accident_pairs or vehicle_recently_seen)
        if impact_score > 0.7 and (accident_pairs or vehicle_recently_seen):
            # Very confident: person was hit and fell/collapsed
            suspicion = self._update_suspicion("gate_accident", True, increment=0.90)
            self._accident_frame_count += 1
            
            if suspicion >= self.SUSPICION_THRESHOLD and not self._can_emit_event("gate_accident"):
                return None
            
            if suspicion >= self.SUSPICION_THRESHOLD:
                self._mark_event_emitted("gate_accident")
                self._accident_frame_count = 0
                self.temporal_buffer.reset_event("gate_accident")
                
                # Find best vehicle + person pair (or use last known vehicle)
                best = max(accident_pairs, key=lambda x: x["confidence"]) if accident_pairs else None
                if best:
                    bbox_pair = [best["person"].bbox, best["vehicle"].bbox]
                    from_person = best["person"].object_id
                    from_vehicle = best["vehicle"].object_id
                else:
                    # Use last known vehicle info (vehicle may have fled scene)
                    bbox_pair = [persons[0].bbox] if persons else []
                    from_person = persons[0].object_id if persons else None
                    from_vehicle = self._last_vehicle_ids[0] if self._last_vehicle_ids else None
                
                return DetectionEvent(
                    event_type="gate_accident",
                    confidence=0.95,  # High confidence: person fell
                    bounding_boxes=bbox_pair,
                    metadata={
                        "person_id": from_person,
                        "vehicle_id": from_vehicle,
                        "impact_type": "person_collapsed",
                        "suspicion_score": suspicion,
                        "skeleton_impact_score": impact_score,
                        "vehicle_visible": bool(accident_pairs),
                    }
                )
        
        # CASE 2: Proximity + motion (vehicle approaching or hitting)
        if accident_pairs:
            self._accident_frame_count += 1
            
            # Find best pair and use appropriate increment
            best = max(accident_pairs, key=lambda x: x["confidence"])
            increment = (
                self.ACCIDENT_SUSPICION_INCREMENT_APPROACH 
                if best["is_approaching"] 
                else self.ACCIDENT_SUSPICION_INCREMENT_STATIC
            )
            
            # If skeleton suggests impact, boost confidence dramatically
            if impact_score > 0.5:
                increment *= 2.0  # Double the confidence if skeleton shows damage
            
            suspicion = self._update_suspicion("gate_accident", True, increment=increment)
            
            if self._accident_frame_count < self.MIN_ACCIDENT_FRAMES:
                return None
            
            if suspicion < self.SUSPICION_THRESHOLD:
                return None
            
            if not self._can_emit_event("gate_accident"):
                return None
            
            # Emit event with full details
            self._mark_event_emitted("gate_accident")
            self._accident_frame_count = 0
            self.temporal_buffer.reset_event("gate_accident")
            
            return DetectionEvent(
                event_type="gate_accident",
                confidence=best["confidence"],
                bounding_boxes=[best["person"].bbox, best["vehicle"].bbox],
                metadata={
                    "person_id": best["person"].object_id,
                    "vehicle_id": best["vehicle"].object_id,
                    "iou": best["iou"],
                    "distance": best["distance"],
                    "is_approaching": best["is_approaching"],  # Motion indicator
                    "suspicion_score": suspicion,
                    "skeleton_impact_score": impact_score,
                }
            )
        
        # No accident detected
        return None
    
    def _check_skeleton_impact(self, persons: List[TrackedObject], poses: List[Dict]) -> float:
        """
        Check if any person shows signs of impact using skeleton data.
        
        Returns: confidence score (0.0-1.0) that person was hit
        """
        if not poses:
            return 0.0
        
        from detectors import PoseDetector
        
        max_impact_score = 0.0
        
        for pose in poses:
            keypoints = pose.get("keypoints", [])
            if not keypoints:
                continue
            
            # Get previous keypoints for this person (by track_id)
            track_id = pose.get("track_id")
            prev_keypoints = self._prev_poses.get(track_id)
            
            # Detect collapse
            result = PoseDetector.detect_person_collapse(keypoints, prev_keypoints)
            if result.get("is_collapsed"):
                max_impact_score = max(max_impact_score, result.get("confidence", 0.0))
        
        return max_impact_score
    
    def _update_pose_history(self, poses: List[Dict]):
        """Store current poses for next frame comparison."""
        if not poses:
            return
        
        for pose in poses:
            track_id = pose.get("track_id")
            keypoints = pose.get("keypoints")
            if track_id is not None and keypoints:
                self._prev_poses[track_id] = keypoints
