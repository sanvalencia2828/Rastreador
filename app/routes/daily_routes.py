"""Daily routes CRUD."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.planned_route import DailyRouteCreate, DailyRouteUpdate

router = APIRouter()


# ==============================================================================
# DAILY ROUTES - CRUD + BUSINESSES NEARBY
# ==============================================================================


@router.get("/api/daily-routes")
def list_daily_routes(user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, day_of_week, streets,
                           created_at, updated_at
                    FROM daily_routes
                    WHERE user_id = :user_id
                    ORDER BY day_of_week NULLS LAST, created_at
                """),
                {"user_id": user_id},
            )
            routes = []
            for row in result:
                row_dict = dict(row._mapping)
                routes.append({
                    "id": str(row_dict["id"]),
                    "name": row_dict["name"],
                    "day_of_week": row_dict["day_of_week"],
                    "streets": row_dict["streets"] or [],
                    "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                    "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
                })
            return routes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list routes: {e}")


@router.post("/api/daily-routes")
def create_daily_route(
    route: DailyRouteCreate, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO daily_routes (user_id, name, day_of_week, streets)
                    VALUES (:user_id, :name, :day_of_week, :streets)
                    RETURNING id, name, day_of_week, streets, created_at
                """),
                {
                    "user_id": user_id,
                    "name": route.name.strip(),
                    "day_of_week": route.day_of_week or None,
                    "streets": route.streets,
                },
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Route creation failed")
            row_dict = dict(row._mapping)
            conn.commit()
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {e}")


@router.get("/api/daily-routes/{route_id}")
def get_daily_route(
    route_id: str, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, day_of_week, streets, created_at, updated_at
                    FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"route_id": route_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            row_dict = dict(row._mapping)
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get route: {e}")


@router.put("/api/daily-routes/{route_id}")
def update_daily_route(
    route_id: str,
    update: DailyRouteUpdate,
    user_id: str = Depends(get_current_user_id),
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            # Build dynamic SET clause
            set_parts = []
            params: Dict[str, Any] = {"route_id": route_id, "user_id": user_id}

            if update.name is not None:
                set_parts.append("name = :name")
                params["name"] = update.name.strip()
            if update.day_of_week is not None:
                set_parts.append("day_of_week = :day_of_week")
                params["day_of_week"] = update.day_of_week or None
            if update.streets is not None:
                set_parts.append("streets = :streets")
                params["streets"] = update.streets

            if not set_parts:
                raise HTTPException(status_code=400, detail="No fields to update")

            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            set_clause = ", ".join(set_parts)

            result = conn.execute(
                text(f"""
                    UPDATE daily_routes
                    SET {set_clause}
                    WHERE id = :route_id AND user_id = :user_id
                    RETURNING id, name, day_of_week, streets, updated_at
                """),
                params,
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            row_dict = dict(row._mapping)
            conn.commit()
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update route: {e}")


@router.delete("/api/daily-routes/{route_id}")
def delete_daily_route(
    route_id: str, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    DELETE FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                    RETURNING id
                """),
                {"route_id": route_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            conn.commit()
            return {"status": "deleted", "route_id": route_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete route: {e}")


@router.get("/api/daily-routes/{route_id}/businesses")
def get_route_businesses(
    route_id: str,
    user_id: str = Depends(get_current_user_id),
    radius: int = 0,
    limit: int = 200,
):
    """
    Returns businesses (from estabelecimentos) whose logradouro matches
    any street in the route. If radius > 0 and street_segments have PostGIS
    geometries, also returns businesses within radius meters of the route.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    # 1. Fetch the route's streets
    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT streets FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"route_id": route_id, "user_id": user_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            streets = row[0] or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch route: {e}")

    if not streets:
        return {
            "type": "FeatureCollection",
            "features": [],
            "metadata": {"route_id": route_id, "total": 0},
        }

    # 2. Search estabelecimentos by street name
    features = []
    try:
        with db_engine.connect() as conn:
            # Build ILIKE conditions for each street
            conditions = " OR ".join(
                f"logradouro ILIKE :street_{i}" for i in range(len(streets))
            )
            params = {}
            for i, s in enumerate(streets):
                params[f"street_{i}"] = f"%{s.strip()}%"

            query = text(f"""
                SELECT
                    cnpj_completo, nome_fantasia, business_type,
                    cnae_fiscal, logradouro, numero, bairro, municipio,
                    latitude, longitude, porte_empresa
                FROM estabelecimentos
                WHERE ({conditions})
                  AND situacao_cadastral = 2
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY nome_fantasia
                LIMIT :limit
            """)
            params["limit"] = limit

            result = conn.execute(query, params)
            for row in result:
                row_dict = dict(row._mapping)
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            float(row_dict["longitude"]),
                            float(row_dict["latitude"]),
                        ],
                    },
                    "properties": {
                        "cnpj": row_dict["cnpj_completo"],
                        "nome_fantasia": row_dict["nome_fantasia"] or "",
                        "business_type": row_dict["business_type"] or "",
                        "cnae": str(row_dict["cnae_fiscal"] or ""),
                        "logradouro": row_dict["logradouro"] or "",
                        "numero": row_dict["numero"] or "",
                        "bairro": row_dict["bairro"] or "",
                        "municipio": row_dict["municipio"] or "",
                        "porte_empresa": str(row_dict["porte_empresa"] or ""),
                    },
                })
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search businesses: {e}"
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "route_id": route_id,
            "routes": streets,
            "total": len(features),
        },
    }
