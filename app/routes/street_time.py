"""Tiempo por calle del propio usuario: estimado frente a real."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.services import street_time as T

router = APIRouter()

# Real minutes pooled per OSM street (every dump spelling of the same street counts together).
_REAL_SQL = text("""
    SELECT c.osm_key, count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY l.seconds) AS med
    FROM street_time_log l
    JOIN street_catalog c ON c.municipio = l.municipio AND c.street_key = l.street_key
    WHERE l.user_id = :user_id AND l.municipio = 'MARINGA'
    GROUP BY c.osm_key
    ORDER BY n DESC, c.osm_key
    LIMIT :limit
""")

_CATALOG_SQL = text("""
    SELECT id, street_key, osm_key, tipo, nombre, n_comercios_activos, numero_min, numero_max, ceps,
           length_m, pareado_pct, estado, 0.0::float8 AS dist_m
    FROM street_catalog
    WHERE municipio = 'MARINGA' AND osm_key = ANY(:keys)
""")


@router.get("/api/street-time")
def street_time(
    response: Response,
    velocidad_kmh: float = Query(T.WALK_SPEED_KMH, gt=0, le=10),
    min_por_local: float = Query(T.MIN_PER_LOCAL, ge=0, le=60),
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """Por calle con registros propios: mediana real, estimado (SUPUESTOS) y cuál se usa (real desde N_MIN registros)."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            logged = conn.execute(_REAL_SQL, {"user_id": user_id, "limit": limit}).fetchall()
            real = {r.osm_key: (int(r.n), float(r.med)) for r in logged}
            catalog = [dict(r._mapping) for r in conn.execute(_CATALOG_SQL, {"keys": list(real)})]
    except Exception as e:  # driver messages embed parameters: class name only
        print(f"street-time failed ({type(e).__name__})")
        raise HTTPException(status_code=500, detail="Error al consultar tiempos") from None
    merged = {m["osm_key"]: m for m in T.merge_catalog_rows(catalog)}
    calles = []
    for osm_key in real:  # already ordered by number of records
        if osm_key not in merged:
            continue
        v = T.street_view(merged[osm_key], velocidad_kmh, min_por_local, real)
        item = {
            "calle": v["calle"], "n_real": v["n_real"], "tiempo_real_min": v["tiempo_real_min"],
            "tiempo_estimado_min": v["tiempo_estimado_min"], "tiempo_usado": v["tiempo_usado"],
            "diferencia_min": None if v["tiempo_estimado_min"] is None else round(v["tiempo_real_min"] - v["tiempo_estimado_min"], 1),
        }
        if "tiempo_motivo" in v:
            item["tiempo_motivo"] = v["tiempo_motivo"]
        calles.append(item)
    response.headers["Cache-Control"] = "no-store"
    return {
        "supuestos": T.supuestos(velocidad_kmh, min_por_local),
        "n_min_para_usar_real": T.N_MIN_REAL,
        "aproximacion_real": "derivado de visited_at: incluye desplazamiento y pausas; se descartan intervalos de más de 90 min",
        "calles": calles,
    }
