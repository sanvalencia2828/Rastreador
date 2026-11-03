"""Cities and per-city routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.city import CityCreate
from app.schemas.planned_route import RouteCreate

router = APIRouter()


@router.get("/api/cities")
def get_cities():
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("SELECT id, name, state, lat, lon FROM cities ORDER BY id")).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch cities: {e}")


@router.post("/api/cities", dependencies=[Depends(get_current_user_id)])
def create_city(city: CityCreate):
    """Crea una ciudad idempotentemente (ON CONFLICT DO NOTHING)."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not city.name.strip():
        raise HTTPException(status_code=400, detail="City name is required")
    try:
        with db_engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO cities (name, state, lat, lon)
                    VALUES (:name, :state, :lat, :lon)
                    ON CONFLICT (name, state) DO NOTHING
                """),
                {
                    "name": city.name.strip(),
                    "state": city.state.strip().upper() or "PR",
                    "lat": city.lat,
                    "lon": city.lon,
                },
            )
            row = conn.execute(
                text("SELECT id, name, state, lat, lon FROM cities WHERE name = :name AND state = :state"),
                {"name": city.name.strip(), "state": city.state.strip().upper() or "PR"},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="City creation failed")
            return dict(row._mapping)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create city: {e}")

@router.get("/api/cities/{city_id}/stats")
def get_city_stats(city_id: int):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, name, state, lat, lon FROM cities WHERE id = :city_id"),
                {"city_id": city_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="City not found")
            city = dict(row._mapping)
            count = conn.execute(
                text("SELECT COUNT(*) FROM estabelecimentos WHERE UPPER(municipio) = UPPER(:city_name) AND situacao_cadastral = 2 AND geom IS NOT NULL"),
                {"city_name": city["name"]},
            ).scalar()
            city["total_businesses"] = count
            return city
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch city stats: {e}")


# ==============================================================================
# CITY ROUTES CRUD
# ==============================================================================

@router.get("/api/cities/{city_id}/routes")
def list_city_routes(city_id: int, user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, city_id, created_at
                    FROM routes
                    WHERE city_id = :city_id AND user_id = :user_id
                    ORDER BY created_at DESC, name
                """),
                {"city_id": city_id, "user_id": user_id},
            )
            routes = []
            for row in result:
                row_dict = dict(row._mapping)
                stops_result = conn.execute(
                    text("""
                        SELECT id, stop_order, address, lat, lon, cep, display_name
                        FROM route_stops
                        WHERE route_id = :route_id
                        ORDER BY stop_order
                    """),
                    {"route_id": row_dict["id"]},
                )
                stops = [
                    {
                        "id": str(stop_row[0]),
                        "stop_order": stop_row[1],
                        "address": stop_row[2],
                        "lat": float(stop_row[3]),
                        "lon": float(stop_row[4]),
                        "cep": stop_row[5],
                        "display_name": stop_row[6],
                    }
                    for stop_row in stops_result
                ]
                routes.append(
                    {
                        "id": str(row_dict["id"]),
                        "name": row_dict["name"],
                        "city_id": row_dict["city_id"],
                        "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                        "stops": stops,
                    }
                )
            return routes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list city routes: {e}")


@router.post("/api/cities/{city_id}/routes")
def create_city_route(city_id: int, route: RouteCreate, user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    if route.city_id != city_id:
        raise HTTPException(status_code=400, detail="City mismatch")
    if not route.stops:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    try:
        with db_engine.connect() as conn:
            route_result = conn.execute(
                text("""
                    INSERT INTO routes (user_id, city_id, name)
                    VALUES (:user_id, :city_id, :name)
                    RETURNING id, created_at
                """),
                {"user_id": user_id, "city_id": city_id, "name": route.name.strip()},
            )
            created_row = route_result.fetchone()
            if not created_row:
                raise HTTPException(status_code=500, detail="Route creation failed")
            route_id = created_row[0]
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
                "id": str(route_id),
                "name": route.name.strip(),
                "city_id": city_id,
                "created_at": created_row[1].isoformat() if created_row[1] else None,
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
        raise HTTPException(status_code=500, detail=f"Failed to create city route: {e}")
