"""Private per-user customer list."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.cliente import ClienteCreate

router = APIRouter()

_LIST_SQL = text("""
    SELECT id, external_id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, cep,
           lat, lon, geocode_status, geocode_source, nota
    FROM clientes
    WHERE user_id = :user_id
    ORDER BY nombre_negocio, id
    LIMIT :limit
""")


_COLUMNS = ("id, external_id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, cep, "
            "lat, lon, geocode_status, geocode_source, nota")

# municipio is fixed to Maringá (the only city this form serves): Gerar Semana drops other cities.
_INSERT_SQL = text(f"""
    INSERT INTO clientes (user_id, external_id, nombre_cliente, nombre_negocio, direccion, bairro,
                          municipio, lat, lon, geocode_status, geocode_source, nota)
    VALUES (:user_id, :external_id, :nombre_cliente, :nombre_negocio, :direccion, :bairro,
            'Maringá', :lat, :lon, :geocode_status, :geocode_source, :nota)
    RETURNING {_COLUMNS}
""")


def _serialize(row) -> dict:
    item = dict(row._mapping)
    item["id"] = str(item["id"])
    for key in ("lat", "lon"):
        if item[key] is not None:
            item[key] = float(item[key])
    return item


@router.post("/api/clientes", status_code=201)
def create_cliente(
    body: ClienteCreate,
    response: Response,
    user_id: str = Depends(get_current_user_id),
):
    """Create a customer owned by the caller. With lat/lon it is located; otherwise it stays 'pendiente'."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    located = body.lat is not None
    params = {
        **body.model_dump(),
        "user_id": user_id,
        "external_id": str(uuid.uuid4()),
        "geocode_status": "ok" if located else "pendiente",
        "geocode_source": "manual" if located else None,
    }
    try:
        with db_engine.begin() as conn:
            row = conn.execute(_INSERT_SQL, params).fetchone()
    except Exception:  # driver messages embed bound parameters and row data: fixed text only
        raise HTTPException(status_code=500, detail="Error al guardar el cliente") from None
    response.headers["Cache-Control"] = "no-store"
    return _serialize(row)


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
    return [_serialize(row) for row in rows]
