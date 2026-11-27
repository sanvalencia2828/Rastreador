"""Private per-user customer list."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.cliente import ClienteCreate, ClientePatch
from cities import nearest_city

router = APIRouter()

_LIST_SQL = text("""
    SELECT id, external_id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, cep,
           lat, lon, geocode_status, geocode_source, nota, visita_diaria, atrasado
    FROM clientes
    WHERE user_id = :user_id
    ORDER BY nombre_negocio, id
    LIMIT :limit
""")


_COLUMNS = ("id, external_id, nombre_cliente, nombre_negocio, direccion, bairro, municipio, cep, "
            "lat, lon, geocode_status, geocode_source, nota, visita_diaria, atrasado")

_INSERT_SQL = text(f"""
    INSERT INTO clientes (user_id, external_id, nombre_cliente, nombre_negocio, direccion, bairro,
                          municipio, lat, lon, geocode_status, geocode_source, nota, visita_diaria)
    VALUES (:user_id, :external_id, :nombre_cliente, :nombre_negocio, :direccion, :bairro,
            :municipio, :lat, :lon, :geocode_status, :geocode_source, :nota, :visita_diaria)
    RETURNING {_COLUMNS}
""")

# Only the owner's row matches; the id arrives already validated as a UUID. Coordinates typed in the app are
# 'manual', so reloading the CSV never overwrites them (seed_clientes skips manual rows).
_PATCH_SQL = text(f"""
    UPDATE clientes SET municipio = COALESCE(:municipio, municipio),
                        visita_diaria = COALESCE(:visita_diaria, visita_diaria),
                        atrasado = COALESCE(:atrasado, atrasado),
                        nombre_negocio = COALESCE(:nombre_negocio, nombre_negocio),
                        nota = CASE WHEN CAST(:set_nota AS BOOLEAN) THEN CAST(:nota AS TEXT) ELSE nota END,
                        lat = COALESCE(CAST(:lat AS NUMERIC), lat),
                        lon = COALESCE(CAST(:lon AS NUMERIC), lon),
                        geocode_status = CASE WHEN CAST(:lat AS NUMERIC) IS NULL THEN geocode_status ELSE 'ok' END,
                        geocode_source = CASE WHEN CAST(:lat AS NUMERIC) IS NULL THEN geocode_source ELSE 'manual' END,
                        updated_at = NOW()
    WHERE id = :id AND user_id = :user_id
    RETURNING {_COLUMNS}
""")
MAX_CITY_KM = 40


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
    municipio = body.municipio
    if municipio is None:
        municipio = nearest_city(body.lat, body.lon, MAX_CITY_KM) if located else "Maringá"
        if municipio is None:
            raise HTTPException(status_code=422, detail=f"Ninguna ciudad conocida a menos de {MAX_CITY_KM} km de esa ubicación")
    params = {
        **body.model_dump(),
        "municipio": municipio,
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


@router.patch("/api/clientes/{cliente_id}")
def patch_cliente(
    cliente_id: uuid.UUID,
    body: ClientePatch,
    response: Response,
    user_id: str = Depends(get_current_user_id),
):
    """Edit one of the caller's customers (only the fields sent); another user's id is a 404.
    New lat/lon without municipio picks the nearest known city (if any within MAX_CITY_KM)."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    params = {**body.model_dump(), "set_nota": "nota" in body.model_fields_set,
              "id": str(cliente_id), "user_id": user_id}
    params["nota"] = params["nota"] or None
    if body.lat is not None and body.municipio is None:  # lejos de toda ciudad conocida: se queda la que tenía
        params["municipio"] = nearest_city(body.lat, body.lon, MAX_CITY_KM)
    try:
        with db_engine.begin() as conn:
            row = conn.execute(_PATCH_SQL, params).fetchone()
    except Exception:  # driver messages embed bound parameters and row data: fixed text only
        raise HTTPException(status_code=500, detail="Error al guardar el cliente") from None
    if row is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    response.headers["Cache-Control"] = "no-store"
    return _serialize(row)
