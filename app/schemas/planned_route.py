"""Schemas for DB-backed planned and daily routes."""

from datetime import date, datetime
from typing import List, Dict, Any, Literal, Optional

from pydantic import BaseModel, Field


class RouteStopCreate(BaseModel):
    address: str
    lat: float
    lon: float
    cep: Optional[str] = None
    display_name: Optional[str] = None
    cliente_id: Optional[str] = None  # cliente del usuario (clientes.id); se valida que sea suyo


class RouteStopResponse(BaseModel):
    id: str
    stop_order: int
    address: str
    lat: float
    lon: float
    cep: Optional[str]
    display_name: Optional[str]


class RouteCreate(BaseModel):
    name: str
    city_id: int
    stops: List[RouteStopCreate] = []


class RouteResponse(BaseModel):
    id: str
    name: str
    city_id: int
    created_at: str
    stops: List[RouteStopResponse] = []


class RouteStop(BaseModel):
    id: str
    route_id: str
    business_id: Optional[int]
    order: int
    visited: bool
    visited_at: Optional[str]
    skipped: bool
    skip_reason: Optional[str]
    notes: Optional[str]
    business: Optional[Dict[str, Any]] = None


class Route(BaseModel):
    id: str
    user_id: Optional[str]
    name: str
    city_id: Optional[int]
    start_lat: Optional[float]
    start_lng: Optional[float]
    status: str
    planned_at: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    completed_at: Optional[str]
    completed_date: Optional[str]
    total_stops_planned: int
    total_stops_done: int
    total_distance_km: float
    total_duration_min: float
    notes: Optional[str]
    stops: List[RouteStop] = []


class RouteCoordinate(BaseModel):
    lat: float
    lng: float


class PlannedRouteCreate(BaseModel):
    name: str
    city_id: Optional[int] = None
    business_ids: List[int]
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    start: Optional[RouteCoordinate] = None
    notes: Optional[str] = None


class RouteStatusUpdate(BaseModel):
    status: Literal["active", "cancelled"]


class RouteCompletionStop(BaseModel):
    business_id: int
    status: Literal["visited", "skipped", "closed"]
    notes: Optional[str] = None
    skip_reason: Optional[str] = None


class RouteCompleteRequest(BaseModel):
    completed_date: date
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    stops: List[RouteCompletionStop]


class DailyRouteCreate(BaseModel):
    name: str
    day_of_week: Optional[str] = None
    streets: List[str] = []


class DailyRouteUpdate(BaseModel):
    name: Optional[str] = None
    day_of_week: Optional[str] = None
    streets: Optional[List[str]] = None


# ── INTELLIGENT ROUTE GENERATION MODELS ────────────────────
class RouteGenerateRequest(BaseModel):
    city_id: int
    max_lojas: int = 80
    min_days_without_visit: int = 30
    day: Optional[int] = Field(None, ge=0, le=4)  # solo Maringa: 0=lunes .. 4=viernes


class GeneratedStop(BaseModel):
    cnpj: str
    nome_fantasia: str
    cnae_label: str
    bairro: str
    logradouro: str
    lat: float
    lon: float
    days_since_visit: Optional[int] = None  # None: clientes aun no tienen visitas enlazadas
    priority: Optional[int] = None
    cliente_id: Optional[str] = None


class ClienteListed(BaseModel):
    """Cliente del propio usuario que no entra en la ruta (fuera de Maringa o sin ubicar)."""
    nombre: str
    direccion: str
    municipio: str


class RouteGenerateResponse(BaseModel):
    city: str
    total_candidates: int
    selected: int
    stops: list[GeneratedStop]
    distance_km: Optional[float] = None
    distance_kind: Optional[str] = None  # "linea_recta": Haversine, no por calle
    maps_links: list[str] = []
    fuera_de_maringa: list[ClienteListed] = []
    pendientes: list[ClienteListed] = []
    day: Optional[int] = None
    day_label: Optional[str] = None
    day_counts: list[int] = []  # paradas por dia (lunes..viernes)
    sin_asignar: int = 0  # no caben en ningun dia con el tope


class RoutePoint(BaseModel):
    id: int
    lat: float
    lng: float


class RouteOptimizeRequest(BaseModel):
    start: RouteCoordinate
    points: List[RoutePoint]
