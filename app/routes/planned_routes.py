"""DB-backed planned routes: CRUD, completion, generation."""

import os
from datetime import date, datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.planned_route import (
    GeneratedStop,
    PlannedRouteCreate,
    RouteCompleteRequest,
    RouteCreate,
    RouteGenerateRequest,
    RouteGenerateResponse,
    RouteOptimizeRequest,
    RouteStatusUpdate,
)
from app.services.geo import cnae_to_category, fix_encoding
from app.services.route_planning import (
    _get_route_detail,
    _route_distance_km,
    nearest_neighbor_order,
)
from app.services.street_time_log import refresh_street_times_safely
from app.services.visit_metrics import recalculate_visit_interval

router = APIRouter()


@router.post("/api/routes")
def create_route(
    route: PlannedRouteCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Persist an ordered business route with planned route stops."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    if not route.business_ids:
        raise HTTPException(status_code=400, detail="At least one business is required")
    if len(set(route.business_ids)) != len(route.business_ids):
        raise HTTPException(status_code=400, detail="business_ids must be unique")

    start_lat = route.start.lat if route.start else route.start_lat
    start_lng = route.start.lng if route.start else route.start_lng
    if start_lat is None or start_lng is None:
        raise HTTPException(status_code=400, detail="start_lat and start_lng are required")

    try:
        from sqlalchemy import bindparam

        with db_engine.begin() as conn:
            business_rows = conn.execute(
                text("""
                    SELECT id, nome_fantasia, cnpj_completo, logradouro,
                           bairro, municipio, latitude, longitude
                    FROM estabelecimentos
                    WHERE id IN :business_ids
                """).bindparams(bindparam("business_ids", expanding=True)),
                {"business_ids": route.business_ids},
            ).fetchall()
            businesses_by_id = {int(row.id): dict(row._mapping) for row in business_rows}
            missing_ids = [
                business_id
                for business_id in route.business_ids
                if business_id not in businesses_by_id
            ]
            if missing_ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"Business(es) not found: {missing_ids}",
                )

            ordered_businesses = [businesses_by_id[business_id] for business_id in route.business_ids]
            if any(
                business["latitude"] is None or business["longitude"] is None
                for business in ordered_businesses
            ):
                raise HTTPException(
                    status_code=400,
                    detail="All businesses must have latitude and longitude",
                )

            total_distance_km = _route_distance_km(
                start_lat,
                start_lng,
                ordered_businesses,
            )
            total_duration_min = total_distance_km / 40.0 * 60.0
            route_row = conn.execute(
                text("""
                    INSERT INTO routes (
                        user_id, name, city_id, start_lat, start_lng, status,
                        planned_at, total_stops_planned, total_stops_done,
                        total_distance_km, total_duration_min, notes
                    )
                    VALUES (
                        :user_id, :name, :city_id, :start_lat, :start_lng, 'planned',
                        NOW(), :total_stops_planned, 0,
                        :total_distance_km, :total_duration_min, :notes
                    )
                    RETURNING id
                """),
                {
                    "user_id": user_id,
                    "name": route.name.strip(),
                    "city_id": route.city_id,
                    "start_lat": start_lat,
                    "start_lng": start_lng,
                    "total_stops_planned": len(ordered_businesses),
                    "total_distance_km": total_distance_km,
                    "total_duration_min": total_duration_min,
                    "notes": route.notes,
                },
            ).fetchone()
            if not route_row:
                raise HTTPException(status_code=500, detail="Route creation failed")

            route_id = route_row[0]
            for stop_order, business in enumerate(ordered_businesses, start=1):
                conn.execute(
                    text("""
                        INSERT INTO route_stops (
                            route_id, business_id, stop_order, address, lat, lon,
                            display_name, visited, skipped
                        )
                        VALUES (
                            :route_id, :business_id, :stop_order, :address, :lat, :lon,
                            :display_name, FALSE, FALSE
                        )
                    """),
                    {
                        "route_id": route_id,
                        "business_id": business["id"],
                        "stop_order": stop_order,
                        "address": business["logradouro"] or "",
                        "lat": business["latitude"],
                        "lon": business["longitude"],
                        "display_name": business["nome_fantasia"] or "",
                    },
                )

            return _get_route_detail(conn, route_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {e}")


@router.get("/api/routes")
def list_routes(
    status: Optional[str] = None,
    city_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    """List planned routes, optionally filtered by status or city."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if status and status not in {"planned", "active", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid route status")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")

    query = """
        SELECT r.id, r.user_id, r.name, r.city_id, r.start_lat, r.start_lng,
               r.status, r.planned_at, r.started_at, r.ended_at,
               r.completed_at, r.completed_date,
               r.total_stops_planned, r.total_stops_done,
               r.total_distance_km, r.total_duration_min, r.notes,
               COUNT(rs.id) AS stops_count
        FROM routes r
        LEFT JOIN route_stops rs ON rs.route_id = r.id
        WHERE 1 = 1
    """
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    query += " AND r.user_id = :user_id"
    params["user_id"] = user_id
    if status:
        query += " AND r.status = :status"
        params["status"] = status
    if city_id is not None:
        query += " AND r.city_id = :city_id"
        params["city_id"] = city_id
    query += " GROUP BY r.id ORDER BY r.planned_at DESC NULLS LAST LIMIT :limit OFFSET :offset"

    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()
            return [
                {
                    "id": str(row.id),
                    "user_id": str(row.user_id) if row.user_id is not None else None,
                    "name": row.name,
                    "city_id": row.city_id,
                    "start_lat": float(row.start_lat) if row.start_lat is not None else None,
                    "start_lng": float(row.start_lng) if row.start_lng is not None else None,
                    "status": row.status,
                    "planned_at": row.planned_at.isoformat() if row.planned_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "completed_date": row.completed_date.isoformat() if row.completed_date else None,
                    "total_stops_planned": int(row.total_stops_planned or 0),
                    "total_stops_done": int(row.total_stops_done or 0),
                    "total_distance_km": float(row.total_distance_km or 0),
                    "total_duration_min": float(row.total_duration_min or 0),
                    "notes": row.notes,
                    "stops_count": int(row.stops_count or 0),
                }
                for row in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list routes: {e}")


@router.get("/api/routes/{route_id}")
def get_route(route_id: str, user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            accessible = conn.execute(
                text("SELECT id FROM routes WHERE id = :route_id AND user_id = :user_id"),
                {"route_id": route_id, "user_id": user_id},
            ).fetchone()
            if not accessible:
                raise HTTPException(status_code=404, detail="Route not found")
            return _get_route_detail(conn, route_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch route: {e}")


@router.patch("/api/routes/{route_id}/status")
def update_route_status(
    route_id: str,
    body: RouteStatusUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Apply the allowed planned -> active/cancelled transitions atomically."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.begin() as conn:
            query = """
                SELECT id, status
                FROM routes
                WHERE id = :route_id
            """
            query += " AND user_id = :user_id FOR UPDATE"
            params: Dict[str, Any] = {"route_id": route_id, "user_id": user_id}

            route_row = conn.execute(text(query), params).fetchone()
            if not route_row:
                raise HTTPException(status_code=404, detail="Route not found")

            current_status = route_row.status
            allowed = (
                body.status == "active" and current_status == "planned"
            ) or (
                body.status == "cancelled"
                and current_status in {"planned", "active"}
            )
            if not allowed:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route cannot transition from '{current_status}' to '{body.status}'",
                )

            conn.execute(
                text("""
                    UPDATE routes
                    SET status = :status,
                        started_at = CASE
                            WHEN :status = 'active' THEN COALESCE(started_at, NOW())
                            ELSE started_at
                        END
                    WHERE id = :route_id
                """),
                {"route_id": route_id, "status": body.status},
            )
            return _get_route_detail(conn, route_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update route status: {e}")


@router.post("/api/routes/{route_id}/complete")
def complete_route(
    route_id: str,
    body: RouteCompleteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Complete a route, record visits, and recalculate business frequency."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if body.completed_date > date.today():
        raise HTTPException(
            status_code=400,
            detail="completed_date cannot be in the future",
        )
    business_ids = [stop.business_id for stop in body.stops]
    if len(set(business_ids)) != len(business_ids):
        raise HTTPException(status_code=400, detail="Each business can appear only once")

    visit_date = datetime.combine(
        body.completed_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    visited_at = datetime.now(timezone.utc)

    try:
        with db_engine.begin() as conn:
            route_query = """
                SELECT id, user_id, status
                FROM routes
                WHERE id = :route_id
            """
            route_query += " AND user_id = :user_id FOR UPDATE"
            route_params: Dict[str, Any] = {"route_id": route_id, "user_id": user_id}

            route_row = conn.execute(text(route_query), route_params).fetchone()
            if not route_row or route_row.status not in {"planned", "active"}:
                raise HTTPException(status_code=404, detail="Route not found or already completed")

            route_stop_rows = conn.execute(
                text("""
                    SELECT business_id
                    FROM route_stops
                    WHERE route_id = :route_id
                    FOR UPDATE
                """),
                {"route_id": route_id},
            ).fetchall()
            route_business_ids = {row.business_id for row in route_stop_rows}
            invalid_business_ids = sorted(
                set(business_ids) - route_business_ids
            )
            if invalid_business_ids:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "The following business_ids are not stops on this route: "
                        f"{invalid_business_ids}"
                    ),
                )

            route_user_id = route_row.user_id or user_id or os.getenv(
                "DEV_USER_ID",
                "00000000-0000-0000-0000-000000000001",
            )
            visited_business_ids = set()

            for stop in body.stops:
                stop_row = conn.execute(
                    text("""
                        SELECT
                            rs.id AS route_stop_id,
                            rs.business_id,
                            e.cnpj_completo,
                            COALESCE(e.latitude, ST_Y(e.geom::geometry)) AS lat,
                            COALESCE(e.longitude, ST_X(e.geom::geometry)) AS lon,
                            e.logradouro,
                            e.bairro
                        FROM route_stops rs
                        JOIN estabelecimentos e ON e.id = rs.business_id
                        WHERE rs.route_id = :route_id
                          AND rs.business_id = :business_id
                        FOR UPDATE
                    """),
                    {"route_id": route_id, "business_id": stop.business_id},
                ).fetchone()
                if not stop_row:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Business {stop.business_id} is not a stop on this route",
                    )

                is_visited = stop.status == "visited"
                is_skipped = stop.status in {"skipped", "closed"}
                skip_reason = stop.skip_reason
                if stop.status == "closed" and not skip_reason:
                    skip_reason = "closed"

                if is_visited:
                    if not stop_row.cnpj_completo:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Business {stop.business_id} has no CNPJ",
                        )
                    if stop_row.lat is None or stop_row.lon is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Business {stop.business_id} has no coordinates",
                        )

                    conn.execute(
                        text("""
                            INSERT INTO visits (
                                user_id, route_id, cnpj, lat, lon, logradouro,
                                bairro, notes, source, visited_at
                            )
                            VALUES (
                                :user_id, :route_id, :cnpj, :lat, :lon, :logradouro,
                                :bairro, :notes, 'route', :visited_at
                            )
                        """),
                        {
                            "user_id": route_user_id,
                            "route_id": route_id,
                            "cnpj": stop_row.cnpj_completo,
                            "lat": stop_row.lat,
                            "lon": stop_row.lon,
                            "logradouro": stop_row.logradouro or "",
                            "bairro": stop_row.bairro,
                            "notes": stop.notes,
                            "visited_at": visit_date,
                        },
                    )
                    visited_business_ids.add(stop.business_id)

                conn.execute(
                    text("""
                        UPDATE route_stops
                        SET visited = :visited,
                            visited_at = :visited_at,
                            skipped = :skipped,
                            skip_reason = :skip_reason,
                            notes = :notes
                        WHERE id = :route_stop_id
                    """),
                    {
                        "route_stop_id": stop_row.route_stop_id,
                        "visited": is_visited,
                        "visited_at": visited_at if is_visited else None,
                        "skipped": is_skipped,
                        "skip_reason": skip_reason,
                        "notes": stop.notes,
                    },
                )

            for business_id in visited_business_ids:
                recalculate_visit_interval(conn, business_id)
            refresh_street_times_safely(conn, route_user_id, route_id)

            total_stops_done = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM route_stops
                    WHERE route_id = :route_id AND visited = TRUE
                """),
                {"route_id": route_id},
            ).scalar() or 0

            conn.execute(
                text("""
                    UPDATE routes
                    SET status = 'completed',
                        started_at = COALESCE(:started_at, started_at),
                        ended_at = COALESCE(:ended_at, NOW()),
                        completed_date = :completed_date,
                        completed_at = NOW(),
                        total_stops_done = :total_stops_done
                    WHERE id = :route_id
                """),
                {
                    "route_id": route_id,
                    "started_at": body.started_at,
                    "ended_at": body.ended_at,
                    "completed_date": body.completed_date,
                    "total_stops_done": int(total_stops_done),
                },
            )

            return {
                "message": "Route completed successfully",
                "route": _get_route_detail(conn, route_id),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to complete route: {e}")


@router.put("/api/routes/{route_id}")
def update_route(route_id: str, route: RouteCreate, user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    if not route.stops:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    try:
        with db_engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM routes WHERE id = :route_id AND user_id = :user_id"),
                {"route_id": route_id, "user_id": user_id},
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Route not found")
            conn.execute(
                text("""
                    UPDATE routes
                    SET name = :name, city_id = :city_id
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"name": route.name.strip(), "city_id": route.city_id, "route_id": route_id, "user_id": user_id},
            )
            conn.execute(text("DELETE FROM route_stops WHERE route_id = :route_id"), {"route_id": route_id})
            for index, stop in enumerate(route.stops, start=1):
                conn.execute(
                    text("""
                        INSERT INTO route_stops (route_id, stop_order, address, lat, lon, cep, display_name)
                        VALUES (:route_id, :stop_order, :address, :lat, :lon, :cep, :display_name)
                    """),
                    {
                        "route_id": route_id,
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    },
                )
            conn.commit()
            return {
                "id": route_id,
                "name": route.name.strip(),
                "city_id": route.city_id,
                "created_at": None,
                "stops": [
                    {
                        "id": str(route_id),
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    }
                    for index, stop in enumerate(route.stops, start=1)
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update route: {e}")


@router.delete("/api/routes/{route_id}")
def delete_route(route_id: str, user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM routes WHERE id = :route_id AND user_id = :user_id RETURNING id"),
                {"route_id": route_id, "user_id": user_id},
            )
            conn.commit()
            if result.fetchone() is None:
                raise HTTPException(status_code=404, detail="Route not found")
            return {"status": "deleted", "route_id": route_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete route: {e}")


# ==============================================================================
# INTELLIGENT ROUTE GENERATION
# ==============================================================================
@router.post(
    "/api/routes/generate",
    response_model=RouteGenerateResponse,
    dependencies=[Depends(get_current_user_id)],
)
def generate_route(body: RouteGenerateRequest):
    """
    Generates an intelligent visiting route for a given city.

    Selects businesses that have not been visited in `min_days_without_visit`
    days (or never visited), orders them by days-since-visit descending, then
    applies a Python-side diversity filter so no more than 3 stops share the
    same street (logradouro), until `max_lojas` stops are selected.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    # 1. Resolve city name (404 if it doesn't exist)
    try:
        with db_engine.connect() as conn:
            city_row = conn.execute(
                text("SELECT name FROM cities WHERE id = :city_id"),
                {"city_id": body.city_id},
            ).fetchone()
            if not city_row:
                raise HTTPException(status_code=404, detail="City not found")
            city_name = city_row[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve city: {e}")

    # 2. Candidate businesses with days since last visit (fetch 2x for diversity)
    max_limit = body.max_lojas * 2
    select_query = text("""
        WITH candidate_businesses AS (
            SELECT
                e.cnpj_completo as cnpj,
                e.nome_fantasia,
                e.cnae_fiscal,
                e.bairro,
                e.logradouro,
                e.municipio,
                ST_Y(e.geom::geometry) as lat,
                ST_X(e.geom::geometry) as lon,
                COALESCE(
                    EXTRACT(DAY FROM NOW() - MAX(v.visited_at))::INTEGER,
                    999999
                ) as days_since_visit
            FROM estabelecimentos e
            LEFT JOIN visits v ON v.cnpj = e.cnpj_completo
            WHERE e.situacao_cadastral = 2
              AND e.geom IS NOT NULL
              AND e.municipio = :city_name
            GROUP BY e.cnpj_completo, e.nome_fantasia, e.cnae_fiscal,
                     e.bairro, e.logradouro, e.municipio, e.geom
            HAVING COALESCE(
                EXTRACT(DAY FROM NOW() - MAX(v.visited_at))::INTEGER,
                999999
            ) >= :min_days
        )
        SELECT * FROM candidate_businesses
        ORDER BY days_since_visit DESC
        LIMIT :max_limit
    """)

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                select_query,
                {
                    "city_name": city_name,
                    "min_days": body.min_days_without_visit,
                    "max_limit": max_limit,
                },
            )
            candidates = []
            for row in result:
                row_dict = dict(row._mapping)
                candidates.append(row_dict)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch candidate businesses: {e}"
        )

    total_candidates = len(candidates)

    # 3. Diversity filter: no more than 3 stops per logradouro (street coverage)
    street_counts: Dict[str, int] = {}
    stops: List[GeneratedStop] = []

    for row in candidates:
        if len(stops) >= body.max_lojas:
            break

        logradouro = (row.get("logradouro") or "").strip()
        # Apply per-street cap; empty logradouro is treated as its own bucket
        key = logradouro if logradouro else "<sem logradouro>"
        if street_counts.get(key, 0) >= 3:
            continue
        street_counts[key] = street_counts.get(key, 0) + 1

        days_since = int(row.get("days_since_visit") or 0)

        stops.append(
            GeneratedStop(
                cnpj=str(row.get("cnpj") or ""),
                nome_fantasia=fix_encoding(str(row.get("nome_fantasia") or "")),
                cnae_label=fix_encoding(cnae_to_category(row.get("cnae_fiscal"))),
                bairro=fix_encoding(str(row.get("bairro") or "")),
                logradouro=fix_encoding(logradouro),
                lat=float(row.get("lat") or 0.0),
                lon=float(row.get("lon") or 0.0),
                days_since_visit=days_since,
                # 4. priority = days_since_visit
                priority=days_since,
            )
        )

    print(
        f"Generated route for '{city_name}': {total_candidates} candidates, "
        f"{len(stops)} selected (max_lojas={body.max_lojas}, "
        f"min_days={body.min_days_without_visit})"
    )

    return RouteGenerateResponse(
        city=city_name,
        total_candidates=total_candidates,
        selected=len(stops),
        stops=stops,
    )


@router.post("/api/routes/optimize", dependencies=[Depends(get_current_user_id)])
def optimize_route(body: RouteOptimizeRequest):
    """Order route points from the start using nearest neighbor."""
    if len({point.id for point in body.points}) != len(body.points):
        raise HTTPException(status_code=400, detail="Point ids must be unique")

    ordered_ids, total_distance_m = nearest_neighbor_order(
        body.start.lat,
        body.start.lng,
        body.points,
    )
    total_distance_km = total_distance_m / 1000.0
    return {
        "ordered_ids": ordered_ids,
        "total_distance_km": round(total_distance_km, 3),
        "total_duration_min": round(total_distance_km / 40.0 * 60.0, 1),
    }
