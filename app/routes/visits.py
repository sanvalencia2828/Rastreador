"""Street segments, visits, offline sync and street coverage."""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id, get_optional_user_id
from app.schemas.visit import VisitCreate, VisitSyncItem
from app.services.visit_metrics import _business_id_for_cnpj, recalculate_visit_interval

router = APIRouter()


# ------------------------------------------------------------------------------
# TRACKING ENDPOINTS
# ------------------------------------------------------------------------------
@router.get("/api/segments")
def get_street_segments(
    bbox: str, user_id: Optional[str] = Depends(get_optional_user_id)
):
    """
    Returns GeoJSON FeatureCollection of street segments within the specified bbox.
    Format: bbox=lng1,lat1,lng2,lat2
    Includes 'visited_by_user' boolean if a valid JWT token is provided.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="Bbox must have exactly 4 coordinates: lng1,lat1,lng2,lat2",
            )
        lng1, lat1, lng2, lat2 = map(float, parts)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Bbox coordinates must be valid numbers"
        )

    try:
        with db_engine.connect() as conn:
            if user_id:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           EXISTS(
                               SELECT 1 FROM visits v
                               WHERE v.logradouro = s.name AND v.user_id = :user_id
                           ) as visited_by_user,
                           (SELECT MAX(v.visited_at) FROM visits v
                              WHERE v.logradouro = s.name AND v.user_id = :user_id) as last_visited
                    FROM street_segments s
                    WHERE ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))
                """)
                params = {
                    "lng1": lng1,
                    "lat1": lat1,
                    "lng2": lng2,
                    "lat2": lat2,
                    "user_id": user_id,
                }
            else:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           FALSE as visited_by_user, NULL as last_visited
                    FROM street_segments s
                    WHERE ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))
                """)
                params = {"lng1": lng1, "lat1": lat1, "lng2": lng2, "lat2": lat2}

            result = conn.execute(query, params)
            features = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"])
                feature = {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "id": row_dict["id"],
                        "osm_id": row_dict["osm_id"],
                        "name": row_dict["name"] or "Calle sin nombre",
                        "length_m": (
                            float(row_dict["length_m"]) if row_dict["length_m"] else 0.0
                        ),
                        "visited_by_user": row_dict["visited_by_user"],
                        "notes": None,
                        "visited_at": (
                            row_dict["last_visited"].isoformat()
                            if row_dict["last_visited"]
                            else None
                        ),
                    },
                }
                features.append(feature)

            return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")


@router.get("/api/visits")
def get_user_visits(
    user_id: Optional[str] = None,
    bbox: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Returns the authenticated user's business-level visits (history).
    Optional bbox filter restricts results to a geographic envelope.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    target_user_id = user_id if user_id else current_user_id

    query_str = """
        SELECT v.id, v.cnpj, v.lat, v.lon, v.logradouro, v.bairro,
               v.notes, v.route_id, v.visited_at,
               ST_AsGeoJSON(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)) as geom_geojson
        FROM visits v
        WHERE v.user_id = :user_id
    """
    params: Dict[str, Any] = {"user_id": target_user_id}

    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) == 4:
                lng1, lat1, lng2, lat2 = map(float, parts)
                query_str += (
                    " AND ST_Intersects("
                    "ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326), "
                    "ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))"
                )
                params.update({"lng1": lng1, "lat1": lat1, "lng2": lng2, "lat2": lat2})
        except ValueError:
            pass

    try:
        with db_engine.connect() as conn:
            result = conn.execute(text(query_str), params)
            visits = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"])
                visits.append(
                    {
                        "id": row_dict["id"],
                        "cnpj": row_dict["cnpj"],
                        "lat": float(row_dict["lat"]),
                        "lon": float(row_dict["lon"]),
                        "logradouro": row_dict["logradouro"],
                        "bairro": row_dict["bairro"],
                        "notes": row_dict["notes"],
                        "route_id": str(row_dict["route_id"]) if row_dict["route_id"] else None,
                        "visited_at": row_dict["visited_at"].isoformat(),
                        "street_name": row_dict["logradouro"],
                        "geometry": geom,
                    }
                )
            return visits
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")


@router.post("/api/visits")
def create_visit(visit: VisitCreate, user_id: str = Depends(get_current_user_id)):
    """
    Record a new business/street visit. `visited_at` defaults to server NOW()
    if omitted. `street_coverage` is updated automatically via DB trigger.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    visited_at = None
    if visit.visited_at:
        try:
            visited_at = datetime.fromisoformat(visit.visited_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid visited_at timestamp format"
            )

    try:
        with db_engine.connect() as conn:
            query = text("""
                INSERT INTO visits (user_id, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
                VALUES (:user_id, :route_id, :cnpj, :lat, :lon, :logradouro, :bairro, :notes,
                        COALESCE(:visited_at, NOW()))
                RETURNING id
            """)
            result = conn.execute(
                query,
                {
                    "user_id": user_id,
                    "route_id": visit.route_id,
                    "cnpj": visit.cnpj,
                    "lat": visit.lat,
                    "lon": visit.lon,
                    "logradouro": visit.logradouro,
                    "bairro": visit.bairro,
                    "notes": visit.notes,
                    "visited_at": visited_at,
                },
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=500, detail="Database did not return the visit ID"
                )
            visit_id = row[0]

            business_id = _business_id_for_cnpj(conn, visit.cnpj)
            if business_id is not None:
                recalculate_visit_interval(conn, business_id)

            conn.commit()
            return {"status": "success", "visit_id": visit_id, "synced": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database insert failed: {e}"
        )


@router.post("/api/sync/visits")
def sync_visits(
    visits: List[VisitSyncItem], user_id: str = Depends(get_current_user_id)
):
    """
    Sync offline visits in batch. Each item becomes a new visit row (the new
    visits table records history rather than upserts). Exact-duplicate detection
    by (user_id, logradouro, lat, lon, visited_at) prevents repeat-sync issues.
    Returns the number of visits actually inserted.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    inserted_count = 0
    skipped_count = 0
    inserted_cnpjs = set()

    try:
        with db_engine.connect() as conn:
            for item in visits:
                try:
                    client_time = datetime.fromisoformat(
                        item.visited_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    skipped_count += 1
                    continue

                # Skip if an identical visit already exists (idempotent re-sync)
                dup_check = text("""
                    SELECT 1 FROM visits
                     WHERE user_id = :user_id
                       AND logradouro = :logradouro
                       AND lat = :lat
                       AND lon = :lon
                       AND visited_at = :visited_at
                    LIMIT 1
                """)
                existing = conn.execute(
                    dup_check,
                    {
                        "user_id": user_id,
                        "logradouro": item.logradouro,
                        "lat": item.lat,
                        "lon": item.lon,
                        "visited_at": client_time,
                    },
                ).fetchone()
                if existing:
                    skipped_count += 1
                    continue

                insert_query = text("""
                    INSERT INTO visits
                        (user_id, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
                    VALUES
                        (:user_id, :route_id, :cnpj, :lat, :lon, :logradouro, :bairro, :notes, :visited_at)
                """)
                conn.execute(
                    insert_query,
                    {
                        "user_id": user_id,
                        "route_id": item.route_id,
                        "cnpj": item.cnpj,
                        "lat": item.lat,
                        "lon": item.lon,
                        "logradouro": item.logradouro,
                        "bairro": item.bairro,
                        "notes": item.notes,
                        "visited_at": client_time,
                    },
                )
                inserted_count += 1
                if item.cnpj:
                    inserted_cnpjs.add(item.cnpj)

            for cnpj in inserted_cnpjs:
                business_id = _business_id_for_cnpj(conn, cnpj)
                if business_id is not None:
                    recalculate_visit_interval(conn, business_id)

            conn.commit()
            return {"synced": inserted_count, "skipped": skipped_count, "conflicts": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync process failed: {e}")


# ==============================================================================
# STREET COVERAGE — aggregated per-street visit stats
# ==============================================================================
@router.get("/api/street-coverage")
def get_street_coverage(
    municipio: Optional[str] = None,
    only_unvisited: bool = False,
    limit: int = 200,
):
    """
    Returns aggregated street coverage rows ordered by least-recently-visited
    first (so the worker can pick the next street to walk).

    - `municipio` filters by municipality (default: all).
    - `only_unvisited=true` returns only streets with `last_visited IS NULL`.
    - `limit` caps the number of rows returned (default 200).
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    query_str = """
        SELECT id, logradouro, bairro, municipio, state, last_visited,
               visit_count, total_businesses, covered_businesses,
               ST_AsGeoJSON(geom) as geom_geojson, updated_at
        FROM street_coverage
        WHERE 1=1
    """
    params: Dict[str, Any] = {}
    if municipio:
        query_str += " AND municipio = :municipio"
        params["municipio"] = municipio
    if only_unvisited:
        query_str += " AND last_visited IS NULL"
    query_str += " ORDER BY last_visited ASC NULLS FIRST, covered_businesses ASC LIMIT :limit"
    params["limit"] = limit

    try:
        with db_engine.connect() as conn:
            result = conn.execute(text(query_str), params)
            rows = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"]) if row_dict["geom_geojson"] else None
                rows.append(
                    {
                        "id": row_dict["id"],
                        "logradouro": row_dict["logradouro"],
                        "bairro": row_dict["bairro"],
                        "municipio": row_dict["municipio"],
                        "state": row_dict["state"],
                        "last_visited": (
                            row_dict["last_visited"].isoformat()
                            if row_dict["last_visited"]
                            else None
                        ),
                        "visit_count": row_dict["visit_count"],
                        "total_businesses": row_dict["total_businesses"],
                        "covered_businesses": row_dict["covered_businesses"],
                        "geometry": geom,
                        "updated_at": (
                            row_dict["updated_at"].isoformat()
                            if row_dict["updated_at"]
                            else None
                        ),
                    }
                )
            return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Coverage query failed: {e}")
