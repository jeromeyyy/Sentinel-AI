import json
from pathlib import Path
import threading
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

CAMERAS_FILE = DATA_DIR / "cameras.json"
INCIDENTS_FILE = DATA_DIR / "incidents.json"
TENANTS_FILE = DATA_DIR / "tenants.json"

_lock = threading.Lock()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_cameras() -> List[Dict[str, Any]]:
    return _load_json(CAMERAS_FILE, [])


def save_cameras(cameras: List[Dict[str, Any]]) -> None:
    with _lock:
        _save_json(CAMERAS_FILE, cameras)


def load_incidents() -> List[Dict[str, Any]]:
    return _load_json(INCIDENTS_FILE, [])


def save_incidents(incidents: List[Dict[str, Any]]) -> None:
    with _lock:
        _save_json(INCIDENTS_FILE, incidents)


def append_incident(entry: Dict[str, Any]) -> None:
    with _lock:
        data = _load_json(INCIDENTS_FILE, [])
        data.append(entry)
        _save_json(INCIDENTS_FILE, data)


def load_tenants() -> List[Dict[str, Any]]:
    return _load_json(TENANTS_FILE, [])


def save_tenants(tenants: List[Dict[str, Any]]) -> None:
    with _lock:
        _save_json(TENANTS_FILE, tenants)
