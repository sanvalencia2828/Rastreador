"""Schemas for visits and offline sync."""

from typing import Optional

from pydantic import BaseModel


class VisitCreate(BaseModel):
    cnpj: Optional[str] = None
    lat: float
    lon: float
    logradouro: str
    bairro: Optional[str] = None
    route_id: Optional[str] = None
    notes: Optional[str] = None
    visited_at: Optional[str] = None


class VisitSyncItem(BaseModel):
    cnpj: Optional[str] = None
    lat: float
    lon: float
    logradouro: str
    bairro: Optional[str] = None
    route_id: Optional[str] = None
    notes: Optional[str] = None
    visited_at: str
