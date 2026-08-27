import time
from datetime import datetime, timedelta
import jwt
from auth import (
    create_jwt_token,
    decode_jwt_token,
    get_google_auth_url,
    generate_oauth_state,
    validate_oauth_state,
    User,
    JWT_SECRET,
    JWT_ALGORITHM,
)

def test_user_model_creation():
    user = User(
        id="google_12345",
        email="testuser@example.com",
        name="Test User",
        picture="https://example.com/pic.jpg",
        role="user",
        tenant_id="tenant_google_12345"
    )
    assert user.id == "google_12345"
    assert user.email == "testuser@example.com"
    assert user.name == "Test User"
    assert user.tenant_id == "tenant_google_12345"

def test_jwt_token_generation_and_validation():
    user = User(
        id="google_user_99",
        email="alex@sentinelai.com",
        name="Alex Sentinel",
        role="admin",
        tenant_id="tenant_99"
    )
    token = create_jwt_token(user)
    assert isinstance(token, str)
    assert len(token) > 20

    payload = decode_jwt_token(token)
    assert payload["sub"] == "google_user_99"
    assert payload["email"] == "alex@sentinelai.com"
    assert payload["name"] == "Alex Sentinel"
    assert payload["role"] == "admin"
    assert payload["tenant_id"] == "tenant_99"

def test_expired_jwt_token():
    user = User(
        id="user_exp",
        email="exp@example.com",
        name="Expired User"
    )
    expired_payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "exp": datetime.utcnow() - timedelta(hours=1),
        "iat": datetime.utcnow() - timedelta(hours=2),
    }
    expired_token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    error_caught = False
    try:
        decode_jwt_token(expired_token)
    except Exception as e:
        error_caught = True
        assert "expired" in str(e).lower()
    assert error_caught is True

def test_oauth_state_generation_and_validation():
    state = generate_oauth_state()
    assert len(state) >= 32
    assert validate_oauth_state(state) is True
    # Second validation should fail (consumed state)
    assert validate_oauth_state(state) is False

def test_google_auth_url_structure():
    url = get_google_auth_url(state="custom_test_state_123")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "state=custom_test_state_123" in url
    assert "response_type=code" in url
    assert "scope=openid" in url
