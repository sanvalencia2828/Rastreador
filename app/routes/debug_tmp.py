"""TEMPORARY one-shot diagnostic endpoint. Remove after use."""

import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text

from app.core.database import db_engine

router = APIRouter()


@router.get("/api/_debug/users-summary", include_in_schema=False)
def users_summary(x_debug_key: str | None = Header(default=None)):
    key = os.getenv("DEBUG_KEY")
    # 404 (not 401) so the endpoint's existence isn't hinted at.
    if not key or not x_debug_key or not hmac.compare_digest(x_debug_key, key):
        raise HTTPException(status_code=404)
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    with db_engine.connect() as conn:
        users = conn.execute(text("SELECT id, username FROM users ORDER BY id")).fetchall()
        counts = conn.execute(
            text("SELECT user_id, count(*) AS count FROM clientes GROUP BY 1 ORDER BY 1")
        ).fetchall()
    return {
        "users": [{"id": str(r.id), "username": r.username} for r in users],
        "clientes_por_user": [{"user_id": str(r.user_id), "count": r.count} for r in counts],
    }
