from pipeline.analytics import PERSON, ZoneAnalytics, Persist
from pipeline.config import load_config

CFG = load_config()
SIZE = (1000, 600)


def person(i, x, y=300, w=60, h=160, conf=0.9):
    return {"id": i, "cls": PERSON, "name": "person", "conf": conf, "box": [x, y, x + w, y + h]}


def run(za, frames, dt=0.33):
    out = []
    t = 100.0
    for tracks in frames:
        out += za.update(tracks, [], t, SIZE)
        t += dt
    return out


def test_persist_requires_continuous_hold_and_bridges_short_gaps():
    p = Persist(grace=0.5)
    assert not p.held("k", True, 0.0, 2.0)
    assert not p.held("k", True, 1.0, 2.0)
    assert p.held("k", True, 2.1, 2.0)
    assert p.held("k", False, 2.4, 2.0)      # 0.3 s gap bridged
    assert not p.held("k", False, 3.5, 2.0)  # real gap resets
    assert not p.held("k", True, 3.6, 2.0)


def test_crowd_needs_count_and_duration():
    za = ZoneAnalytics("corridor", CFG)
    five = [person(i, 100 + i * 100) for i in range(5)]
    assert run(za, [five] * 4) == []               # 1.3 s: too short
    za = ZoneAnalytics("corridor", CFG)
    ev = run(za, [five] * 14)                      # ~4.3 s
    assert any(e["event_type"] == "crowd_formation" for e in ev)
    za = ZoneAnalytics("corridor", CFG)
    assert run(za, [five[:3]] * 20) == []          # only 3 people


def test_crowd_only_counts_people_inside_polygon():
    left_half = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
    za = ZoneAnalytics("corridor", CFG, polygon_norm=left_half)
    people = [person(i, 50 + i * 60) for i in range(3)] + [person(10 + i, 700 + i * 60) for i in range(4)]  # 3 left, 4 right
    assert run(za, [people] * 20) == []
    za = ZoneAnalytics("corridor", CFG, polygon_norm=left_half)
    people = [person(i, 20 + i * 70) for i in range(6)]  # 6 on the left
    assert any(e["event_type"] == "crowd_formation" for e in run(za, [people] * 14))


def test_fight_requires_proximity_and_sustained_fast_motion():
    za = ZoneAnalytics("corridor", CFG)
    frames = []
    for k in range(20):  # two people close together, both jumping around fast
        dx = 40 if k % 2 else -40
        frames.append([person(1, 400 + dx), person(2, 470 - dx)])
    ev = run(za, frames)
    assert any(e["event_type"] == "fight" and e["metadata"]["is_trained_classifier"] is False for e in ev)


def test_standing_still_close_together_is_not_a_fight():
    za = ZoneAnalytics("corridor", CFG)
    assert run(za, [[person(1, 400), person(2, 470)]] * 30) == []


def test_far_apart_fast_people_is_not_a_fight():
    za = ZoneAnalytics("corridor", CFG)
    frames = [[person(1, 50 + 40 * (k % 2)), person(2, 850 - 40 * (k % 2))] for k in range(30)]
    assert run(za, frames) == []


def test_phone_needs_consecutive_cycles_near_a_person():
    za = ZoneAnalytics("classroom", CFG)
    p = person(1, 400)
    phone = {"id": -1, "cls": 67, "name": "cell phone", "conf": 0.4, "box": [420, 340, 440, 370]}
    ev = []
    for i in range(CFG.confirm_phone_frames - 1):
        ev += za.update([p], [phone], 100 + i, SIZE)
    assert ev == []
    ev += za.update([p], [phone], 110, SIZE)
    assert any(e["event_type"] == "mobile_usage" for e in ev)
    # a phone far from any person never confirms
    za = ZoneAnalytics("classroom", CFG)
    far = dict(phone, box=[900, 50, 920, 80])
    assert all(za.update([p], [far], 100 + i, SIZE) == [] for i in range(10))


def test_stopped_vehicle_with_overlap_after_motion_is_accident_but_moving_is_not():
    za = ZoneAnalytics("outgate", CFG)
    car = lambda x: {"id": 7, "cls": 2, "name": "car", "conf": 0.9, "box": [x, 300, x + 200, 400]}
    other = {"id": 8, "cls": 2, "name": "car", "conf": 0.9, "box": [500, 310, 700, 410]}
    frames = [[car(100 + 40 * k), other] for k in range(8)]       # car drives into the other car
    frames += [[car(380), other]] * 18                            # then stays put, overlapping
    ev = run(za, frames)
    assert any(e["event_type"] == "gate_accident" for e in ev)
    za = ZoneAnalytics("outgate", CFG)
    moving = [[car(100 + 30 * k), dict(other, box=[900, 50, 960, 90])] for k in range(30)]
    assert not any(e["event_type"] == "gate_accident" for e in run(za, moving))
