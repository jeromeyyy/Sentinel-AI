from fastapi.testclient import TestClient
from main import app, camera_configs, incidents
from auth import create_jwt_token, User

def test_tenant_data_isolation(client):
    # User A from School A
    user_a = User(
        id="user_tenant_a",
        email="admin@schoolA.edu",
        name="School A Admin",
        tenant_id="tenant_school_a"
    )
    token_a = create_jwt_token(user_a)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # User B from School B
    user_b = User(
        id="user_tenant_b",
        email="admin@schoolB.edu",
        name="School B Admin",
        tenant_id="tenant_school_b"
    )
    token_b = create_jwt_token(user_b)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Seed in-memory cameras with specific tenant_ids
    camera_configs["cam_isolated_a"] = {
        "id": "cam_isolated_a",
        "name": "School A Main Gate",
        "zone": "outgate",
        "tenant_id": "tenant_school_a",
        "active": True,
    }
    camera_configs["cam_isolated_b"] = {
        "id": "cam_isolated_b",
        "name": "School B Main Gate",
        "zone": "outgate",
        "tenant_id": "tenant_school_b",
        "active": True,
    }

    # Seed in-memory incidents with specific tenant_ids
    incidents["inc_tenant_a"] = {
        "event": {
            "event_id": "inc_tenant_a",
            "camera_id": "cam_isolated_a",
            "tenant_id": "tenant_school_a",
            "event_type": "fight",
            "confidence": 0.9,
            "timestamp": 1700000000,
        },
        "alert": {
            "priority": "high",
            "summary": "Fight detected at School A",
            "suspicion_score": 0.85,
        }
    }
    incidents["inc_tenant_b"] = {
        "event": {
            "event_id": "inc_tenant_b",
            "camera_id": "cam_isolated_b",
            "tenant_id": "tenant_school_b",
            "event_type": "intrusion",
            "confidence": 0.8,
            "timestamp": 1700000000,
        },
        "alert": {
            "priority": "high",
            "summary": "Intrusion detected at School B",
            "suspicion_score": 0.80,
        }
    }

    # 1. User A lists cameras - must see only School A cameras, never School B
    resp_a = client.get("/api/cameras", headers=headers_a)
    assert resp_a.status_code == 200
    cams_a = [c["id"] for c in resp_a.json()["cameras"]]
    assert "cam_isolated_a" in cams_a
    assert "cam_isolated_b" not in cams_a

    # 2. User B lists cameras - must see only School B cameras, never School A
    resp_b = client.get("/api/cameras", headers=headers_b)
    assert resp_b.status_code == 200
    cams_b = [c["id"] for c in resp_b.json()["cameras"]]
    assert "cam_isolated_b" in cams_b
    assert "cam_isolated_a" not in cams_b

    # 3. User A lists incidents - must see only School A incidents
    inc_resp_a = client.get("/incidents", headers=headers_a)
    assert inc_resp_a.status_code == 200
    inc_ids_a = [item["id"] for item in inc_resp_a.json()["incidents"]]
    assert "inc_tenant_a" in inc_ids_a
    assert "inc_tenant_b" not in inc_ids_a

    # 4. User B lists incidents - must see only School B incidents
    inc_resp_b = client.get("/incidents", headers=headers_b)
    assert inc_resp_b.status_code == 200
    inc_ids_b = [item["id"] for item in inc_resp_b.json()["incidents"]]
    assert "inc_tenant_b" in inc_ids_b
    assert "inc_tenant_a" not in inc_ids_b
