"""Registration and login endpoints."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import create_jwt_token, hash_password
from app.schemas.auth import UserLogin, UserRegister

router = APIRouter()


# ------------------------------------------------------------------------------
# AUTH ENDPOINTS
# ------------------------------------------------------------------------------
@router.post("/auth/register")
def register_user(user: UserRegister):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        pw_hash = hash_password(user.password)
        with db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO users (username, password_hash) VALUES (:username, :pw_hash) RETURNING id"
                ),
                {"username": user.username, "pw_hash": pw_hash},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="User creation failed")
            user_id = row[0]
            conn.commit()
            token = create_jwt_token(
                {"user_id": str(user_id), "username": user.username}
            )
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Username already registered")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.post("/auth/login")
def login_user(user: UserLogin):
    if not db_engine:
        return {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "username": user.username,
            "token": "dummy_dev_token",
        }
    try:
        pw_hash = hash_password(user.password)
        with db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, password_hash FROM users WHERE username = :username"),
                {"username": user.username},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=400, detail="Invalid username or password"
                )
            user_id, db_pw_hash = row
            if db_pw_hash != pw_hash:
                raise HTTPException(
                    status_code=400, detail="Invalid username or password"
                )

            token = create_jwt_token(
                {"user_id": str(user_id), "username": user.username}
            )
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
