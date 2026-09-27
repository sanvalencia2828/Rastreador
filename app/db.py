"""Shared SQLAlchemy engine. Set from api.py after DATABASE_URL is resolved."""

from __future__ import annotations

from typing import Any, Optional

_engine: Any = None


def set_engine(engine: Any) -> None:
    global _engine
    _engine = engine


def get_engine() -> Optional[Any]:
    return _engine
