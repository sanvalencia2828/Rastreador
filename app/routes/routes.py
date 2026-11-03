from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

import requests
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user_id
from app.optimizer import optimize_open_path
from app.routes.points import get_tracking_point
from app.services.geo import haversine_km
from app.schemas.route import (
    RouteCreateRequest,
    RouteOptimizeRequest,
    RouteReorderRequest,
    RouteResponse,
    RouteStopCreateRequest,
    RouteStopPatchRequest,
    RouteStopResponse,
)

router = APIRouter(prefix="/routes", tags=["routes"], dependencies=[Depends(get_current_user_id)])

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


# Velocidad media urbana usada cuando OSRM no está disponible (km/h)
FALLBACK_SPEED_KMH = float(os.getenv("ROUTE_FALLBACK_SPEED_KMH", "28"))


def _route_coords(route: dict[str, Any]) -> list[tuple[float, float]]:
    """(lat, lon) de cada parada en el orden actual de `seq`."""
    coords: list[tuple[float, float]] = []
    for stop in sorted(route["stops"], key=lambda stop: stop["seq"]):
        point = _ensure_point_exists(stop["point_id"])
        coords.append((float(point["lat"]), float(point["lon"])))
    return coords


def _route_matrices(route: dict[str, Any]) -> tuple[list[list[float | None]], list[list[float | None]], str]:
    """Matrices de duración (s) y distancia (km) entre paradas, y su fuente.

    Usa OSRM /table cuando responde; si no, distancia Haversine y una velocidad media
    (FALLBACK_SPEED_KMH) para estimar la duración. OSRM devuelve null entre puntos
    sin ruta: se conserva como None y el optimizador lo trata como costo infinito.
    """
    coords = _route_coords(route)
    if len(coords) <= 1:
        return [[0.0]], [[0.0]], "none"

    osrm_url = os.getenv("OSRM_URL", "http://osrm:5000")
    joined = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"{osrm_url}/table/v1/driving/{joined}?annotations=duration,distance"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        durations = data.get("durations")
        distances = data.get("distances")
        if isinstance(durations, list) and len(durations) == len(coords):
            dur = [[None if v is None else float(v) for v in row] for row in durations]
            if isinstance(distances, list) and len(distances) == len(coords):
                dist = [[None if v is None else float(v) / 1000.0 for v in row] for row in distances]
            else:
                dist = _haversine_matrix(coords)
            return dur, dist, "osrm"
    except Exception:  # pragma: no cover - fallback for local/offline tests
        pass

    dist = _haversine_matrix(coords)
    dur = [[d / FALLBACK_SPEED_KMH * 3600.0 for d in row] for row in dist]
    return dur, dist, "haversine"


def _haversine_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    return [[haversine_km(lat_a, lon_a, lat_b, lon_b) for lat_b, lon_b in coords] for lat_a, lon_a in coords]


def _route_matrix(route: dict[str, Any]) -> list[list[float | None]]:
    """Matriz de duraciones en segundos (compatibilidad con el código existente)."""
    return _route_matrices(route)[0]


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
    # correr una posición las paradas que van después; si no, el nuevo seq empata con
    # la salida y la parada quedaba después del punto de salida
    for stop in route["stops"]:
        if stop["seq"] > target_seq:
            stop["seq"] += 1
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
        others = [item for item in sorted(route["stops"], key=lambda item: item["seq"]) if item is not stop]
        others.insert(request.seq - 1, stop)
        for new_seq, item in enumerate(others, start=1):
            item["seq"] = new_seq
        route["stops"] = others

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

    durations, distances, source = _route_matrices(route)
    optimized_indices = optimize_open_path(durations, anchor_indices, movable_indices)
    new_order = [ordered_stops[position] for position in optimized_indices]
    # Asignar seq según el nuevo orden ANTES de normalizar: _reindex_stops ordena por
    # el seq existente, así que sin esto la ruta volvía a su orden original.
    for seq, stop in enumerate(new_order, start=1):
        stop["seq"] = seq
    route["stops"] = new_order
    _reindex_stops(route)

    # métricas por tramo: OSRM si respondió; si no, Haversine a FALLBACK_SPEED_KMH
    total_km = 0.0
    total_min = 0.0
    for idx in range(len(optimized_indices) - 1):
        a, b = optimized_indices[idx], optimized_indices[idx + 1]
        segment_km = distances[a][b]
        segment_s = durations[a][b]
        if segment_km is None or segment_s is None:  # OSRM sin ruta entre esos puntos
            p1 = _ensure_point_exists(new_order[idx]["point_id"])
            p2 = _ensure_point_exists(new_order[idx + 1]["point_id"])
            segment_km = haversine_km(float(p1["lat"]), float(p1["lon"]), float(p2["lat"]), float(p2["lon"]))
            segment_s = segment_km / FALLBACK_SPEED_KMH * 3600.0
        segment_min = segment_s / 60.0
        total_km += segment_km
        total_min += segment_min
        new_order[idx]["distance_km"] = round(segment_km, 2)
        new_order[idx]["eta_min"] = round(segment_min, 2)
    new_order[-1]["distance_km"] = None
    new_order[-1]["eta_min"] = None

    route["total_km"] = round(total_km, 2)
    route["total_min"] = round(total_min, 2)
    route["optimized_at"] = _utc_now()
    route["status"] = "optimized"

    serialized = [_serialize_stop(route, stop) for stop in sorted(route["stops"], key=lambda stop: stop["seq"])]
    return {
        "route_id": route_id,
        "total_km": route["total_km"],
        "total_min": route["total_min"],
        "distance_source": source,
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
