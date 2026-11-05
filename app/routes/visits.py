"""Street segments, visits, offline sync and street coverage."""

import json
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from uuid import UUID

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
    bbox: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
):
    """
    Returns the authenticated user's business-level visits (history).
    Optional bbox filter restricts results to a geographic envelope.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    query_str = """
        SELECT v.id, v.cnpj, v.lat, v.lon, v.logradouro, v.bairro,
               v.notes, v.route_id, v.visited_at,
               ST_AsGeoJSON(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)) as geom_geojson
        FROM visits v
        WHERE v.user_id = :user_id
    """
    params: Dict[str, Any] = {"user_id": user_id}

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


# Inserta un lote completo en una sola sentencia. La deduplicación se hace en SQL:
#   * dentro del lote (DISTINCT ON por la clave de la visita) y
#   * contra lo ya guardado (NOT EXISTS sobre visits).
# lat/lon se redondean a 7 decimales como NUMERIC(10,7) de la tabla, porque comparar el
# float del cliente con el valor almacenado no coincidía y los re-sync se duplicaban.
SYNC_VISITS_SQL = text("""
    WITH batch AS (
        SELECT *
          FROM unnest(
                   CAST(:ords AS integer[]),
                   CAST(:route_ids AS uuid[]),
                   CAST(:cnpjs AS varchar[]),
                   CAST(:lats AS numeric[]),
                   CAST(:lons AS numeric[]),
                   CAST(:logradouros AS text[]),
                   CAST(:bairros AS text[]),
                   CAST(:notes AS text[]),
                   CAST(:visited_ats AS timestamptz[])
               ) AS b(ord, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
    ),
    normalized AS (
        SELECT ord, route_id, cnpj,
               ROUND(lat, 7) AS lat, ROUND(lon, 7) AS lon,
               logradouro, bairro, notes, visited_at
          FROM batch
    ),
    deduped AS (
        SELECT DISTINCT ON (logradouro, lat, lon, visited_at) *
          FROM normalized
         ORDER BY logradouro, lat, lon, visited_at, ord
    )
    INSERT INTO visits (user_id, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
    SELECT CAST(:user_id AS uuid), d.route_id, d.cnpj, d.lat, d.lon, d.logradouro, d.bairro, d.notes, d.visited_at
      FROM deduped d
     WHERE NOT EXISTS (
               SELECT 1 FROM visits v
                WHERE v.user_id = CAST(:user_id AS uuid)
                  AND v.logradouro = d.logradouro
                  AND v.lat = d.lat
                  AND v.lon = d.lon
                  AND v.visited_at = d.visited_at
           )
    RETURNING cnpj
""")


def _parse_sync_batch(visits: List[VisitSyncItem]) -> tuple[Dict[str, list], List[Dict[str, Any]]]:
    """Valida cada ítem y arma los arrays columnares para SYNC_VISITS_SQL.

    Devuelve (columnas, errores). Un ítem inválido no aborta el lote: se informa en
    `errors` con su índice y el resto se sincroniza.
    """
    columns: Dict[str, list] = {
        key: []
        for key in ("ords", "route_ids", "cnpjs", "lats", "lons", "logradouros", "bairros", "notes", "visited_ats")
    }
    errors: List[Dict[str, Any]] = []
    for index, item in enumerate(visits):
        try:
            visited_at = datetime.fromisoformat(item.visited_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append({"index": index, "error": f"visited_at inválido: {item.visited_at!r}"})
            continue
        if not (-90 <= item.lat <= 90 and -180 <= item.lon <= 180):
            errors.append({"index": index, "error": "lat/lon fuera de rango"})
            continue
        if not item.logradouro or not item.logradouro.strip():
            errors.append({"index": index, "error": "logradouro vacío"})
            continue
        route_id = item.route_id or None
        if route_id is not None:
            try:
                route_id = str(UUID(str(route_id)))
            except ValueError:
                errors.append({"index": index, "error": f"route_id no es un UUID: {item.route_id!r}"})
                continue
        columns["ords"].append(index)
        columns["route_ids"].append(route_id)
        columns["cnpjs"].append(item.cnpj or None)
        columns["lats"].append(Decimal(repr(item.lat)))
        columns["lons"].append(Decimal(repr(item.lon)))
        columns["logradouros"].append(item.logradouro)
        columns["bairros"].append(item.bairro)
        columns["notes"].append(item.notes)
        columns["visited_ats"].append(visited_at)
    return columns, errors


@router.post("/api/sync/visits")
def sync_visits(
    visits: List[VisitSyncItem], user_id: str = Depends(get_current_user_id)
):
    """
    Sync offline visits in batch. Each item becomes a new visit row (the visits
    table records history rather than upserts).

    Idempotente: una visita con la misma (user_id, logradouro, lat, lon, visited_at)
    que otra del lote o de la base no se vuelve a insertar. Todo el lote se escribe
    con una sola sentencia, y las métricas se recalculan una vez por CNPJ afectado.

    Respuesta: {"received", "synced", "skipped", "duplicates",
                "errors": [{index, error}], "warnings": [{index, warning}], "conflicts": []}
    `skipped` = duplicados + inválidos.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    columns, errors = _parse_sync_batch(visits)
    valid_count = len(columns["ords"])
    inserted_count = 0

    warnings: List[Dict[str, Any]] = []

    try:
        with db_engine.begin() as conn:
            if valid_count:
                # Una sola consulta para las rutas referenciadas: si una ya no existe, la
                # visita se guarda igual (es dato de campo) pero sin ruta, en vez de que la
                # FK haga fallar todo el lote.
                referenced = sorted({r for r in columns["route_ids"] if r})
                if referenced:
                    existing = {
                        str(row[0])
                        for row in conn.execute(
                            text("SELECT id FROM routes WHERE id = ANY(CAST(:ids AS uuid[]))"),
                            {"ids": referenced},
                        )
                    }
                    for pos, route_id in enumerate(columns["route_ids"]):
                        if route_id and route_id not in existing:
                            columns["route_ids"][pos] = None
                            warnings.append(
                                {"index": columns["ords"][pos], "warning": f"route_id {route_id} no existe; se guardó sin ruta"}
                            )
                inserted = conn.execute(SYNC_VISITS_SQL, {**columns, "user_id": user_id}).fetchall()
                inserted_count = len(inserted)
                inserted_cnpjs = sorted({row[0] for row in inserted if row[0]})
                for cnpj in inserted_cnpjs:
                    business_id = _business_id_for_cnpj(conn, cnpj)
                    if business_id is not None:
                        recalculate_visit_interval(conn, business_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync process failed: {e}")

    return {
        "received": len(visits),
        "synced": inserted_count,
        "skipped": len(visits) - inserted_count,
        "duplicates": valid_count - inserted_count,
        "errors": errors,
        "warnings": warnings,
        "conflicts": [],
    }


# ==============================================================================
# STREET COVERAGE — aggregated per-street visit stats
# ==============================================================================
@router.get("/api/street-coverage")
def get_street_coverage(
    municipio: Optional[str] = None,
    only_unvisited: bool = False,
    limit: int = 200,
    user_id: str = Depends(get_current_user_id),
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
    params["limit"] = max(1, min(limit, 500))

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
