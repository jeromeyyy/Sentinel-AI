"""Zone logic on top of tracked objects, with temporal confirmation.

Everything here is a HEURISTIC over detector output except plain object detection
(person / vehicle / cell phone from COCO YOLO). In particular:
  - fight_suspected style "fight" events = proximity + relative motion over a time window.
    There is no trained violence classifier in this repo.
  - gate_accident = a vehicle that was moving, stopped for N seconds while touching another
    vehicle/person box. It will miss slow collisions and fire on a normal queue stop at a barrier.
  - fall = a person box that stays much wider than tall for N seconds.
A fine-tuned model on labelled clips is needed for production-grade fight/accident detection
(see README, 'Limitations')."""
import math
from collections import defaultdict, deque
from typing import Dict, List, Optional, Sequence, Tuple

from .config import PipelineConfig
from .geometry import box_center, box_foot, denormalize_polygon, filter_in_zone, iou, point_in_polygon

PERSON = 0
PHONE = 67
VEHICLE_IDS = (2, 3, 5, 7)  # car, motorcycle, bus, truck

# COCO classes the shared model is asked for, per zone (fewer classes = faster NMS, fewer false boxes)
ZONE_CLASSES: Dict[str, List[int]] = {
    "outgate": [PERSON, *VEHICLE_IDS],
    "corridor": [PERSON],
    "school_ground": [PERSON],
    "classroom": [PERSON, PHONE],
    "fire_only": [],
}


class Persist:
    """Condition must hold continuously for `seconds` (brief gaps up to `grace` are bridged).
    Returns True once confirmed, and keeps returning True while the condition keeps holding."""

    def __init__(self, grace: float = 0.8):
        self.grace = grace
        self._start: Dict[str, float] = {}
        self._last_true: Dict[str, float] = {}

    def held(self, key: str, cond: bool, t: float, seconds: float) -> bool:
        if cond:
            self._last_true[key] = t
            self._start.setdefault(key, t)
            return (t - self._start[key]) >= seconds
        if key in self._last_true and t - self._last_true[key] <= self.grace:
            return key in self._start and (self._last_true[key] - self._start[key]) >= seconds
        self._start.pop(key, None)
        self._last_true.pop(key, None)
        return False


class MotionHistory:
    def __init__(self, horizon_s: float = 8.0):
        self.h = horizon_s
        self.pts: Dict[int, deque] = defaultdict(deque)  # id -> (t, cx, cy, ref_len)

    def add(self, tracks: List[dict], t: float):
        seen = set()
        for tr in tracks:
            cx, cy = box_center(tr["box"])
            ref = max(tr["box"][3] - tr["box"][1], tr["box"][2] - tr["box"][0], 1.0)
            dq = self.pts[tr["id"]]
            dq.append((t, cx, cy, ref))
            while dq and t - dq[0][0] > self.h:
                dq.popleft()
            seen.add(tr["id"])
        for k in [k for k, dq in self.pts.items() if k not in seen and dq and t - dq[-1][0] > self.h]:
            del self.pts[k]

    def speed(self, tid: int, window: float, t_end: Optional[float] = None) -> Optional[float]:
        """Mean speed in object-sizes per second over the last `window` seconds (None if no data)."""
        dq = self.pts.get(tid)
        if not dq or len(dq) < 2:
            return None
        t_end = dq[-1][0] if t_end is None else t_end
        pts = [p for p in dq if t_end - window <= p[0] <= t_end]
        if len(pts) < 2:
            return None
        dt = pts[-1][0] - pts[0][0]
        if dt <= 0:
            return None
        dist = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        return dist / pts[-1][3] / dt

    def path_speed(self, tid: int, window: float) -> Optional[float]:
        """Like speed() but sums every step (path length), so back-and-forth thrashing counts as motion."""
        dq = self.pts.get(tid)
        if not dq or len(dq) < 2:
            return None
        t_end = dq[-1][0]
        pts = [p for p in dq if t_end - window <= p[0]]
        if len(pts) < 3 or pts[-1][0] - pts[0][0] <= 0:
            return None
        path = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(pts, pts[1:]))
        return path / pts[-1][3] / (pts[-1][0] - pts[0][0])

    def velocity(self, tid: int, window: float = 0.6) -> Tuple[float, float]:
        dq = self.pts.get(tid)
        if not dq or len(dq) < 2:
            return 0.0, 0.0
        pts = [p for p in dq if dq[-1][0] - window <= p[0]]
        if len(pts) < 2 or pts[-1][0] - pts[0][0] <= 0:
            return 0.0, 0.0
        dt = pts[-1][0] - pts[0][0]
        return (pts[-1][1] - pts[0][1]) / dt, (pts[-1][2] - pts[0][2]) / dt


class ZoneAnalytics:
    def __init__(self, zone: str, cfg: PipelineConfig, polygon_norm=None):
        self.zone = zone
        self.cfg = cfg
        self.polygon_norm = polygon_norm or []
        self.persist = Persist()
        self.motion = MotionHistory()
        self._phone_streak = 0
        self._was_moving: Dict[int, float] = {}
        self._extra_hits: Dict[str, int] = defaultdict(int)

    def polygon(self, size: Tuple[int, int]):
        return denormalize_polygon(self.polygon_norm, size)

    def in_zone(self, tracks, size):
        return filter_in_zone(tracks, self.polygon(size), use="foot")

    # ------------------------------------------------------------------ main
    def update(self, tracks: List[dict], phones: List[dict], t: float, size: Tuple[int, int]) -> List[dict]:
        """tracks: tracked persons/vehicles; phones: untracked phone detections (classroom)."""
        poly = self.polygon(size)
        zt = [x for x in tracks if point_in_polygon(box_foot(x["box"]), poly)]
        self.motion.add(zt, t)
        persons = [x for x in zt if x["cls"] == PERSON]
        vehicles = [x for x in zt if x["cls"] in VEHICLE_IDS]
        events: List[dict] = []

        if self.zone == "outgate":
            events += self._vehicles(vehicles, persons, t)
        if self.zone in ("corridor", "school_ground"):
            events += self._crowd(persons, t)
        if self.zone in ("corridor", "school_ground", "classroom"):
            events += self._fight(persons, t)
        if self.zone == "school_ground" or self.zone == "corridor":
            events += self._fall(persons, t)
        if self.zone == "classroom":
            zp = [p for p in phones if point_in_polygon(box_center(p["box"]), poly)]
            events += self._phone(zp, persons, t)
        return events

    # ---------------------------------------------------------------- rules
    def _vehicles(self, vehicles, persons, t):
        ev = []
        if self.persist.held("vehicle", bool(vehicles), t, 1.0):
            ev.append(self._ev("vehicle_detected", max(v["conf"] for v in vehicles), vehicles,
                               {"vehicle_count": len(vehicles), "kind": "detector"}))
        for v in vehicles:
            sp_recent = self.motion.speed(v["id"], 1.0)
            sp_before = self.motion.speed(v["id"], 4.0, t_end=t - self.cfg.stopped_seconds)
            if sp_before is not None and sp_before > 0.3:
                self._was_moving[v["id"]] = t
            stopped = sp_recent is not None and sp_recent < 0.05
            was_moving = t - self._was_moving.get(v["id"], -1e9) < 8.0
            others = [o for o in vehicles + persons if o["id"] != v["id"]]
            touching = [o for o in others if iou(v["box"], o["box"]) > 0.05]
            cond = stopped and was_moving and bool(touching)
            if self.persist.held(f"acc{v['id']}", cond, t, self.cfg.stopped_seconds):
                ev.append(self._ev("gate_accident", 0.6, [v] + touching[:2],
                                   {"method": "heuristic_stop_after_motion_with_overlap", "track_id": v["id"]}))
        return ev

    def _crowd(self, persons, t):
        n = len(persons)
        if self.persist.held("crowd", n >= self.cfg.crowd_min_people, t, self.cfg.crowd_seconds):
            return [self._ev("crowd_formation", min(0.95, 0.5 + 0.05 * n), persons,
                             {"people_count": n, "threshold": self.cfg.crowd_min_people,
                              "seconds": self.cfg.crowd_seconds, "method": "count_in_polygon_over_time"})]
        return []

    def _fight(self, persons, t):
        best, best_pair = 0.0, None
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                a, b = persons[i], persons[j]
                ca, cb = box_center(a["box"]), box_center(b["box"])
                ref = max(a["box"][3] - a["box"][1], b["box"][3] - b["box"][1], 1.0)
                if math.dist(ca, cb) / ref > 1.0:
                    continue
                sa, sb = self.motion.path_speed(a["id"], 1.2), self.motion.path_speed(b["id"], 1.2)
                if sa is None or sb is None:
                    continue
                score = (sa + sb) / 2.0
                if score > best:
                    best, best_pair = score, (a, b)
        cond = best_pair is not None and best > 1.2  # both fast (object-heights/s) and within one body height
        if self.persist.held("fight", cond, t, self.cfg.fight_seconds):
            return [self._ev("fight", min(0.85, 0.5 + 0.1 * best), list(best_pair),
                             {"method": "heuristic_proximity_motion", "is_trained_classifier": False,
                              "relative_motion": round(best, 2), "seconds": self.cfg.fight_seconds})]
        return []

    def _fall(self, persons, t):
        ev = []
        for p in persons:
            w = p["box"][2] - p["box"][0]
            h = p["box"][3] - p["box"][1]
            cond = w > 1.3 * h and p["conf"] > 0.5
            if self.persist.held(f"fall{p['id']}", cond, t, 1.5):
                ev.append(self._ev("fall_detected", 0.6, [p], {"method": "heuristic_aspect_ratio", "track_id": p["id"]}))
        return ev

    def _phone(self, phones, persons, t):
        near = []
        for ph in phones:
            cx, cy = box_center(ph["box"])
            for p in persons:
                x1, y1, x2, y2 = p["box"]
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    near.append(ph)
                    break
        self._phone_streak = self._phone_streak + 1 if near else 0
        if self._phone_streak >= self.cfg.confirm_phone_frames:
            return [self._ev("mobile_usage", max(p["conf"] for p in near), near,
                             {"confirmed_cycles": self._phone_streak, "kind": "detector"})]
        return []

    def update_extra(self, weapons: List[dict], fire: List[dict]) -> List[dict]:
        """Weapon and fire/smoke detections from the optional extra models; 2 consecutive hits."""
        ev = []
        for key, items, etype in (("weapon", weapons, "weapon_detected"), ("fire", fire, "fire_smoke_detected")):
            self._extra_hits[key] = self._extra_hits[key] + 1 if items else 0
            if self._extra_hits[key] >= 2:
                ev.append({"event_type": etype, "confidence": max(i["conf"] for i in items),
                           "boxes": [i["box"] for i in items], "metadata": {"kind": "extra_model", "classes": sorted({i["name"] for i in items})}})
        return ev

    @staticmethod
    def _ev(etype, conf, objs, meta):
        return {"event_type": etype, "confidence": float(conf), "boxes": [list(map(float, o["box"])) for o in objs], "metadata": meta}
