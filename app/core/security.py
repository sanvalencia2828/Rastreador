"""Zero-dependency JWT helpers and auth dependencies."""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core import config  # noqa: F401  (loads .env before env reads below)


security = HTTPBearer(auto_error=False)


def is_dev_env() -> bool:
    """Dev shortcuts are opt-in: APP_ENV must be exactly 'development'."""
    return os.getenv("APP_ENV", "").strip().lower() == "development"


def _load_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if secret and secret != "change-me-in-production":
        return secret
    if is_dev_env():
        return "dev-only-insecure-secret"
    raise RuntimeError("JWT_SECRET_KEY must be set to a real secret (or APP_ENV=development)")


JWT_SECRET_KEY = _load_jwt_secret()
SECRET_KEY = JWT_SECRET_KEY


# ------------------------------------------------------------------------------
# 0-DEPENDENCY JWT & CRYPTO UTILITIES
# ------------------------------------------------------------------------------
def base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("utf-8")


def base64url_decode(payload: str) -> bytes:
    padding = "=" * (4 - (len(payload) % 4))
    return base64.urlsafe_b64decode(payload + padding)


def create_jwt_token(data: dict, expires_in: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = data.copy()
    payload["exp"] = int(time.time()) + expires_in
    header_json = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    unsigned_token = (
        base64url_encode(header_json) + "." + base64url_encode(payload_json)
    )
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), unsigned_token.encode("utf-8"), hashlib.sha256
    ).digest()
    return unsigned_token + "." + base64url_encode(signature)


def decode_jwt_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        header_segment, payload_segment, signature_segment = parts
        unsigned_token = header_segment + "." + payload_segment
        expected_signature = hmac.new(
            SECRET_KEY.encode("utf-8"), unsigned_token.encode("utf-8"), hashlib.sha256
        ).digest()
        actual_signature = base64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return {}
        payload = json.loads(base64url_decode(payload_segment).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return {}
        return payload
    except Exception:
        return {}


_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    """scrypt with a random salt, stored as 'scrypt$<salt hex>$<hash hex>'."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("scrypt$"):
        _, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), hash_hex)
    # legacy unsalted SHA-256; the caller re-hashes it on a successful login
    return hmac.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), stored)


def needs_rehash(stored: str) -> bool:
    return not stored.startswith("scrypt$")


# ------------------------------------------------------------------------------
# DEPENDENCY FOR AUTHENTICATION
# ------------------------------------------------------------------------------
def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not credentials:
        if is_dev_env():
            return os.getenv("DEV_USER_ID", "00000000-0000-0000-0000-000000000001")
        raise HTTPException(status_code=401, detail="Authentication token missing")
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    if not credentials:
        return None
    token = credentials.credentials
    payload = decode_jwt_token(token)
    return payload.get("user_id") if payload else None
