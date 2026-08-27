"""
SentinelAI Vision & Behavior Pipeline Test Suite

Tests:
1. Environment & Zone registry configuration across School, Home, Office
2. Phone-use spatial-temporal detector
3. Fight altercation proximity & velocity detector
4. Fire & smoke multi-frame tracker
5. Crowd density spatial detector
6. Loitering dwell-time analyzer
7. Restricted area point-in-polygon geofencing
8. After-hours schedule monitor
9. Global Person Tracking & Topology Re-ID
10. Incident Engine deduplication & lifecycle management
"""

import time
import numpy as np
from worker.registry import ModelRegistry, ENVIRONMENT_CONFIGS
from worker.behaviours import (
    PhoneUseDetector,
    FightAltercationDetector,
    FireSmokeTracker,
    CrowdDensityDetector,
    LoiteringDwellDetector,
    RestrictedZoneMonitor,
    AfterHoursScheduleMonitor,
)
from worker.reid import GlobalPersonTracker, CameraTopology
from engine import process_event, _active_incidents, _sliding_windows

def test_environment_registry_configs():
    registry = ModelRegistry()
    
    school_cfg = registry.get_environment_config("school")
    assert school_cfg.name == "school"
    assert "classroom" in school_cfg.zones
    assert "corridor" in school_cfg.zones
    assert "phone_use" in school_cfg.enabled_rules
    
    home_cfg = registry.get_environment_config("home")
    assert home_cfg.name == "home"
    assert "entrance" in home_cfg.zones
    assert "living_room" in home_cfg.zones
    assert "intrusion_detected" in home_cfg.enabled_rules

    office_cfg = registry.get_environment_config("office")
    assert office_cfg.name == "office"
    assert "open_office" in office_cfg.zones
    assert "server_room" in office_cfg.zones
    assert "after_hours_presence" in office_cfg.enabled_rules

def test_phone_use_spatial_temporal_detection():
    detector = PhoneUseDetector(min_duration=1.0)
    person = {"track_id": 101, "bbox": [100, 100, 300, 500], "confidence": 0.90}
    # Phone right inside person's upper chest region
    phone_overlapping = {"bbox": [180, 150, 220, 220], "confidence": 0.88}

    # Frame 1 at t=0.0 -> Session started, not yet triggered
    events_t0 = detector.update([person], [phone_overlapping], timestamp=1000.0)
    assert len(events_t0) == 0

    # Frame 2 at t=0.5 -> Still within min_duration
    events_t1 = detector.update([person], [phone_overlapping], timestamp=1000.5)
    assert len(events_t1) == 0

    # Frame 3 at t=1.2 -> Passes min_duration of 1.0s -> Event triggered!
    events_t2 = detector.update([person], [phone_overlapping], timestamp=1001.2)
    assert len(events_t2) == 1
    assert events_t2[0]["event_type"] == "mobile_phone_use"
    assert events_t2[0]["track_id"] == 101

    # Distant phone test: phone far away in corner (x=800, y=800) should NOT trigger
    distant_phone = {"bbox": [800, 800, 850, 890], "confidence": 0.92}
    distant_events = detector.update([person], [distant_phone], timestamp=1005.0)
    assert len(distant_events) == 0

def test_fight_altercation_detection():
    fight_detector = FightAltercationDetector(proximity_threshold=80.0, min_frames=2)
    # Two people close together with high motion
    p1 = {"track_id": 201, "bbox": [100, 100, 200, 400], "confidence": 0.9}
    p2 = {"track_id": 202, "bbox": [150, 100, 250, 400], "confidence": 0.9}

    # Frame 1
    events1 = fight_detector.update([p1, p2], timestamp=2000.0)
    assert len(events1) == 0

    # Frame 2 (moving close and fast)
    p1_moved = {"track_id": 201, "bbox": [130, 90, 230, 390], "confidence": 0.9}
    p2_moved = {"track_id": 202, "bbox": [160, 110, 260, 410], "confidence": 0.9}
    events2 = fight_detector.update([p1_moved, p2_moved], timestamp=2000.3)
    assert len(events2) == 1
    assert events2[0]["event_type"] == "fight_suspected"
    assert 201 in events2[0]["involved_tracks"]
    assert 202 in events2[0]["involved_tracks"]

def test_fire_smoke_temporal_tracker():
    fire_tracker = FireSmokeTracker(min_confirmation_frames=2, cooldown_seconds=10.0)

    # 1. Single frame anomaly should NOT trigger
    single_frame = fire_tracker.update([{"class_name": "fire", "confidence": 0.85, "bbox": [50, 50, 150, 150]}], timestamp=3000.0)
    assert len(single_frame) == 0

    # 2. Sustained frame confirms fire!
    confirmed_frame = fire_tracker.update([{"class_name": "fire", "confidence": 0.92, "bbox": [50, 50, 160, 160]}], timestamp=3000.5)
    assert len(confirmed_frame) == 1
    assert confirmed_frame[0]["event_type"] == "fire_detected"
    assert confirmed_frame[0]["priority"] == "critical"

def test_crowd_density_detector():
    crowd_detector = CrowdDensityDetector(min_people=3, duration_seconds=1.0)
    people = [
        {"track_id": 1, "bbox": [10, 10, 50, 100]},
        {"track_id": 2, "bbox": [60, 10, 100, 100]},
        {"track_id": 3, "bbox": [110, 10, 150, 100]},
    ]
    # Start of crowd
    e0 = crowd_detector.update(people, timestamp=4000.0)
    assert len(e0) == 0

    # After duration threshold
    e1 = crowd_detector.update(people, timestamp=4001.5)
    assert len(e1) == 1
    assert e1[0]["event_type"] == "crowd_detected"
    assert e1[0]["count"] == 3

def test_loitering_dwell_detector():
    loiter_detector = LoiteringDwellDetector(max_dwell_sec=2.0, max_displacement_px=50.0)
    stationary_person = {"track_id": 301, "bbox": [200, 200, 300, 500]}

    # Initial sighting
    e0 = loiter_detector.update([stationary_person], timestamp=5000.0)
    assert len(e0) == 0

    # Still stationary at same spot after dwell duration
    e1 = loiter_detector.update([stationary_person], timestamp=5002.5)
    assert len(e1) == 1
    assert e1[0]["event_type"] == "loitering_detected"
    assert e1[0]["track_id"] == 301

def test_restricted_zone_geofencing():
    # Polygon box in upper-left corner: (0,0) to (500,500)
    polygon = [(0, 0), (500, 0), (500, 500), (0, 500)]
    monitor = RestrictedZoneMonitor(polygon)

    # Person inside zone (feet at x=250, y=400)
    inside_person = {"track_id": 401, "bbox": [200, 100, 300, 400]}
    events_inside = monitor.update([inside_person], frame_w=1920, frame_h=1080)
    assert len(events_inside) == 1
    assert events_inside[0]["event_type"] == "restricted_area_entry"

    # Person outside zone (feet at x=800, y=800)
    outside_person = {"track_id": 402, "bbox": [750, 600, 850, 800]}
    events_outside = monitor.update([outside_person], frame_w=1920, frame_h=1080)
    assert len(events_outside) == 0

def test_after_hours_schedule_monitor():
    # Working hours 09:00 to 18:00
    monitor = AfterHoursScheduleMonitor(start_hour=9, end_hour=18)
    
    # 23:00 (11 PM) -> After hours
    import time
    # Construct a timestamp for 23:30 local time
    local_struct = time.localtime()
    night_struct = time.struct_time((
        local_struct.tm_year, local_struct.tm_mon, local_struct.tm_mday,
        23, 30, 0, 0, 0, -1
    ))
    night_ts = time.mktime(night_struct)
    
    events = monitor.update([{"track_id": 501, "bbox": [100, 100, 200, 300]}], timestamp=night_ts)
    assert len(events) == 1
    assert events[0]["event_type"] == "after_hours_presence"

def test_global_person_tracking_and_topology():
    tracker = GlobalPersonTracker(similarity_threshold=0.70)
    tracker.topology.add_connection("cam_hallway", "cam_classroom", min_time=1.0, max_time=30.0)

    # Fake synthetic image frame
    frame_blue_shirt = np.zeros((400, 400, 3), dtype=np.uint8)
    frame_blue_shirt[100:250, 100:250] = [200, 50, 50] # Solid distinctive color

    # Camera 1 (Hallway) sighting
    gid1, conf1 = tracker.assign_global_id(
        camera_id="cam_hallway",
        local_track_id=12,
        frame=frame_blue_shirt,
        bbox=[100, 100, 250, 350],
        timestamp=7000.0
    )
    assert gid1.startswith("P-")

    # Camera 2 (Classroom) sighting 5 seconds later (valid topology window)
    gid2, conf2 = tracker.assign_global_id(
        camera_id="cam_classroom",
        local_track_id=3,
        frame=frame_blue_shirt,
        bbox=[100, 100, 250, 350],
        timestamp=7005.0
    )
    # The person should be successfully re-identified with the SAME global ID!
    assert gid2 == gid1

def test_incident_engine_deduplication():
    _active_incidents.clear()
    _sliding_windows.clear()

    # Event 1 (t=0)
    ev1 = {
        "event_id": "ev_001",
        "tenant_id": "school1",
        "camera_id": "cam_corridor",
        "event_type": "fight",
        "confidence": 0.85,
        "timestamp": 8000.0,
    }
    r1 = process_event(ev1)
    # Frame 1 of 2 -> not enough frames yet
    assert r1["incident"] is False

    # Event 2 (t=0.5) -> cross threshold
    ev2 = dict(ev1, timestamp=8000.5, confidence=0.90)
    r2 = process_event(ev2)
    assert r2["incident"] is True
    assert r2["status"] == "DETECTED"
    assert r2["is_update"] is False
    inc_id = r2["incident_id"]

    # Event 3 (t=3.0) -> same continuous fight event should be an UPDATE, NOT a duplicate new incident
    ev3 = dict(ev1, timestamp=8003.0, confidence=0.92)
    r3 = process_event(ev3)
    assert r3["incident"] is True
    assert r3["status"] == "ACTIVE"
    assert r3["is_update"] is True
    assert r3["incident_id"] == inc_id
