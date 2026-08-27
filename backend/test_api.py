from fastapi.testclient import TestClient
from main import app
from auth import create_jwt_token, User

def get_client():
    return TestClient(app)

def get_auth_headers():
    user = User(
        id="test_sub_101",
        email="test_pilot@sentinelai.com",
        name="Pilot User",
        role="user",
        tenant_id="tenant_pilot"
    )
    token = create_jwt_token(user)
    return {"Authorization": f"Bearer {token}"}

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "cameras" in data
    assert "incidents" in data

def test_zones_endpoint(client):
    response = client.get("/api/zones")
    assert response.status_code == 200
    data = response.json()
    assert "zones" in data
    assert "corridor" in data["zones"]
    assert "outgate" in data["zones"]

def test_modules_endpoint(client):
    response = client.get("/api/modules")
    assert response.status_code == 200
    data = response.json()
    assert "modules" in data
    assert "school" in data["modules"]

def test_auth_verify_unauthenticated(client):
    response = client.get("/auth/verify")
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert data["user"] is None

def test_auth_verify_authenticated(client, auth_headers):
    response = client.get("/auth/verify", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["user"]["email"] == "test_pilot@sentinelai.com"
    assert data["user"]["name"] == "Pilot User"

def test_auth_me_endpoint(client, auth_headers):
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test_pilot@sentinelai.com"
    assert data["role"] == "user"

def test_stats_endpoint(client, auth_headers):
    response = client.get("/api/stats", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_incidents" in data
    assert "active_cameras" in data
    assert "total_cameras" in data
