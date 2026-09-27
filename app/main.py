"""Alternate entrypoint: uvicorn app.main:app --host 0.0.0.0 --port $PORT"""

from api import app

__all__ = ["app"]
