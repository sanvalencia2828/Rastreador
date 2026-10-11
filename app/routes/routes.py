from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

import requests
from fastapi import APIRouter, HTTPException

from app.optimizer import optimize_open_path
from app.routes.points import get_tracking_point
from app.schemas.route import (
    RouteCreateRequest,
    RouteOptimizeRequest,
    RouteReorderRequest,
    RouteResponse,
    RouteStopCreateRequest,
    RouteStopPatchRequest,
    RouteStopResponse,
)

router = APIRouter(prefix="/routes", tags=["routes"])

ROUTE_STORE: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_point_exists(point_id: int) -> dict[str, Any]:
    point = get_tracking_point(point_id)
    if point is None:
        raise HTTPException(status_code=404, detail=f"Point {point_id} not found")
    return point


def _read_route(route_id: str) -> dict[str, Any]:
    route = ROUTE_STORE.get(route_id)
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return route


def _normalize_route(route: dict[str, Any]) -> dict[str, Any]:
    stops = sorted(route["stops"], key=lambda stop: stop["seq"])
    for idx, stop in enumerate(stops, start=1):
        stop["seq"] = idx
    route["stops"] = stops
    return route


def validate_route_status(route: dict[str, Any]) -> None:
    if route["status"] in {"in_progress", "done"}:
        raise HTTPException(
            status_code=409,
            detail=f"Route is in status '{route['status']}' and cannot be modified.",
        )


def _stop_index(route: dict[str, Any], stop_id: int | str) -> int:
    for index, stop in enumerate(route["stops"]):
        if stop["id"] == stop_id:
            return index
    raise HTTPException(status_code=404, detail="Stop not found")


def _is_entry_stop(route: dict[str, Any], stop: dict[str, Any]) -> bool:
    return stop["point_id"] == route["entry_point_id"]


def _is_exit_stop(route: dict[str, Any], stop: dict[str, Any]) -> bool:
    return stop["point_id"] == route["exit_point_id"]


def _reindex_stops(route: dict[str, Any]) -> None:
    ordered = sorted(route["stops"], key=lambda stop: stop["seq"])
    for new_seq, stop in enumerate(ordered, start=1):
        stop["seq"] = new_seq
    route["stops"] = ordered


def _serialize_stop(route: dict[str, Any], stop: dict[str, Any]) -> RouteStopResponse:
    point = _ensure_point_exists(stop["point_id"])
    return RouteStopResponse(
        id=stop["id"],
        point_id=stop["point_id"],
        seq=stop["seq"],
        locked=bool(stop.get("locked", False)),
        eta_min=stop.get("eta_min"),
        distance_km=stop.get("distance_km"),
        label=point.get("label"),
        lat=point.get("lat"),
        lon=point.get("lon"),
    )


def _build_route_response(route: dict[str, Any]) -> RouteResponse:
    ordered = sorted(route["stops"], key=lambda stop: stop["seq"])
    return RouteResponse(
        id=route["id"],
        name=route["name"],
        status=route["status"],
        entry_point_id=route["entry_point_id"],
        exit_point_id=route["exit_point_id"],
        total_km=route.get("total_km"),
        total_min=route.get("total_min"),
        optimized_at=route.get("optimized_at"),
        created_at=route["created_at"],
        stops=[_serialize_stop(route, stop) for stop in ordered],
    )


def reorder_route(route: dict[str, Any], ordered_stop_ids: Sequence[int | str]) -> dict[str, Any]:
    stop_ids = [stop["id"] for stop in route["stops"]]
    if len(ordered_stop_ids) != len(stop_ids):
        raise HTTPException(status_code=422, detail="ordered_stop_ids must include every stop in the route")

    if set(ordered_stop_ids) != set(stop_ids):
        raise HTTPException(status_code=422, detail="ordered_stop_ids must match the current stops exactly")

    entry_stop = next(stop for stop in route["stops"] if _is_entry_stop(route, stop))
    exit_stop = next(stop for stop in route["stops"] if _is_exit_stop(route, stop))
    if ordered_stop_ids[0] != entry_stop["id"] or ordered_stop_ids[-1] != exit_stop["id"]:
        raise HTTPException(
            status_code=422,
            detail="Entry and exit stops must remain at the beginning and end of the route.",
        )

    ordered_stops = [
        next(stop for stop in route["stops"] if stop["id"] == stop_id)
        for stop_id in ordered_stop_ids
    ]
    route["stops"] = ordered_stops
    route["status"] = "draft"
    route["total_km"] = None
    route["total_min"] = None
    route["optimized_at"] = None
    _reindex_stops(route)
    return route


def _route_matrix(route: dict[str, Any]) -> list[list[float]]:
    ordered = sorted(route["stops"], key=lambda stop: stop["seq"])
    coords: list[tuple[float, float]] = []
    for stop in ordered:
        point = _ensure_point_exists(stop["point_id"])
        coords.append((float(point["lon"]), float(point["lat"])))
    if len(coords) <= 1:
        return [[0.0]]

    osrm_url = os.getenv("OSRM_URL", "http://osrm:5000")
    joined = ";".join(f"{lon},{lat}" for lon, lat in coords)
    url = f"{osrm_url}/table/v1/driving/{joined}?annotations=duration,distance"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        matrix = data.get("durations")
        if isinstance(matrix, list) and matrix and len(matrix) == len(ordered):
            return [[float(value) for value in row] for row in matrix]
    except Exception:  # pragma: no cover - fallback for local/offline tests
        pass

    fallback_matrix: list[list[float]] = []
    for i, (lon_a, lat_a) in enumerate(coords):
        row: list[float] = []
        for _, (lon_b, lat_b) in enumerate(coords):
            delta_lon = lon_a - lon_b
            delta_lat = lat_a - lat_b
            row.append(float(max(1.0, math.hypot(delta_lon, delta_lat) * 100.0)))
        fallback_matrix.append(row)
    return fallback_matrix


@router.post("", response_model=RouteResponse)
def create_route(request: RouteCreateRequest) -> RouteResponse:
    if request.entry_point_id == request.exit_point_id:
        raise HTTPException(status_code=422, detail="entry_point_id and exit_point_id must differ")

    _ensure_point_exists(request.entry_point_id)
    _ensure_point_exists(request.exit_point_id)

    route_id = str(uuid4())
    route = {
        "id": route_id,
        "name": request.name,
        "status": "draft",
        "entry_point_id": request.entry_point_id,
        "exit_point_id": request.exit_point_id,
        "total_km": None,
        "total_min": None,
        "optimized_at": None,
        "created_at": _utc_now(),
        "stops": [
            {
                "id": f"stop-{uuid4()}",
                "point_id": request.entry_point_id,
                "seq": 1,
                "locked": True,
                "eta_min": None,
                "distance_km": None,
            },
            {
                "id": f"stop-{uuid4()}",
                "point_id": request.exit_point_id,
                "seq": 2,
                "locked": True,
                "eta_min": None,
                "distance_km": None,
            },
        ],
    }
    ROUTE_STORE[route_id] = route
    return _build_route_response(route)


@router.get("/{route_id}", response_model=RouteResponse)
def get_route(route_id: str) -> RouteResponse:
    route = _read_route(route_id)
    return _build_route_response(route)


@router.post("/{route_id}/stops", response_model=RouteResponse)
def add_stop(route_id: str, request: RouteStopCreateRequest) -> RouteResponse:
    route = _read_route(route_id)
    validate_route_status(route)
    _ensure_point_exists(request.point_id)

    if request.point_id in {route["entry_point_id"], route["exit_point_id"]}:
        raise HTTPException(status_code=409, detail="Entry and exit stops cannot be added as intermediate stops")

    if any(stop["point_id"] == request.point_id for stop in route["stops"]):
        raise HTTPException(status_code=409, detail="Point already exists in this route")

    exit_stop = next(stop for stop in route["stops"] if _is_exit_stop(route, stop))
    exit_seq = exit_stop["seq"]
    target_seq = request.after_seq if request.after_seq is not None else exit_seq - 1
    if target_seq < 1 or target_seq >= exit_seq:
        raise HTTPException(status_code=422, detail="after_seq must be between 1 and exit_point_seq-1")

    new_stop = {
        "id": f"stop-{uuid4()}",
        "point_id": request.point_id,
        "seq": target_seq + 1,
        "locked": bool(request.locked),
        "eta_min": None,
        "distance_km": None,
    }
    route["stops"].append(new_stop)
    _reindex_stops(route)
    return _build_route_response(route)


@router.patch("/{route_id}/stops/{stop_id}", response_model=RouteResponse)
def patch_stop(route_id: str, stop_id: str | int, request: RouteStopPatchRequest) -> RouteResponse:
    route = _read_route(route_id)
    validate_route_status(route)
    stop = next(stop for stop in route["stops"] if stop["id"] == stop_id)

    if _is_entry_stop(route, stop) or _is_exit_stop(route, stop):
        raise HTTPException(status_code=422, detail="Entry and exit stops cannot be moved or unlocked.")

    if request.seq is not None:
        if request.seq < 2 or request.seq >= len(route["stops"]):
            raise HTTPException(status_code=422, detail="seq must be between 2 and N-1 for intermediate stops")
        stop["seq"] = request.seq
        _reindex_stops(route)

    if request.locked is not None:
        stop["locked"] = bool(request.locked)

    route["total_km"] = None
    route["total_min"] = None
    route["optimized_at"] = None
    route["status"] = "draft"
    return _build_route_response(route)


@router.delete("/{route_id}/stops/{stop_id}", response_model=dict[str, str])
def delete_stop(route_id: str, stop_id: str | int) -> dict[str, str]:
    route = _read_route(route_id)
    validate_route_status(route)
    stop = next((item for item in route["stops"] if item["id"] == stop_id), None)
    if stop is None:
        raise HTTPException(status_code=404, detail="Stop not found")
    if _is_entry_stop(route, stop) or _is_exit_stop(route, stop):
        raise HTTPException(status_code=422, detail="Entry and exit stops cannot be removed")
    route["stops"] = [item for item in route["stops"] if item["id"] != stop_id]
    _reindex_stops(route)
    route["status"] = "draft"
    route["total_km"] = None
    route["total_min"] = None
    route["optimized_at"] = None
    return {"status": "deleted", "route_id": route_id}


@router.post("/{route_id}/optimize", response_model=dict[str, Any])
def optimize_route(route_id: str, request: RouteOptimizeRequest) -> dict[str, Any]:
    route = _read_route(route_id)
    validate_route_status(route)

    ordered_stops = sorted(route["stops"], key=lambda stop: stop["seq"])
    if len(ordered_stops) <= 2:
        route["status"] = "optimized"
        route["optimized_at"] = _utc_now()
        route["total_km"] = 0.0
        route["total_min"] = 0.0
        return {
            "route_id": route_id,
            "total_km": 0.0,
            "total_min": 0.0,
            "stops": [_serialize_stop(route, stop) for stop in ordered_stops],
        }

    anchor_indices: list[int] = []
    movable_indices: list[int] = []
    for idx, stop in enumerate(ordered_stops):
        if stop["point_id"] == route["entry_point_id"] or stop["point_id"] == route["exit_point_id"] or stop.get("locked"):
            anchor_indices.append(idx)
        else:
            movable_indices.append(idx)

    matrix = _route_matrix(route)
    optimized_indices = optimize_open_path(matrix, anchor_indices, movable_indices)
    new_order = [ordered_stops[position] for position in optimized_indices]
    route["stops"] = new_order
    _reindex_stops(route)

    total_km = 0.0
    total_min = 0.0
    for idx in range(len(route["stops"]) - 1):
        current = route["stops"][idx]
        nxt = route["stops"][idx + 1]
        current_point = _ensure_point_exists(current["point_id"])
        next_point = _ensure_point_exists(nxt["point_id"])
        delta_lon = float(current_point["lon"]) - float(next_point["lon"])
        delta_lat = float(current_point["lat"]) - float(next_point["lat"])
        segment_km = max(0.1, math.hypot(delta_lon, delta_lat) * 700.0)
        total_km += segment_km
        total_min += max(1.0, segment_km / 28.0)
        current["distance_km"] = round(segment_km, 2)
        current["eta_min"] = round(max(1.0, segment_km / 28.0), 2)

    route["total_km"] = round(total_km, 2)
    route["total_min"] = round(total_min, 2)
    route["optimized_at"] = _utc_now()
    route["status"] = "optimized"

    serialized = [_serialize_stop(route, stop) for stop in sorted(route["stops"], key=lambda stop: stop["seq"])]
    return {
        "route_id": route_id,
        "total_km": route["total_km"],
        "total_min": route["total_min"],
        "stops": serialized,
    }


@router.post("/{route_id}/reorder", response_model=RouteResponse)
def reorder_route_endpoint(route_id: str, request: RouteReorderRequest) -> RouteResponse:
    route = _read_route(route_id)
    validate_route_status(route)
    reorder_route(route, request.ordered_stop_ids)
    return _build_route_response(route)


@router.post("/{route_id}/commit", response_model=RouteResponse)
def commit_route(route_id: str) -> RouteResponse:
    route = _read_route(route_id)
    validate_route_status(route)
    route["status"] = "optimized"
    route["optimized_at"] = _utc_now()
    return _build_route_response(route)


@router.get("", response_model=list[RouteResponse])
def list_routes() -> list[RouteResponse]:
    return [_build_route_response(route) for route in ROUTE_STORE.values()]
