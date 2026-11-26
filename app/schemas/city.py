"""Schemas for cities."""

from pydantic import BaseModel


# ── CITIES ENDPOINTS ──────────────────────────────────────

class City(BaseModel):
    id: int
    name: str
    state: str
    lat: float | None
    lon: float | None

class CityCreate(BaseModel):
    name: str
    state: str = "PR"
    lat: float
    lon: float

class CityStats(BaseModel):
    id: int
    name: str
    state: str
    lat: float | None
    lon: float | None
    total_businesses: int
