"""
SentinelAI Authentication Module
Google OAuth + JWT Token Authentication with Database Persistence & Fallback
"""

import os
import time
import secrets
import jwt
import httpx
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded from root .env and local .env
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

from datetime import datetime, timedelta
from typing import Optional, Dict
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Try to import db functions
try:
    from db import upsert_user as db_upsert_user, get_user_by_id as db_get_user_by_id
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
def _get_google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "")

def _get_google_client_secret() -> str:
    return os.getenv("GOOGLE_CLIENT_SECRET", "")

def _get_google_redirect_uri() -> str:
    return os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

GOOGLE_CLIENT_ID = _get_google_client_id()
GOOGLE_CLIENT_SECRET = _get_google_client_secret()
GOOGLE_REDIRECT_URI = _get_google_redirect_uri()
JWT_SECRET = os.getenv("JWT_SECRET", "sentinelai_super_secret_jwt_key_2026_production_safe_256bit")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Google OAuth URLs
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# In-memory store fallback and state cache
_oauth_states: Dict[str, float] = {}  # state -> timestamp

# ============================================================================
# MODELS
# ============================================================================
class User(BaseModel):
    id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: str = "user"
    tenant_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: User

# ============================================================================
# JWT UTILITIES
# ============================================================================
def create_jwt_token(user: User) -> str:
    """Create a signed JWT token for the authenticated user."""
    now = datetime.utcnow()
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
        "tenant_id": user.tenant_id or f"tenant_{user.id}",
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt_token(token: str) -> Optional[Dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ============================================================================
# GOOGLE OAUTH
# ============================================================================
def generate_oauth_state() -> str:
    """Generate a CSRF-protecting random OAuth state token."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time()
    # Clean old states (> 10 mins)
    now = time.time()
    for s in list(_oauth_states.keys()):
        if now - _oauth_states[s] > 600:
            _oauth_states.pop(s, None)
    return state

def validate_oauth_state(state: Optional[str]) -> bool:
    """Validate and consume OAuth state token."""
    if not state:
        return True  # For backward-compatibility with direct flows
    created_at = _oauth_states.pop(state, None)
    if created_at and (time.time() - created_at <= 600):
        return True
    return False

def get_google_auth_url(state: Optional[str] = None) -> str:
    """Generate Google OAuth authorization URL."""
    state_token = state or generate_oauth_state()
    client_id = _get_google_client_id()
    redirect_uri = _get_google_redirect_uri()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
    }
    
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"

async def exchange_code_for_tokens(code: str) -> Dict:
    """Exchange authorization code for tokens."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": _get_google_client_id(),
                "client_secret": _get_google_client_secret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _get_google_redirect_uri(),
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to exchange code with Google: {response.text}"
            )
        
        return response.json()

async def get_google_user_info(access_token: str) -> Dict:
    """Get user profile from Google using access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to retrieve user info from Google"
            )
        
        return response.json()

# ============================================================================
# USER PERSISTENCE & DATA ISOLATION
# ============================================================================
users_store: Dict[str, User] = {}

async def get_or_create_user(google_user: Dict) -> User:
    """
    Get existing user or create a new user record dynamically.
    Persists to MongoDB when available, and caches in memory.
    """
    user_id = str(google_user.get("id") or google_user.get("sub", ""))
    email = google_user.get("email", "").strip().lower()
    name = google_user.get("name") or (email.split("@")[0] if email else "User")
    picture = google_user.get("picture")
    tenant_id = f"tenant_{user_id}"
    
    # 1. Check in-memory store
    if user_id in users_store:
        existing = users_store[user_id]
        existing.name = name
        existing.picture = picture
        # Update in MongoDB if available
        if DB_AVAILABLE:
            try:
                await db_upsert_user({
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "role": existing.role,
                    "tenant_id": existing.tenant_id or tenant_id,
                    "last_login_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                })
            except Exception as e:
                logger.error(f"[AUTH_DB] Error updating user: {e}")
        return existing
    
    # 2. Check MongoDB if available
    if DB_AVAILABLE:
        try:
            db_user = await db_get_user_by_id(user_id)
            if db_user:
                user = User(
                    id=db_user["id"],
                    email=db_user.get("email", email),
                    name=name,
                    picture=picture,
                    role=db_user.get("role", "user"),
                    tenant_id=db_user.get("tenant_id", tenant_id),
                )
                users_store[user_id] = user
                await db_upsert_user({
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "last_login_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                })
                return user
        except Exception as e:
            logger.error(f"[AUTH_DB] Error querying user: {e}")
            
    # 3. Create fresh user
    user = User(
        id=user_id,
        email=email,
        name=name,
        picture=picture,
        role="admin" if len(users_store) == 0 else "user",
        tenant_id=tenant_id,
    )
    users_store[user_id] = user
    
    # Save to MongoDB
    if DB_AVAILABLE:
        try:
            await db_upsert_user({
                "id": user_id,
                "email": email,
                "name": name,
                "picture": picture,
                "role": user.role,
                "tenant_id": tenant_id,
                "created_at": datetime.utcnow().isoformat(),
                "last_login_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            })
            logger.info(f"[AUTH_DB] New user persisted: {email} ({user_id})")
        except Exception as e:
            logger.error(f"[AUTH_DB] Error creating user in DB: {e}")

    return user

# ============================================================================
# FASTAPI AUTH DEPENDENCIES
# ============================================================================
security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[User]:
    """Get current authenticated user from JWT token (optional dependency)."""
    if not credentials:
        return None
    
    try:
        payload = decode_jwt_token(credentials.credentials)
        return User(
            id=payload["sub"],
            email=payload["email"],
            name=payload["name"],
            picture=payload.get("picture"),
            role=payload.get("role", "user"),
            tenant_id=payload.get("tenant_id", f"tenant_{payload['sub']}"),
        )
    except Exception:
        return None

async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """Require authentication - raises 401 if no valid token is present."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    payload = decode_jwt_token(credentials.credentials)
    return User(
        id=payload["sub"],
        email=payload["email"],
        name=payload["name"],
        picture=payload.get("picture"),
        role=payload.get("role", "user"),
        tenant_id=payload.get("tenant_id", f"tenant_{payload['sub']}"),
    )
