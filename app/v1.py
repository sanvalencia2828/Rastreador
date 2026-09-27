"""API v1 planner routes. Extends the API; it does not replace /api/*."""

from __future__ import annotations

import os
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_repository
from app.geo import fill_leg_distance
from app.maps_import import parse_maps_text, today_in_app_tz
from app.memory_repo import ConflictError, NotFoundError
from app.osrm import fill_osrm_legs
from app.tarjeta import normalize_route_status, tarjeta_legend

router = APIRouter(prefix="/api/v1", tags=["v1"])


class StopIn(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    maps_url: Optional[str] = None
    source: str = "google_maps"
    stop_ref: Optional[str] = None
    order_id: Optional[str] = None
    visit_date: Optional[DateType] = None
    tarjeta_status: str = "TT"
    locked: bool = False
    meta: dict = Field(default_factory=dict)


class RouteCreateIn(BaseModel):
    city_id: int
    date: Optional[DateType] = None
    name: Optional[str] = None
    status: str = "draft"
    vehicle_id: Optional[str] = None
    meta: dict = Field(default_factory=dict)
    stops: list[StopIn] = Field(default_factory=list)


class RouteUpdateIn(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    date: Optional[DateType] = None
    vehicle_id: Optional[str] = None
    meta: Optional[dict] = None


class StopUpdateIn(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    maps_url: Optional[str] = None
    visit_date: Optional[DateType] = None
    locked: Optional[bool] = None
    stop_ref: Optional[str] = None
    order_id: Optional[str] = None


class TarjetaIn(BaseModel):
    tarjeta_status: str
    visit_date: Optional[DateType] = None
    tarjeta_by: Optional[str] = None


class ImportMapsIn(BaseModel):
    city_id: int
    date: Optional[DateType] = None
    visit_date: Optional[DateType] = None
    name: Optional[str] = None
    text: Optional[str] = None
    maps_urls: list[str] = Field(default_factory=list)
    route_id: Optional[str] = None
    append: bool = True
    vehicle_id: Optional[str] = None


def _user_id(authorization: Optional[str] = Header(default=None)) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            from api import decode_jwt_token

            payload = decode_jwt_token(token)
            if payload and payload.get("user_id"):
                return str(payload["user_id"])
        except Exception:
            pass
    return os.getenv("DEV_USER_ID", "00000000-0000-0000-0000-000000000001")


def _call(fn):
    try:
        return fn()
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


def _public(route: dict) -> dict:
    body = dict(route)
    body.pop("user_id", None)
    return body


@router.get("/docs")
def v1_docs():
    return {
        "ok": True,
        "openapi": "/openapi.json",
        "api": "/api/v1",
        "endpoints": [
            "GET /api/v1/tarjeta-statuses",
            "GET /api/v1/routes",
            "POST /api/v1/routes",
            "POST /api/v1/routes/import-maps",
            "GET /api/v1/routes/{route_id}",
            "PATCH /api/v1/routes/{route_id}",
            "DELETE /api/v1/routes/{route_id}",
            "PATCH /api/v1/routes/{route_id}/stops/{stop_id}",
            "PATCH /api/v1/routes/{route_id}/stops/{stop_id}/tarjeta",
            "DELETE /api/v1/routes/{route_id}/stops/{stop_id}",
        ],
    }


@router.get("/openapi.json")
def v1_openapi():
    from api import app

    return app.openapi()


@router.get("/tarjeta-statuses")
def list_tarjeta_statuses():
    return tarjeta_legend()


@router.get("/routes")
def list_routes(
    city_id: Optional[int] = None,
    date: Optional[DateType] = None,
    status: Optional[str] = None,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    return _call(lambda: [_public(row) for row in repo.list_routes(user_id, city_id, date, status)])


@router.post("/routes", status_code=201)
def create_route(
    body: RouteCreateIn,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    on_date = body.date or today_in_app_tz()
    payload = _route_payload(body, on_date)
    return _call(lambda: _public(repo.create_route(user_id, payload)))


@router.post("/routes/import-maps", status_code=201)
def import_maps(
    body: ImportMapsIn,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    blob = "\n".join([body.text or "", *body.maps_urls])
    parsed = parse_maps_text(blob)
    if not parsed:
        raise HTTPException(status_code=400, detail="No Google Maps links found")
    on_date = body.date or today_in_app_tz()
    visit = body.visit_date or on_date

    def run():
        target_id = body.route_id
        existing_stops: list[dict] = []
        if target_id:
            existing_stops = repo.get_route(user_id, target_id).get("stops") or []
        elif body.append:
            draft = repo.find_draft(user_id, body.city_id, on_date.isoformat())
            if draft:
                target_id = draft["id"]
                existing_stops = draft.get("stops") or []
        _estimate_legs(existing_stops, parsed)
        if target_id:
            return repo.add_stops(user_id, target_id, parsed, visit.isoformat())
        payload = {
            "city_id": body.city_id,
            "date": on_date,
            "visit_date": visit,
            "name": body.name or f"Maps {on_date.isoformat()}",
            "status": "draft",
            "vehicle_id": body.vehicle_id,
            "meta": {"source": "google_maps"},
            "stops": parsed,
        }
        return repo.create_route(user_id, payload)

    created = _call(run)
    return _public(created)


@router.get("/routes/{route_id}")
def get_route(route_id: str, user_id: str = Depends(_user_id), repo=Depends(get_repository)):
    return _call(lambda: _public(repo.get_route(user_id, route_id)))


@router.patch("/routes/{route_id}")
def update_route(
    route_id: str,
    body: RouteUpdateIn,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    payload = body.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] is not None:
        payload["status"] = normalize_route_status(payload["status"])
    return _call(lambda: _public(repo.update_route(user_id, route_id, payload)))


@router.delete("/routes/{route_id}")
def delete_route(route_id: str, user_id: str = Depends(_user_id), repo=Depends(get_repository)):
    _call(lambda: repo.delete_route(user_id, route_id))
    return {"status": "deleted", "route_id": route_id}


@router.patch("/routes/{route_id}/stops/{stop_id}")
def update_stop(
    route_id: str,
    stop_id: str,
    body: StopUpdateIn,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    payload = body.model_dump(exclude_unset=True)
    return _call(lambda: repo.update_stop(user_id, route_id, stop_id, payload))


@router.patch("/routes/{route_id}/stops/{stop_id}/tarjeta")
def set_tarjeta(
    route_id: str,
    stop_id: str,
    body: TarjetaIn,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    payload = body.model_dump()

    def run():
        from app.tarjeta import normalize_tarjeta

        payload["tarjeta_status"] = normalize_tarjeta(payload["tarjeta_status"])
        return repo.set_tarjeta(user_id, route_id, stop_id, payload)

    return _call(run)


@router.delete("/routes/{route_id}/stops/{stop_id}")
def delete_stop(
    route_id: str,
    stop_id: str,
    user_id: str = Depends(_user_id),
    repo=Depends(get_repository),
):
    _call(lambda: repo.delete_stop(user_id, route_id, stop_id))
    return {"status": "deleted", "stop_id": stop_id}


def _estimate_legs(existing: list[dict], incoming: list[dict]) -> None:
    anchor = dict(existing[-1]) if existing else None
    chain = ([anchor] if anchor else []) + incoming
    fill_osrm_legs(incoming)
    fill_leg_distance(chain)


def _route_payload(body: RouteCreateIn, on_date: DateType) -> dict:
    stops = []
    for stop in body.stops:
        item = stop.model_dump()
        item_visit = item.get("visit_date") or on_date
        item["visit_date"] = item_visit.isoformat()
        stops.append(item)
    return {
        "city_id": body.city_id,
        "date": on_date,
        "visit_date": on_date,
        "name": body.name or f"Ruta {on_date.isoformat()}",
        "status": body.status,
        "vehicle_id": body.vehicle_id,
        "meta": body.meta,
        "stops": stops,
    }
