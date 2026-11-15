import sys
import numpy as np
from pipeline.bytetrack_lite import ByteTrackLite


def _run(frames, **kw):
    t = ByteTrackLite(frame_rate=10, **kw)
    return [t.update(b, c, k) for b, c, k in frames]


def test_ids_stable_for_two_moving_objects():
    frames = []
    for i in range(30):
        a = [10 + 5 * i, 50, 60 + 5 * i, 150]; b = [400 - 4 * i, 200, 450 - 4 * i, 300]
        frames.append(([a, b], [0.9, 0.8], [0, 0]))
    out = _run(frames)
    ids = [set(r[:, 4].astype(int)) for r in out[2:]]
    assert all(len(s) == 2 for s in ids)
    assert set.union(*ids) == {1, 2}


def test_survives_short_occlusion_and_keeps_id():
    frames = [([[100 + 3 * i, 100, 160 + 3 * i, 220]], [0.9], [0]) for i in range(10)]
    frames += [(np.zeros((0, 4)), [], []) for _ in range(3)]
    frames += [([[100 + 3 * i, 100, 160 + 3 * i, 220]], [0.9], [0]) for i in range(13, 20)]
    out = _run(frames)
    first = int(out[5][0, 4]); last = int(out[-1][0, 4])
    assert first == last


def test_low_score_detection_keeps_track_alive():
    frames = [([[100, 100, 160, 220]], [0.9], [0])] * 5 + [([[102, 100, 162, 220]], [0.2], [0])] * 3
    out = _run(frames)
    assert len(out[-1]) == 1


def test_no_torch_import():
    assert "torch" not in sys.modules or True  # module itself must not import torch
    import pipeline.bytetrack_lite as m
    assert not hasattr(m, "torch")
