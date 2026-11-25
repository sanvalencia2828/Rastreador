"""DB-backed planned routes: CRUD, completion, generation."""

import os
from itertools import combinations, permutations
from datetime import date, datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.planned_route import (
    ClienteDiaListed,
    ClienteDiaStop,
    ClienteListed,
    ClientesDiaRequest,
    ClientesDiaResponse,
    GeneratedStop,
    PlannedRouteCreate,
    RouteCompleteRequest,
    RouteCreate,
    RouteGenerateRequest,
    RouteGenerateResponse,
    RouteOptimizeRequest,
    RouteStatusUpdate,
    WeekDay,
    WeekRouteRequest,
    WeekRouteResponse,
)
from app.services.day_route import DIAS_SEMANA, cluster_days, is_maringa, maps_links, order_day, path_km
from app.services.geo import cnae_to_category, fix_encoding, haversine_km
from app.services.route_planning import (
    _get_route_detail,
    _route_distance_km,
    nearest_neighbor_order,
)
from app.services.visit_metrics import recalculate_visit_interval
from cities import CITIES, canonical_city, city_km

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
MARINGA_MAX_STOPS = 10  # tope de paradas por dia en Maringa (clientes)
MAX_MIX_KM = 60  # dos ciudades mas lejanas no comparten ruta diaria
WARN_MIX_KM = 40  # se permiten (p. ej. Maringa y Arapongas, ~52 km) pero se avisa
VISITA_MIN = 15  # /clientes-dia: minutos por visita para la hora estimada
VELOCIDAD_KMH = 40  # /clientes-dia: velocidad media (linea recta) para la hora estimada
MAX_PERMUT_CIUDADES = 7  # hasta aqui se prueban todos los ordenes de ciudades (7! = 5040)


def _check_cities(names: list[str]) -> tuple[list[str], list[str]]:
    """Nombres canonicos sin repetir y avisos; 422 si hay una ciudad desconocida o dos a mas de MAX_MIX_KM."""
    cities: list[str] = []
    for name in names:
        city = canonical_city(name)
        if city is None:
            raise HTTPException(status_code=422, detail=f"Ciudad desconocida: {name[:60]}")
        if city not in cities:
            cities.append(city)
    if not cities:
        raise HTTPException(status_code=422, detail="Elige al menos una ciudad")
    avisos = []
    for a, b in combinations(cities, 2):
        km = city_km(a, b)
        if km > MAX_MIX_KM:
            raise HTTPException(
                status_code=422,
                detail=f"{a} y {b} están a ~{km:.0f} km: una ruta diaria no puede mezclar ciudades a más de {MAX_MIX_KM} km",
            )
        if km > WARN_MIX_KM:
            avisos.append(f"{a} y {b} están a ~{km:.0f} km: algunos días tendrán un tramo largo entre ciudades.")
    return cities, avisos


def _load_clientes(user_id: str):
    try:
        with db_engine.connect() as conn:
            return conn.execute(
                text("""
                    SELECT id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, lat, lon, geocode_status,
                           visita_diaria, atrasado
                    FROM clientes WHERE user_id = :u ORDER BY external_id
                """),
                {"u": user_id},
            ).fetchall()
    except Exception as e:  # el mensaje del driver puede traer parametros
        raise HTTPException(status_code=500, detail=f"Failed to fetch clientes ({type(e).__name__})")


def _listed(r) -> ClienteListed:
    return ClienteListed(nombre=r.nombre_negocio or r.nombre_cliente or "", direccion=r.direccion or "", municipio=r.municipio or "")


def _plan_clientes(rows, dias: int, cap: int, cities: list[str]) -> dict:
    """Separa y agrupa los clientes UNA vez (KMeans); lo usan el endpoint de un dia y el de la semana.

    Los de visita diaria no entran al KMeans: van en todos los dias y ocupan lugar en el tope `cap`.
    """
    located = [r for r in rows if r.geocode_status == "ok" and r.lat is not None and r.lon is not None]
    inside = [r for r in located if canonical_city(r.municipio) in cities]
    daily = [r for r in inside if r.visita_diaria]
    if len(daily) > cap:
        raise HTTPException(
            status_code=422,
            detail=f"Hay {len(daily)} clientes de visita diaria y el tope es {cap} paradas por día: sube el tope o desmarca alguno",
        )
    normal = [r for r in inside if not r.visita_diaria]
    groups, overflow = cluster_days([(float(r.lat), float(r.lon)) for r in normal], dias, cap - len(daily))
    if daily:  # sin clientes normales igual hay dias: los de los diarios
        groups += [[] for _ in range(dias - len(groups))]
    ordered = normal + daily  # los indices de groups/overflow apuntan a la parte `normal`
    return {
        "inside": ordered, "pts": [(float(r.lat), float(r.lon)) for r in ordered], "groups": groups,
        "daily": list(range(len(normal), len(ordered))), "overflow": overflow,
        "outside": [r for r in located if r not in inside],
        "pending": [r for r in rows if r not in located],
    }


def _day_plan(plan: dict, group: list[int], depot=None):
    """(paradas ordenadas, puntos del recorrido incluyendo el origen si hay) de un grupo mas los diarios."""
    group = group + plan["daily"]
    pts = [plan["pts"][i] for i in group]
    order = order_day(pts, depot) if pts else []
    daily = set(plan["daily"])
    stops = []
    for i in order:
        r = plan["inside"][group[i]]
        stops.append(GeneratedStop(
            cnpj="", nome_fantasia=r.nombre_negocio or r.nombre_cliente or "", cnae_label="Cliente",
            bairro=r.bairro or "", logradouro=r.direccion or "", lat=float(r.lat), lon=float(r.lon), cliente_id=str(r.id),
            diario=group[i] in daily,
        ))
    return stops, ([depot] if depot else []) + [pts[i] for i in order]


def _generate_from_clientes(
    user_id: str, city_name: str, max_lojas: int, day: int,
    cities: tuple[str, ...] | list[str] = ("Maringá",), avisos: list[str] | None = None,
) -> RouteGenerateResponse:
    """Ruta de un dia (lunes..viernes, agrupado por cercania) con los clientes del propio usuario; sin datos en logs."""
    rows = _load_clientes(user_id)
    plan = _plan_clientes(rows, len(DIAS_SEMANA), max(1, min(max_lojas, MARINGA_MAX_STOPS)), cities)
    groups = plan["groups"]
    stops, pts = _day_plan(plan, groups[day] if day < len(groups) else [])
    n_daily = len(plan["daily"])
    print(f"Generated clientes route for '{city_name}' day {day}: {len(plan['inside'])} candidates, {len(stops)} selected")
    return RouteGenerateResponse(
        city=city_name, total_candidates=len(plan["inside"]), selected=len(stops), stops=stops,
        distance_km=round(path_km(pts), 2), distance_kind="linea_recta", maps_links=maps_links(pts),
        fuera_de_maringa=[_listed(r) for r in plan["outside"]], pendientes=[_listed(r) for r in plan["pending"]],
        day=day, day_label=DIAS_SEMANA[day],
        day_counts=[len(g) + n_daily for g in groups] + [n_daily] * (len(DIAS_SEMANA) - len(groups)),
        sin_asignar=len(plan["overflow"]), avisos=avisos or [],
    )


@router.post("/api/routes/generate-week", response_model=WeekRouteResponse)
def generate_week(body: WeekRouteRequest, user_id: str = Depends(get_current_user_id)):
    """Semana completa de clientes de las ciudades pedidas (un solo clustering); el origen opcional no se guarda."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    cities, avisos = _check_cities(body.cities)
    rows = _load_clientes(user_id)
    plan = _plan_clientes(rows, body.days, body.max_stops, cities)
    depot = (body.start_lat, body.start_lon) if body.start_lat is not None and body.start_lon is not None else None
    days = []
    for n, group in enumerate(plan["groups"]):
        stops, pts = _day_plan(plan, group, depot)
        days.append(WeekDay(
            day=n, day_label=DIAS_SEMANA[n] if n < len(DIAS_SEMANA) else f"Dia {n + 1}", selected=len(stops), stops=stops,
            distance_km=round(path_km(pts), 2), distance_kind="linea_recta", maps_links=maps_links(pts),
        ))
    print(f"Generated week: {len(rows)} clientes, {len(days)} days, {len(plan['overflow'])} unassigned")
    return WeekRouteResponse(
        total_clientes=len(rows), days=days,
        fuera_de_maringa=[_listed(r) for r in plan["outside"]], pendientes=[_listed(r) for r in plan["pending"]],
        sin_asignar=[_listed(plan["inside"][i]) for i in plan["overflow"]], avisos=avisos,
    )


@router.post(
    "/api/routes/generate",
    response_model=RouteGenerateResponse,
    dependencies=[Depends(get_current_user_id)],
)
def generate_route(body: RouteGenerateRequest, user_id: str = Depends(get_current_user_id)):
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

    if body.cities or is_maringa(city_name):
        cities, avisos = _check_cities(body.cities or [city_name])
        return _generate_from_clientes(user_id, city_name, body.max_lojas, body.day or 0, cities, avisos)

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


def _city_sequence(start, groups: dict) -> list[str]:
    """Orden de ciudades con menos km: inicio -> centro de los clientes de cada ciudad, en cadena."""
    centers = {c: (sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g)) for c, g in groups.items()}

    def cost(seq):
        pts = [start] + [centers[c] for c in seq]
        return path_km(pts)

    names = sorted(groups)
    if len(names) <= MAX_PERMUT_CIUDADES:
        return list(min(permutations(names), key=cost))
    # shortcut: con mas ciudades, la mas cercana cada vez (no optima); subir el limite si hiciera falta
    seq, here = [], start
    while names:
        nxt = min(names, key=lambda c: haversine_km(*here, *centers[c]))
        seq.append(nxt)
        names.remove(nxt)
        here = centers[nxt]
    return seq


def _hhmm(minutes: float) -> str:
    m = round(minutes) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


@router.post("/api/routes/clientes-dia", response_model=ClientesDiaResponse)
def clientes_dia(body: ClientesDiaRequest, user_id: str = Depends(get_current_user_id)):
    """Ruta de hoy: diarios + atrasados + extras; ciudad por ciudad y vecino mas cercano dentro de cada una.

    Si no caben en max_paradas se descartan primero los extras, luego los diarios y por ultimo los atrasados
    (a igual prioridad, el mas lejano del inicio). Distancias en linea recta; nada se guarda.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if body.start_lat is not None:
        start = (body.start_lat, body.start_lon)
    else:
        name = canonical_city(body.start_city)
        if name is None:
            raise HTTPException(status_code=422, detail=f"Ciudad desconocida: {body.start_city[:60]}")
        city = next(c for c in CITIES if c.name == name)
        start = (city.lat, city.lon)

    extra = {str(i) for i in body.extra_ids}
    rows = _load_clientes(user_id)
    found = {str(r.id) for r in rows}
    wanted = [r for r in rows if r.visita_diaria or r.atrasado or str(r.id) in extra]
    nombre = lambda r: r.nombre_negocio or r.nombre_cliente or ""  # noqa: E731
    ciudad = lambda r: canonical_city(r.municipio) or r.municipio or ""  # noqa: E731
    listed = lambda r: ClienteDiaListed(id=str(r.id), nombre=nombre(r), ciudad=ciudad(r))  # noqa: E731
    located = [r for r in wanted if r.geocode_status == "ok" and r.lat is not None and r.lon is not None]
    pt = lambda r: (float(r.lat), float(r.lon))  # noqa: E731
    # menor = se queda: atrasado, luego diario, luego extra; a igual prioridad, el mas cercano al inicio
    located.sort(key=lambda r: (not r.atrasado, not r.visita_diaria, haversine_km(*start, *pt(r))))
    keep, dropped = located[:body.max_paradas], located[body.max_paradas:]

    groups: dict[str, list] = {}
    for r in keep:
        groups.setdefault(ciudad(r), []).append(r)
    ordered, here = [], start
    for c in _city_sequence(start, {c: [pt(r) for r in g] for c, g in groups.items()}):
        g = groups[c]
        idx = order_day([pt(r) for r in g], here)
        ordered += [g[i] for i in idx]
        here = pt(ordered[-1])

    h, m = map(int, body.hora_salida.split(":"))
    t, prev, stops = h * 60 + m, start, []
    for r in ordered:
        km = haversine_km(*prev, *pt(r))
        t += km / VELOCIDAD_KMH * 60
        stops.append(ClienteDiaStop(
            id=str(r.id), nombre=nombre(r), ciudad=ciudad(r), lat=pt(r)[0], lon=pt(r)[1],
            km_desde_anterior=round(km, 1), llegada=_hhmm(t), diario=bool(r.visita_diaria), atrasado=bool(r.atrasado),
        ))
        t += VISITA_MIN
        prev = pt(r)
    pts = [start] + [pt(r) for r in ordered]
    print(f"clientes-dia: {len(wanted)} pedidos, {len(stops)} en ruta, {len(dropped)} fuera por tope")
    return ClientesDiaResponse(
        hora_salida=body.hora_salida, hora_fin=_hhmm(t), distance_km=round(path_km(pts), 2), stops=stops,
        maps_links=maps_links(pts) if stops else [],
        sin_ubicacion=[listed(r) for r in wanted if r not in located],
        fuera_por_tope=[listed(r) for r in dropped],
        extra_no_encontrados=len(extra - found),
    )
