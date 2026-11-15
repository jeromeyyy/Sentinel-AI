import pytest
from pipeline.geometry import (BoxSmoother, clip_box, denormalize_polygon, filter_in_zone, iou,
                               point_in_polygon, scale_box, target_size)

SQUARE = [(100, 100), (300, 100), (300, 300), (100, 300)]
L_SHAPE = [(0, 0), (200, 0), (200, 100), (100, 100), (100, 200), (0, 200)]


def test_point_in_polygon_square():
    assert point_in_polygon((200, 200), SQUARE)
    assert not point_in_polygon((50, 200), SQUARE)
    assert not point_in_polygon((200, 350), SQUARE)


def test_point_in_polygon_concave():
    assert point_in_polygon((50, 150), L_SHAPE)
    assert not point_in_polygon((150, 150), L_SHAPE)  # in the notch


def test_empty_polygon_means_whole_frame():
    assert point_in_polygon((5, 5), [])
    assert point_in_polygon((5, 5), [(0, 0), (1, 1)])


def test_filter_in_zone_uses_center_and_foot():
    dets = [{"box": [150, 150, 250, 250]}, {"box": [0, 0, 60, 60]}, {"box": [250, 250, 350, 350]}]
    assert filter_in_zone(dets, SQUARE) == [dets[0]]  # third centre (300,300) is on the edge -> outside
    # foot point (bottom centre): first box foot (200,250) inside; a tall box whose centre is inside but foot is not
    tall = {"box": [150, 200, 250, 380]}  # centre (200,290) inside, foot (200,380) outside
    assert filter_in_zone([tall], SQUARE, use="center") == [tall]
    assert filter_in_zone([tall], SQUARE, use="foot") == []


def test_denormalize_polygon():
    assert denormalize_polygon([[0, 0], [1, 0], [1, 1]], (640, 360)) == [(0, 0), (640, 0), (640, 360)]
    assert denormalize_polygon(None, (640, 360)) == []


def test_scale_box_roundtrip_and_aspect():
    b = [64, 36, 320, 180]
    small = scale_box(b, (1280, 720), (640, 360))
    assert small == [32, 18, 160, 90]
    back = scale_box(small, (640, 360), (1280, 720))
    assert back == pytest.approx(b)


def test_scale_box_non_uniform():
    assert scale_box([10, 10, 20, 20], (100, 50), (200, 200)) == [20, 40, 40, 80]


def test_target_size_never_upscales_and_keeps_aspect():
    assert target_size(1920, 1080, 960) == (960, 540)
    assert target_size(640, 360, 960) == (640, 360)
    assert target_size(1000, 500, 0) == (1000, 500)
    w, h = target_size(1280, 720, 640)
    assert abs(w / h - 1280 / 720) < 0.01 and h % 2 == 0


def test_clip_box():
    assert clip_box([-5, -5, 700, 400], (640, 360)) == [0, 0, 639, 359]


def test_iou():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert iou([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(1 / 3)


def test_smoother_reduces_jitter_and_prunes():
    s = BoxSmoother(alpha=0.5, max_age_s=1.0)
    s.update(1, [0, 0, 100, 100], 0.0)
    out = s.update(1, [10, 0, 110, 100], 0.1)
    assert out == [5, 0, 105, 100]
    s.prune(5.0)
    assert s.update(1, [50, 50, 60, 60], 5.1) == [50, 50, 60, 60]  # state was dropped
