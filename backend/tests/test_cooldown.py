from pipeline.cooldown import EVENT_TYPE_COOLDOWNS, EventCooldownManager


def make():
    t = [1000.0]
    return EventCooldownManager(clock=lambda: t[0]), t


def test_first_event_passes_duplicate_suppressed():
    m, t = make()
    assert m.should_emit("cam1", "fight", 0.6)
    assert not m.should_emit("cam1", "fight", 0.6)


def test_emits_again_after_per_type_cooldown():
    m, t = make()
    assert m.should_emit("cam1", "mobile_usage", 0.5)
    t[0] += EVENT_TYPE_COOLDOWNS["mobile_usage"] - 0.1
    assert not m.should_emit("cam1", "mobile_usage", 0.5)
    t[0] += 0.2
    assert m.should_emit("cam1", "mobile_usage", 0.5)


def test_confidence_jump_bypasses_cooldown():
    m, t = make()
    assert m.should_emit("cam1", "fight", 0.50)
    assert not m.should_emit("cam1", "fight", 0.54)  # < 10 % increase
    assert m.should_emit("cam1", "fight", 0.70)      # > 10 % increase


def test_cameras_and_types_are_independent():
    m, t = make()
    assert m.should_emit("cam1", "fight", 0.5)
    assert m.should_emit("cam2", "fight", 0.5)
    assert m.should_emit("cam1", "crowd_formation", 0.5)


def test_unknown_type_uses_default_and_reset_clears():
    m, t = make()
    assert m.should_emit("c", "weird", 0.5)
    t[0] += 9.9
    assert not m.should_emit("c", "weird", 0.5)
    t[0] += 0.2
    assert m.should_emit("c", "weird", 0.5)
    m.reset("c")
    assert m.should_emit("c", "weird", 0.5)
