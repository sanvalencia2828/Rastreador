"""Test double. Not used in production and not a ROUTE_STORE fallback."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.tarjeta import normalize_route_status, normalize_tarjeta


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class MemoryRouteRepository:
    def __init__(self) -> None:
        self.routes: dict[str, dict] = {}

    def list_routes(self, user_id: str, city_id=None, on_date=None, status=None) -> list[dict]:
        rows = []
        for route in self.routes.values():
            if route["user_id"] != user_id:
                continue
            if city_id is not None and route["city_id"] != city_id:
                continue
            if on_date is not None and route["date"] != on_date.isoformat():
                continue
            if status is not None and route["status"] != normalize_route_status(status):
                continue
            rows.append(deepcopy(route))
        rows.sort(key=lambda item: (item["date"], item["name"]), reverse=True)
        return rows

    def get_route(self, user_id: str, route_id: str) -> dict:
        route = self.routes.get(route_id)
        if not route or route["user_id"] != user_id:
            raise NotFoundError("Route not found")
        return deepcopy(route)

    def create_route(self, user_id: str, payload: dict) -> dict:
        now = _now()
        route_id = str(uuid4())
        stops = []
        for index, stop in enumerate(payload.get("stops") or [], start=1):
            stops.append(_new_stop(route_id, index, stop, payload["visit_date"]))
        route = {
            "id": route_id,
            "user_id": user_id,
            "city_id": payload["city_id"],
            "name": payload["name"],
            "status": normalize_route_status(payload.get("status") or "draft"),
            "vehicle_id": payload.get("vehicle_id"),
            "date": payload["date"].isoformat(),
            "meta": payload.get("meta") or {},
            "created_at": now,
            "updated_at": now,
            "stops": stops,
        }
        self.routes[route_id] = route
        return deepcopy(route)

    def update_route(self, user_id: str, route_id: str, payload: dict) -> dict:
        route = self._owned(user_id, route_id)
        if "name" in payload and payload["name"]:
            route["name"] = payload["name"]
        if "status" in payload and payload["status"] is not None:
            route["status"] = normalize_route_status(payload["status"])
            locked = route["status"] != "draft"
            for stop in route["stops"]:
                stop["locked"] = locked
        if "date" in payload and payload["date"] is not None:
            route["date"] = payload["date"].isoformat()
        if "vehicle_id" in payload:
            route["vehicle_id"] = payload["vehicle_id"]
        if "meta" in payload and payload["meta"] is not None:
            route["meta"] = payload["meta"]
        route["updated_at"] = _now()
        return deepcopy(route)

    def delete_route(self, user_id: str, route_id: str) -> None:
        self._owned(user_id, route_id)
        del self.routes[route_id]

    def add_stops(self, user_id: str, route_id: str, stops: list[dict], visit_date: str) -> dict:
        route = self._owned(user_id, route_id)
        if route["status"] != "draft":
            raise ConflictError("Route is not editable")
        next_seq = max((stop["seq"] for stop in route["stops"]), default=0) + 1
        for offset, stop in enumerate(stops):
            route["stops"].append(_new_stop(route_id, next_seq + offset, stop, visit_date))
        route["updated_at"] = _now()
        return deepcopy(route)

    def update_stop(self, user_id: str, route_id: str, stop_id: str, payload: dict) -> dict:
        route = self._owned(user_id, route_id)
        stop = _find_stop(route, stop_id)
        if route["status"] == "committed" and any(
            key in payload for key in ("address", "lat", "lng", "seq", "maps_url")
        ):
            raise ConflictError("Committed route stops cannot be edited")
        for key in ("address", "lat", "lng", "maps_url", "locked", "stop_ref", "order_id"):
            if key in payload:
                stop[key] = payload[key]
        if payload.get("visit_date") is not None:
            stop["visit_date"] = payload["visit_date"].isoformat()
        route["updated_at"] = _now()
        return deepcopy(stop)

    def set_tarjeta(self, user_id: str, route_id: str, stop_id: str, payload: dict) -> dict:
        route = self._owned(user_id, route_id)
        stop = _find_stop(route, stop_id)
        stop["tarjeta_status"] = normalize_tarjeta(payload["tarjeta_status"])
        stop["tarjeta_at"] = _now()
        stop["tarjeta_by"] = payload.get("tarjeta_by")
        if payload.get("visit_date") is not None:
            stop["visit_date"] = payload["visit_date"].isoformat()
        route["updated_at"] = _now()
        return deepcopy(stop)

    def delete_stop(self, user_id: str, route_id: str, stop_id: str) -> None:
        route = self._owned(user_id, route_id)
        if route["status"] != "draft":
            raise ConflictError("Route is not editable")
        stop = _find_stop(route, stop_id)
        if stop["locked"]:
            raise ConflictError("Stop is locked")
        route["stops"] = [item for item in route["stops"] if item["id"] != stop_id]
        route["updated_at"] = _now()

    def find_draft(self, user_id: str, city_id: int, on_date: str) -> dict | None:
        for route in self.routes.values():
            if (
                route["user_id"] == user_id
                and route["city_id"] == city_id
                and route["date"] == on_date
                and route["status"] == "draft"
            ):
                return deepcopy(route)
        return None

    def _owned(self, user_id: str, route_id: str) -> dict:
        route = self.routes.get(route_id)
        if not route or route["user_id"] != user_id:
            raise NotFoundError("Route not found")
        return route


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_stop(route_id: str, seq: int, payload: dict, visit_date: str) -> dict:
    visit = payload.get("visit_date") or visit_date
    if hasattr(visit, "isoformat"):
        visit = visit.isoformat()
    return {
        "id": str(uuid4()),
        "route_id": route_id,
        "seq": seq,
        "locked": bool(payload.get("locked") or False),
        "order_id": payload.get("order_id"),
        "stop_ref": payload.get("stop_ref"),
        "lat": payload.get("lat"),
        "lng": payload.get("lng"),
        "address": payload.get("address"),
        "maps_url": payload.get("maps_url"),
        "source": payload.get("source") or "google_maps",
        "visit_date": visit,
        "tarjeta_status": normalize_tarjeta(payload.get("tarjeta_status") or "TT"),
        "tarjeta_at": None,
        "tarjeta_by": None,
        "eta_s": payload.get("eta_s"),
        "distance_m": payload.get("distance_m"),
        "meta": payload.get("meta") or {},
    }


def _find_stop(route: dict, stop_id: str) -> dict:
    for stop in route["stops"]:
        if stop["id"] == stop_id:
            return stop
    raise NotFoundError("Stop not found")
