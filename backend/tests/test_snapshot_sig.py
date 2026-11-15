import time
import pytest
pytest.importorskip("fastapi")


def _main(monkeypatch, secret):
    monkeypatch.setenv("SNAPSHOT_SECRET", secret)
    import importlib, main
    return importlib.reload(main)


def test_signed_link_roundtrip_and_tamper(monkeypatch):
    m = _main(monkeypatch, "x" * 32)
    path = m.signed_snapshot_path("evt_1.jpg")
    q = dict(p.split("=") for p in path.split("?")[1].split("&"))
    assert m._snap_sig("evt_1.jpg", int(q["exp"])) == q["sig"]
    assert m._snap_sig("evt_2.jpg", int(q["exp"])) != q["sig"]


def test_rejects_unsigned_and_expired(monkeypatch):
    m = _main(monkeypatch, "x" * 32)
    assert m.get_snapshot("evt_1.jpg").status_code == 403
    exp = int(time.time()) - 5
    assert m.get_snapshot("evt_1.jpg", exp, m._snap_sig("evt_1.jpg", exp)).status_code == 403


def test_disabled_without_stable_secret(monkeypatch):
    m = _main(monkeypatch, "")
    assert m.signed_snapshot_path("evt_1.jpg") is None
    assert m.get_snapshot("evt_1.jpg").status_code == 503
