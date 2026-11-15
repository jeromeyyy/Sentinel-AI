"""Pure geometry helpers: scaling boxes between frame sizes, zone-polygon tests, smoothing.
No heavy imports so they are unit-testable anywhere."""
from typing import Iterable, List, Optional, Sequence, Tuple

Box = Sequence[float]  # x1, y1, x2, y2
Point = Tuple[float, float]


def scale_box(box: Box, src_size: Tuple[int, int], dst_size: Tuple[int, int]) -> List[float]:
    """Map a box from a frame of src_size=(w,h) to one of dst_size=(w,h)."""
    sx = dst_size[0] / float(src_size[0])
    sy = dst_size[1] / float(src_size[1])
    x1, y1, x2, y2 = box
    return [x1 * sx, y1 * sy, x2 * sx, y2 * sy]


def clip_box(box: Box, size: Tuple[int, int]) -> List[float]:
    w, h = size
    x1, y1, x2, y2 = box
    return [min(max(x1, 0), w - 1), min(max(y1, 0), h - 1), min(max(x2, 0), w - 1), min(max(y2, 0), h - 1)]


def target_size(src_w: int, src_h: int, max_width: int) -> Tuple[int, int]:
    """Size after downscaling to max_width (never upscales), aspect ratio kept, even numbers."""
    if max_width <= 0 or src_w <= max_width:
        return src_w, src_h
    ratio = max_width / float(src_w)
    return max_width, max(2, int(round(src_h * ratio / 2)) * 2)


def box_center(box: Box) -> Point:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def box_foot(box: Box) -> Point:
    """Bottom-centre of a box: the point on the ground, better for 'inside zone' tests."""
    return ((box[0] + box[2]) / 2.0, box[3])


def point_in_polygon(pt: Point, polygon: Sequence[Point]) -> bool:
    """Ray casting. polygon is a list of (x, y); an empty/degenerate polygon means 'whole frame'."""
    if not polygon or len(polygon) < 3:
        return True
    x, y = pt
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            xcross = (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            if x < xcross:
                inside = not inside
        j = i
    return inside


def denormalize_polygon(poly_norm: Optional[Iterable[Sequence[float]]], size: Tuple[int, int]) -> List[Point]:
    """Zone polygons are stored normalised (0..1) so they survive any display/stream size."""
    if not poly_norm:
        return []
    w, h = size
    return [(float(p[0]) * w, float(p[1]) * h) for p in poly_norm]


def filter_in_zone(dets: List[dict], polygon: Sequence[Point], use: str = "center") -> List[dict]:
    """Keep detections whose box centre (or foot point) lies inside the polygon."""
    fn = box_foot if use == "foot" else box_center
    return [d for d in dets if point_in_polygon(fn(d["box"]), polygon)]


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class BoxSmoother:
    """Exponential moving average per track id, to stop box jitter.
    alpha=1 disables smoothing; lower = smoother but laggier."""

    def __init__(self, alpha: float = 0.6, max_age_s: float = 2.0):
        self.alpha = alpha
        self.max_age_s = max_age_s
        self._state = {}  # id -> (box, last_t)

    def update(self, track_id: int, box: Box, t: float) -> List[float]:
        prev = self._state.get(track_id)
        if prev is None:
            sm = list(map(float, box))
        else:
            a = self.alpha
            sm = [a * n + (1 - a) * p for n, p in zip(box, prev[0])]
        self._state[track_id] = (sm, t)
        return sm

    def prune(self, t: float):
        for k in [k for k, (_, lt) in self._state.items() if t - lt > self.max_age_s]:
            del self._state[k]
