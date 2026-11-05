"""Calles cercanas a los clientes del usuario (solo Maringá) con comercios activos y tiempo estimado.

Datos por calle, sin nombres de negocios, sin teléfono ni correo, sin listar MEI. Las coordenadas del cliente
se usan solo en la consulta local: ni se devuelven ni se envían a ningún servidor externo.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.services import street_time as T
from app.services.streets import _plain

router = APIRouter()

ATRIBUCION = "© OpenStreetMap contributors (ODbL); comercios: dato público de la Receita Federal (volcado 2026-09)"

_CLIENTES_SQL = text("""
    SELECT id, external_id, municipio, lat, lon
    FROM clientes
    WHERE user_id = :user_id
    ORDER BY nombre_negocio, id
    LIMIT :limit
""")

_NEARBY_SQL = text("""
    WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) AS g)
    SELECT c.id, c.street_key, c.osm_key, c.tipo, c.nombre, c.n_comercios_activos, c.numero_min, c.numero_max,
           c.ceps, c.length_m, c.pareado_pct, c.estado,
           MIN(ST_Distance(s.geom::geography, p.g::geography)) AS dist_m
    FROM p
    JOIN street_segments s ON s.municipio = 'MARINGA' AND s.geom && ST_Expand(p.g, :deg)
    JOIN street_catalog c ON c.municipio = s.municipio AND c.osm_key = s.street_key
    WHERE ST_DWithin(s.geom::geography, p.g::geography, :radio)
    GROUP BY c.id
""")

_REAL_SQL = text("""
    SELECT street_key, count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds) AS med
    FROM street_time_log
    WHERE user_id = :user_id AND municipio = 'MARINGA' AND street_key = ANY(:keys)
    GROUP BY street_key
""")


def real_times(conn, user_id: str, keys: List[str]) -> Dict[str, tuple]:
    """{street_key: (n_registros, mediana_segundos)} del propio usuario."""
    if not keys:
        return {}
    rows = conn.execute(_REAL_SQL, {"user_id": user_id, "keys": keys}).fetchall()
    return {r[0]: (int(r[1]), float(r[2])) for r in rows}


def _cliente_status(municipio: Optional[str], lat, lon) -> Optional[Dict[str, str]]:
    """None = se pueden buscar calles; si no, el motivo explícito (nunca una lista vacía muda)."""
    if lat is None or lon is None:
        return {"calles_estado": "sin_coordenadas", "calles_motivo": "el cliente no tiene coordenadas"}
    if _plain(municipio or "") != "MARINGA":
        return {
            "calles_estado": "sin_datos_de_calles",
            "calles_motivo": f"municipio {municipio or 'no informado'!r}: solo hay calles de Maringá (IBGE 4115200)",
        }
    return None


@router.get("/api/clientes/streets-nearby")
def streets_nearby(
    response: Response,
    radio_m: int = Query(300, ge=50, le=1000, description="radio a pie desde el cliente (m)"),
    velocidad_kmh: float = Query(T.WALK_SPEED_KMH, gt=0, le=10),
    min_por_local: float = Query(T.MIN_PER_LOCAL, ge=0, le=60),
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """Calles con comercios activos a <= radio_m de cada cliente del usuario, con tiempo estimado (SUPUESTOS)."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    clientes_out: List[Dict[str, Any]] = []
    unique = set()
    try:
        with db_engine.connect() as conn:
            clientes = conn.execute(_CLIENTES_SQL, {"user_id": user_id, "limit": limit}).fetchall()
            per_client = []
            for c in clientes:
                status = _cliente_status(c.municipio, c.lat, c.lon)
                found = []
                if status is None:
                    found = [dict(r._mapping) for r in conn.execute(
                        _NEARBY_SQL, {"lat": float(c.lat), "lon": float(c.lon), "radio": radio_m, "deg": radio_m / 90000.0})]
                per_client.append((c, status, T.merge_catalog_rows(found) if found else []))
            keys = sorted({k for _, _, ms in per_client for m in ms for k in m["street_keys"]})
            real = real_times(conn, user_id, keys)
    except Exception:  # driver messages embed parameters (coordinates): fixed text only
        raise HTTPException(status_code=500, detail="Error al consultar calles") from None
    for c, status, merged in per_client:
        item: Dict[str, Any] = {"id": str(c.id), "external_id": c.external_id}
        if status:
            item.update(status, calles=None)
        else:
            views = sorted((T.street_view(m, velocidad_kmh, min_por_local, real) for m in merged),
                           key=lambda v: v["distancia_m"])
            unique.update(m["osm_key"] for m in merged)
            item.update(calles_estado="ok" if views else "sin_calles_cercanas", calles=views)
        clientes_out.append(item)
    response.headers["Cache-Control"] = "no-store"
    return {
        "radio_m": radio_m,
        "supuestos": T.supuestos(velocidad_kmh, min_por_local),
        "calles_unicas": len(unique),
        "clientes": clientes_out,
        "atribucion": ATRIBUCION,
    }
