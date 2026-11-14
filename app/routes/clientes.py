"""Private per-user customer list."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id

router = APIRouter()

_LIST_SQL = text("""
    SELECT id, external_id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, cep,
           lat, lon, geocode_status, geocode_source, nota
    FROM clientes
    WHERE user_id = :user_id
    ORDER BY nombre_negocio, id
    LIMIT :limit
""")


@router.get("/api/clientes")
def list_clientes(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    user_id: str = Depends(get_current_user_id),
):
    """The caller's own customers only (never another user's)."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(_LIST_SQL, {"user_id": user_id, "limit": limit}).fetchall()
    except Exception:  # driver messages embed bound parameters and row data: fixed text only
        raise HTTPException(status_code=500, detail="Error al consultar clientes") from None
    response.headers["Cache-Control"] = "no-store"
    out = []
    for row in rows:
        item = dict(row._mapping)
        item["id"] = str(item["id"])
        for key in ("lat", "lon"):
            if item[key] is not None:
                item[key] = float(item[key])
        out.append(item)
    return out
