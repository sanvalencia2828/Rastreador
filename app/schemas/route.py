from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RouteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    entry_point_id: int
    exit_point_id: int


class RouteStopCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: int
    after_seq: int | None = None
    locked: bool = False


class RouteStopPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int | None = None
    locked: bool | None = None


class RouteOptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: Literal["osrm", "ortools"] = "osrm"
    respect_locked: bool = True
    revisit: bool = False


class RouteReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordered_stop_ids: list[int]


class RouteStopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | str
    point_id: int
    seq: int
    locked: bool
    eta_min: float | None = None
    distance_km: float | None = None
    label: str | None = None
    lat: float | None = None
    lon: float | None = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    entry_point_id: int
    exit_point_id: int
    total_km: float | None = None
    total_min: float | None = None
    optimized_at: str | None = None
    created_at: str
    stops: list[RouteStopResponse]


class RouteOptimizationResult(BaseModel):
    route_id: str
    total_km: float | None = None
    total_min: float | None = None
    stops: list[RouteStopResponse]
