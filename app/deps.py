"""Repository selection. Production never falls back to an in-memory route store."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from app.db import get_engine

_override = None


def set_repository(repo) -> None:
    global _override
    _override = repo


def get_repository():
    if _override is not None:
        return _override
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    from app.routes_repo import PostgresRouteRepository

    return PostgresRouteRepository(engine)


def current_override() -> Optional[object]:
    return _override
