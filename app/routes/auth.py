"""Registration and login endpoints."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import db_engine
from app.core.ratelimit import AttemptLimiter
from app.core.security import create_jwt_token, hash_password, needs_rehash, verify_password
from app.schemas.auth import UserLogin, UserRegister

router = APIRouter()

# 5 failed logins per username per 15 min; 10 registrations per client per hour.
login_limiter = AttemptLimiter(max_attempts=5, window_s=900)
register_limiter = AttemptLimiter(max_attempts=10, window_s=3600)


def _client_key(request: Request) -> str:
    # shortcut: X-Forwarded-For is client-controlled unless the proxy overwrites it; fine for a demo
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


# ------------------------------------------------------------------------------
# AUTH ENDPOINTS
# ------------------------------------------------------------------------------
@router.post("/auth/register")
def register_user(user: UserRegister, request: Request):
    if not db_engine:
        raise HTTPException(status_code=503, detail="Database connection unavailable")
    key = _client_key(request)
    register_limiter.check(key)
    register_limiter.hit(key)
    try:
        pw_hash = hash_password(user.password)
        with db_engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO users (username, password_hash) VALUES (:username, :pw_hash) RETURNING id"
                ),
                {"username": user.username, "pw_hash": pw_hash},
            ).fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="User creation failed")
        user_id = row[0]
        token = create_jwt_token({"user_id": str(user_id), "username": user.username})
        return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Username already registered")
    except Exception as e:
        print(f"register failed: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/auth/login")
def login_user(user: UserLogin):
    if not db_engine:
        raise HTTPException(status_code=503, detail="Database connection unavailable")
    key = user.username.strip().lower()
    login_limiter.check(key)
    try:
        with db_engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, password_hash FROM users WHERE username = :username"),
                {"username": user.username},
            ).fetchone()
            if not row or not verify_password(user.password, row[1]):
                login_limiter.hit(key)
                raise HTTPException(status_code=400, detail="Invalid username or password")
            user_id, stored_hash = row
            if needs_rehash(stored_hash):
                conn.execute(
                    text("UPDATE users SET password_hash = :pw_hash WHERE id = :id"),
                    {"pw_hash": hash_password(user.password), "id": user_id},
                )
        login_limiter.reset(key)
        token = create_jwt_token({"user_id": str(user_id), "username": user.username})
        return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        print(f"login failed: {e}")
        raise HTTPException(status_code=500, detail="Login failed")
