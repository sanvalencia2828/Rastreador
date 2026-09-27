"""Postgres persistence for planner routes. Replaces any in-memory route store."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.memory_repo import ConflictError, NotFoundError
from app.tarjeta import normalize_route_status, normalize_tarjeta


class PostgresRouteRepository:
    def __init__(self, engine) -> None:
        self.engine = engine

    def list_routes(self, user_id: str, city_id=None, on_date=None, status=None) -> list[dict]:
        clauses = ["user_id = :user_id"]
        params: dict[str, Any] = {"user_id": user_id}
        if city_id is not None:
            clauses.append("city_id = :city_id")
            params["city_id"] = city_id
        if on_date is not None:
            clauses.append('"date" = :on_date')
            params["on_date"] = on_date
        if status is not None:
            clauses.append("status = :status")
            params["status"] = normalize_route_status(status)
        query = f"""
            SELECT id, user_id, city_id, name, status, vehicle_id, "date", meta,
                   created_at, updated_at
              FROM routes
             WHERE {' AND '.join(clauses)}
             ORDER BY "date" DESC, name
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()
            return [self._route_with_stops(conn, row) for row in rows]

    def get_route(self, user_id: str, route_id: str) -> dict:
        with self.engine.connect() as conn:
            row = self._fetch_route(conn, user_id, route_id)
            return self._route_with_stops(conn, row)

    def create_route(self, user_id: str, payload: dict) -> dict:
        route_id = str(uuid4())
        status = normalize_route_status(payload.get("status") or "draft")
        try:
            with self.engine.begin() as conn:
                self._ensure_city(conn, payload["city_id"])
                conn.execute(
                    text(
                        """
                        INSERT INTO routes
                            (id, user_id, city_id, name, status, vehicle_id, "date", meta)
                        VALUES
                            (:id, :user_id, :city_id, :name, :status, :vehicle_id, :date, CAST(:meta AS jsonb))
                        """
                    ),
                    {
                        "id": route_id,
                        "user_id": user_id,
                        "city_id": payload["city_id"],
                        "name": payload["name"],
                        "status": status,
                        "vehicle_id": payload.get("vehicle_id"),
                        "date": payload["date"],
                        "meta": json.dumps(payload.get("meta") or {}),
                    },
                )
                self._insert_stops(conn, route_id, payload.get("stops") or [], payload["visit_date"], 1)
            return self.get_route(user_id, route_id)
        except IntegrityError as exc:
            raise ConflictError("Could not create route") from exc

    def update_route(self, user_id: str, route_id: str, payload: dict) -> dict:
        sets = []
        params: dict[str, Any] = {"id": route_id, "user_id": user_id}
        if payload.get("name"):
            sets.append("name = :name")
            params["name"] = payload["name"]
        if payload.get("status") is not None:
            sets.append("status = :status")
            params["status"] = normalize_route_status(payload["status"])
        if payload.get("date") is not None:
            sets.append('"date" = :date')
            params["date"] = payload["date"]
        if "vehicle_id" in payload:
            sets.append("vehicle_id = :vehicle_id")
            params["vehicle_id"] = payload["vehicle_id"]
        if payload.get("meta") is not None:
            sets.append("meta = CAST(:meta AS jsonb)")
            params["meta"] = json.dumps(payload["meta"])
        if not sets:
            return self.get_route(user_id, route_id)
        with self.engine.begin() as conn:
            self._fetch_route(conn, user_id, route_id)
            result = conn.execute(
                text(
                    f"""
                    UPDATE routes
                       SET {', '.join(sets)}
                     WHERE id = :id AND user_id = :user_id
                    """
                ),
                params,
            )
            if result.rowcount == 0:
                raise NotFoundError("Route not found")
            if params.get("status"):
                conn.execute(
                    text("UPDATE route_stops SET locked = :locked WHERE route_id = :id"),
                    {"id": route_id, "locked": params["status"] != "draft"},
                )
        return self.get_route(user_id, route_id)

    def delete_route(self, user_id: str, route_id: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM routes WHERE id = :id AND user_id = :user_id"),
                {"id": route_id, "user_id": user_id},
            )
            if result.rowcount == 0:
                raise NotFoundError("Route not found")

    def add_stops(self, user_id: str, route_id: str, stops: list[dict], visit_date: str) -> dict:
        with self.engine.begin() as conn:
            row = self._fetch_route(conn, user_id, route_id)
            if row.status != "draft":
                raise ConflictError("Route is not editable")
            current = conn.execute(
                text("SELECT COALESCE(MAX(seq), 0) FROM route_stops WHERE route_id = :id"),
                {"id": route_id},
            ).scalar()
            self._insert_stops(conn, route_id, stops, date.fromisoformat(visit_date), int(current) + 1)
        return self.get_route(user_id, route_id)

    def update_stop(self, user_id: str, route_id: str, stop_id: str, payload: dict) -> dict:
        with self.engine.begin() as conn:
            route = self._fetch_route(conn, user_id, route_id)
            if route.status == "committed" and any(
                key in payload for key in ("address", "lat", "lng", "seq", "maps_url")
            ):
                raise ConflictError("Committed route stops cannot be edited")
            sets = []
            params: dict[str, Any] = {"id": stop_id, "route_id": route_id}
            for key, column in (
                ("address", "address"),
                ("lat", "lat"),
                ("lng", "lng"),
                ("maps_url", "maps_url"),
                ("locked", "locked"),
                ("stop_ref", "stop_ref"),
                ("order_id", "order_id"),
            ):
                if key in payload:
                    sets.append(f"{column} = :{key}")
                    params[key] = payload[key]
            if "lng" in payload:
                sets.append("lon = :lng")
            if payload.get("visit_date") is not None:
                sets.append("visit_date = :visit_date")
                params["visit_date"] = payload["visit_date"]
            if not sets:
                return self._public_stop(self._fetch_stop(conn, route_id, stop_id))
            result = conn.execute(
                text(
                    f"""
                    UPDATE route_stops
                       SET {', '.join(sets)}
                     WHERE id = :id AND route_id = :route_id
                    """
                ),
                params,
            )
            if result.rowcount == 0:
                raise NotFoundError("Stop not found")
            return self._public_stop(self._fetch_stop(conn, route_id, stop_id))

    def set_tarjeta(self, user_id: str, route_id: str, stop_id: str, payload: dict) -> dict:
        status = normalize_tarjeta(payload["tarjeta_status"])
        with self.engine.begin() as conn:
            self._fetch_route(conn, user_id, route_id)
            params = {
                "id": stop_id,
                "route_id": route_id,
                "tarjeta_status": status,
                "tarjeta_by": payload.get("tarjeta_by"),
                "visit_date": payload.get("visit_date"),
            }
            visit_sql = ", visit_date = :visit_date" if payload.get("visit_date") is not None else ""
            result = conn.execute(
                text(
                    f"""
                    UPDATE route_stops
                       SET tarjeta_status = :tarjeta_status,
                           tarjeta_at = NOW(),
                           tarjeta_by = :tarjeta_by
                           {visit_sql}
                     WHERE id = :id AND route_id = :route_id
                    """
                ),
                params,
            )
            if result.rowcount == 0:
                raise NotFoundError("Stop not found")
            return self._public_stop(self._fetch_stop(conn, route_id, stop_id))

    def delete_stop(self, user_id: str, route_id: str, stop_id: str) -> None:
        with self.engine.begin() as conn:
            route = self._fetch_route(conn, user_id, route_id)
            if route.status != "draft":
                raise ConflictError("Route is not editable")
            stop = self._fetch_stop(conn, route_id, stop_id)
            if stop.locked:
                raise ConflictError("Stop is locked")
            conn.execute(
                text("DELETE FROM route_stops WHERE id = :id AND route_id = :route_id"),
                {"id": stop_id, "route_id": route_id},
            )

    def find_draft(self, user_id: str, city_id: int, on_date: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, user_id, city_id, name, status, vehicle_id, "date", meta,
                           created_at, updated_at
                      FROM routes
                     WHERE user_id = :user_id
                       AND city_id = :city_id
                       AND "date" = :on_date
                       AND status = 'draft'
                     ORDER BY created_at
                     LIMIT 1
                    """
                ),
                {"user_id": user_id, "city_id": city_id, "on_date": on_date},
            ).fetchone()
            if not row:
                return None
            return self._route_with_stops(conn, row)

    def _insert_stops(self, conn, route_id: str, stops: list[dict], visit_date: date, start_seq: int) -> None:
        for offset, stop in enumerate(stops):
            seq = start_seq + offset
            lng = stop.get("lng")
            stop_visit = stop.get("visit_date") or visit_date
            if isinstance(stop_visit, str):
                stop_visit = date.fromisoformat(stop_visit)
            conn.execute(
                text(
                    """
                    INSERT INTO route_stops (
                        id, route_id, seq, stop_order, locked, order_id, stop_ref,
                        lat, lng, lon, address, maps_url, source, visit_date,
                        tarjeta_status, eta_s, distance_m, meta
                    ) VALUES (
                        :id, :route_id, :seq, :seq, :locked, :order_id, :stop_ref,
                        :lat, :lng, :lon, :address, :maps_url, :source, :visit_date,
                        :tarjeta_status, :eta_s, :distance_m, CAST(:meta AS jsonb)
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "route_id": route_id,
                    "seq": seq,
                    "locked": bool(stop.get("locked") or False),
                    "order_id": stop.get("order_id"),
                    "stop_ref": stop.get("stop_ref"),
                    "lat": stop.get("lat"),
                    "lng": lng,
                    "lon": lng,
                    "address": stop.get("address"),
                    "maps_url": stop.get("maps_url"),
                    "source": stop.get("source") or "google_maps",
                    "visit_date": stop_visit,
                    "tarjeta_status": normalize_tarjeta(stop.get("tarjeta_status") or "TT"),
                    "eta_s": stop.get("eta_s"),
                    "distance_m": stop.get("distance_m"),
                    "meta": json.dumps(stop.get("meta") or {}),
                },
            )

    def _ensure_city(self, conn, city_id: int) -> None:
        row = conn.execute(
            text("SELECT id FROM cities WHERE id = :id"),
            {"id": city_id},
        ).fetchone()
        if not row:
            raise NotFoundError("City not found")

    def _fetch_route(self, conn, user_id: str, route_id: str):
        row = conn.execute(
            text(
                """
                SELECT id, user_id, city_id, name, status, vehicle_id, "date", meta,
                       created_at, updated_at
                  FROM routes
                 WHERE id = :id AND user_id = :user_id
                """
            ),
            {"id": route_id, "user_id": user_id},
        ).fetchone()
        if not row:
            raise NotFoundError("Route not found")
        return row

    def _fetch_stop(self, conn, route_id: str, stop_id: str):
        row = conn.execute(
            text(
                """
                SELECT id, route_id, seq, locked, order_id, stop_ref, lat, lng, lon,
                       address, maps_url, source, visit_date, tarjeta_status, tarjeta_at,
                       tarjeta_by, eta_s, distance_m, meta
                  FROM route_stops
                 WHERE id = :id AND route_id = :route_id
                """
            ),
            {"id": stop_id, "route_id": route_id},
        ).fetchone()
        if not row:
            raise NotFoundError("Stop not found")
        return row

    def _route_with_stops(self, conn, row) -> dict:
        stops = conn.execute(
            text(
                """
                SELECT id, route_id, seq, locked, order_id, stop_ref, lat, lng, lon,
                       address, maps_url, source, visit_date, tarjeta_status, tarjeta_at,
                       tarjeta_by, eta_s, distance_m, meta
                  FROM route_stops
                 WHERE route_id = :route_id
                 ORDER BY seq
                """
            ),
            {"route_id": row.id},
        ).fetchall()
        return _public_route(row, [_public_stop(stop) for stop in stops])

    def _public_stop(self, row) -> dict:
        return _public_stop(row)


def _as_json(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _num(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _public_stop(row) -> dict:
    lng = row.lng if row.lng is not None else row.lon
    return {
        "id": str(row.id),
        "route_id": str(row.route_id),
        "seq": row.seq,
        "locked": bool(row.locked),
        "order_id": row.order_id,
        "stop_ref": row.stop_ref,
        "lat": _num(row.lat),
        "lng": _num(lng),
        "address": row.address,
        "maps_url": row.maps_url,
        "source": row.source or "google_maps",
        "visit_date": _iso(row.visit_date),
        "tarjeta_status": row.tarjeta_status,
        "tarjeta_at": _iso(row.tarjeta_at),
        "tarjeta_by": row.tarjeta_by,
        "eta_s": row.eta_s,
        "distance_m": row.distance_m,
        "meta": _as_json(row.meta),
    }


def _public_route(row, stops: list[dict]) -> dict:
    return {
        "id": str(row.id),
        "city_id": row.city_id,
        "name": row.name,
        "status": row.status,
        "vehicle_id": row.vehicle_id,
        "date": _iso(row.date),
        "meta": _as_json(row.meta),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "stops": stops,
    }
