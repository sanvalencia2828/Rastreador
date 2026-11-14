"""Route ordering, distance and detail helpers."""

from datetime import date, datetime
from typing import List, Dict, Any

from fastapi import HTTPException
from sqlalchemy import text

from app.schemas.planned_route import RoutePoint
from app.services.geo import fix_encoding, haversine_m


def nearest_neighbor_order(
    start_lat: float,
    start_lng: float,
    points: List[RoutePoint],
) -> tuple[List[int], float]:
    """Return point ids and meters for a greedy nearest-neighbor route.

    The scan is O(n²) and uses O(n) extra memory, which is appropriate for a
    city route without a road-network matrix or a map provider.
    """
    remaining = list(points)
    current_lat = start_lat
    current_lng = start_lng
    ordered_ids: List[int] = []
    total_distance_m = 0.0

    while remaining:
        next_index, next_point, next_distance = min(
            (
                (
                    index,
                    point,
                    haversine_m(
                        current_lat,
                        current_lng,
                        point.lat,
                        point.lng,
                    ),
                )
                for index, point in enumerate(remaining)
            ),
            key=lambda candidate: candidate[2],
        )
        remaining.pop(next_index)
        total_distance_m += next_distance
        ordered_ids.append(next_point.id)
        current_lat = next_point.lat
        current_lng = next_point.lng

    return ordered_ids, total_distance_m


def _route_distance_km(
    start_lat: float,
    start_lng: float,
    ordered_businesses: List[Dict[str, Any]],
) -> float:
    """Calculate route distance from the start through ordered businesses."""
    current_lat = start_lat
    current_lng = start_lng
    total_distance_m = 0.0
    for business in ordered_businesses:
        next_lat = float(business["latitude"])
        next_lng = float(business["longitude"])
        total_distance_m += haversine_m(current_lat, current_lng, next_lat, next_lng)
        current_lat = next_lat
        current_lng = next_lng
    return total_distance_m / 1000.0


def _get_route_detail(conn, route_id) -> Dict[str, Any]:
    """Load a route and its business-enriched stops from one connection."""
    route_row = conn.execute(
        text("""
            SELECT id, user_id, name, city_id, start_lat, start_lng, status,
                   planned_at, started_at, ended_at, completed_at, completed_date,
                   total_stops_planned, total_stops_done, total_distance_km,
                   total_duration_min, notes
            FROM routes
            WHERE id = :route_id
        """),
        {"route_id": route_id},
    ).fetchone()
    if not route_row:
        raise HTTPException(status_code=404, detail="Route not found")

    route = dict(route_row._mapping)
    stop_rows = conn.execute(
        text("""
            SELECT
                rs.id AS stop_id,
                rs.route_id,
                rs.business_id,
                rs.stop_order,
                rs.visited,
                rs.visited_at,
                rs.skipped,
                rs.skip_reason,
                rs.notes AS stop_notes,
                rs.address,
                rs.lat AS stop_lat,
                rs.lon AS stop_lng,
                e.id AS business_row_id,
                e.cnpj_completo,
                e.nome_fantasia,
                e.latitude AS business_lat,
                e.longitude AS business_lng,
                e.municipio,
                e.bairro,
                e.logradouro
            FROM route_stops rs
            LEFT JOIN estabelecimentos e ON e.id = rs.business_id
            WHERE rs.route_id = :route_id
            ORDER BY rs.stop_order
        """),
        {"route_id": route_id},
    ).fetchall()

    def iso(value):
        return value.isoformat() if value is not None else None

    stops = []
    for stop_row in stop_rows:
        stop = dict(stop_row._mapping)
        business = None
        if stop["business_row_id"] is not None:
            business = {
                "id": int(stop["business_row_id"]),
                "cnpj": stop["cnpj_completo"],
                "name": fix_encoding(stop["nome_fantasia"] or ""),
                "lat": float(stop["business_lat"]) if stop["business_lat"] is not None else None,
                "lng": float(stop["business_lng"]) if stop["business_lng"] is not None else None,
                "city": fix_encoding(stop["municipio"] or ""),
                "bairro": fix_encoding(stop["bairro"] or ""),
                "logradouro": fix_encoding(stop["logradouro"] or ""),
            }
        stops.append({
            "id": str(stop["stop_id"]),
            "route_id": str(stop["route_id"]),
            "business_id": int(stop["business_id"]) if stop["business_id"] is not None else None,
            "order": stop["stop_order"],
            "visited": bool(stop["visited"]),
            "visited_at": iso(stop["visited_at"]),
            "skipped": bool(stop["skipped"]),
            "skip_reason": stop["skip_reason"],
            "notes": stop["stop_notes"],
            "address": stop["address"],
            "lat": float(stop["stop_lat"]),
            "lng": float(stop["stop_lng"]),
            "business": business,
        })

    return {
        "id": str(route["id"]),
        "user_id": str(route["user_id"]) if route["user_id"] is not None else None,
        "name": route["name"],
        "city_id": int(route["city_id"]) if route["city_id"] is not None else None,
        "start_lat": float(route["start_lat"]) if route["start_lat"] is not None else None,
        "start_lng": float(route["start_lng"]) if route["start_lng"] is not None else None,
        "status": route["status"],
        "planned_at": iso(route["planned_at"]),
        "started_at": iso(route["started_at"]),
        "ended_at": iso(route["ended_at"]),
        "completed_at": iso(route["completed_at"]),
        "completed_date": iso(route["completed_date"]),
        "total_stops_planned": int(route["total_stops_planned"] or 0),
        "total_stops_done": int(route["total_stops_done"] or 0),
        "total_distance_km": float(route["total_distance_km"] or 0),
        "total_duration_min": float(route["total_duration_min"] or 0),
        "notes": route["notes"],
        "stops": stops,
    }


def _business_route_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add read-time urgency fields to a business row."""
    last_visit_date = row.get("last_visit_date")
    if isinstance(last_visit_date, datetime):
        last_visit_date = last_visit_date.date()

    visits_count = int(row.get("visits_count") or 0)
    avg_interval = row.get("avg_visit_interval_days")
    avg_interval = float(avg_interval) if avg_interval is not None else None
    days_since_last_visit = (
        (date.today() - last_visit_date).days if last_visit_date else None
    )
    due_in_days = (
        int(round(avg_interval - days_since_last_visit))
        if avg_interval is not None and days_since_last_visit is not None
        else None
    )

    if visits_count == 0:
        status_due = "never"
    elif due_in_days is not None and due_in_days < 0:
        status_due = "overdue"
    elif due_in_days is not None and due_in_days <= 7:
        status_due = "due_soon"
    else:
        status_due = "ok"

    row["last_visit_date"] = last_visit_date.isoformat() if last_visit_date else None
    row["visits_count"] = visits_count
    row["avg_visit_interval_days"] = avg_interval
    row["days_since_last_visit"] = days_since_last_visit
    row["due_in_days"] = due_in_days
    row["status_due"] = status_due
    return row
