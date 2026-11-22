"""Ruta de tarjetas: registro de entregas y resumen. Todo filtrado por el usuario del token."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.tarjeta import EntregaCreate
from app.services import tarjetas

router = APIRouter()

# Una fila por usuario, negocio y día: repetir el envío (reintento sin red) solo actualiza la del día.
_UPSERT_SQL = text("""
    INSERT INTO tarjeta_entregas (user_id, cnpj_completo, resultado, nota, lat, lon)
    SELECT CAST(:user_id AS uuid), e.cnpj_completo, :resultado, :nota, :lat, :lon
      FROM estabelecimentos e
     WHERE e.cnpj_completo = :cnpj
    ON CONFLICT (user_id, cnpj_completo, fecha) DO UPDATE
       SET resultado = EXCLUDED.resultado, nota = EXCLUDED.nota, lat = EXCLUDED.lat, lon = EXCLUDED.lon
    RETURNING id, fecha
""")

# Solo paradas de rutas del propio usuario.
_MARK_STOP_SQL = text("""
    UPDATE route_stops rs
       SET visited = TRUE, visited_at = NOW()
      FROM routes r, estabelecimentos e
     WHERE rs.route_id = r.id
       AND r.id = CAST(:route_id AS uuid)
       AND r.user_id = CAST(:user_id AS uuid)
       AND e.id = rs.business_id
       AND e.cnpj_completo = :cnpj
""")


def _db():
    if not db_engine:
        raise HTTPException(status_code=500, detail="Base de datos no disponible")
    return db_engine


@router.post("/api/tarjetas/entregas")
def registrar_entrega(body: EntregaCreate, user_id: str = Depends(get_current_user_id)):
    try:
        with _db().begin() as conn:
            row = conn.execute(_UPSERT_SQL, {"user_id": user_id, **body.model_dump(exclude={"route_id"})}).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Negocio no encontrado")
            if body.route_id:
                conn.execute(_MARK_STOP_SQL, {"route_id": str(body.route_id), "user_id": user_id, "cnpj": body.cnpj})
    except HTTPException:
        raise
    except Exception as e:  # el mensaje del driver puede traer parámetros
        raise HTTPException(status_code=500, detail=f"No se pudo guardar la entrega ({type(e).__name__})")
    return {"id": row.id, "fecha": row.fecha.isoformat(), "cnpj": body.cnpj, "resultado": body.resultado}


@router.get("/api/tarjetas/resumen")
def resumen(
    cities: Optional[List[str]] = Query(None),
    user_id: str = Depends(get_current_user_id),
):
    try:
        nombres = [c.name for c in tarjetas.ciudades(cities or tarjetas.CIUDADES_POR_DEFECTO)]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        with _db().connect() as conn:
            return tarjetas.resumen(conn, user_id, nombres)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo leer el resumen ({type(e).__name__})")
