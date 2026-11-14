"""Business search, status and stats endpoints."""

from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.core.cache import get_cached_response, set_cached_response
from app.core.database import db_engine
from app.core.security import get_current_user_id
from app.schemas.business import (
    BusinessStatusUpdate,
    TechBusiness,
    TechBusinessesResponse,
)
from app.services.business_loader import load_businesses
from app.services.geo import (
    TECH_CNAE_SUBCATEGORY,
    cnae_to_category,
    fix_encoding,
    format_cnpj,
    haversine_m,
)
from app.services.route_planning import _business_route_metrics

router = APIRouter()

MAX_LIMIT = 500  # cap for ?limit= on the list/search endpoints


@router.get("/api/businesses/tech", response_model=TechBusinessesResponse)
def get_tech_businesses(limit: int = 50, offset: int = 0, search: str = ""):
    """
    Returns paginated tech businesses with enriched CNAE subcategory data.
    Supports full-text search by name, CNAE or neighborhood.
    - limit: max items per page (default 50)
    - offset: pagination offset (default 0)
    - search: filter by nome_fantasia, cnae or bairro (case-insensitive)
    """
    businesses = load_businesses()

    # Filter only tech businesses
    tech_businesses = [b for b in businesses if b.get("business_type") == "tech"]

    # Apply search filter
    search_lower = search.strip().lower()
    if search_lower:
        tech_businesses = [
            b
            for b in tech_businesses
            if search_lower in (b.get("nome_fantasia") or "").lower()
            or search_lower
            in str(b.get("cnae_fiscal") or b.get("cnae_fiscal_principal") or "").lower()
            or search_lower in (b.get("bairro") or "").lower()
            or search_lower in (b.get("logradouro") or "").lower()
        ]

    total = len(tech_businesses)

    # Paginate
    paginated = tech_businesses[offset : offset + limit]

    items = []
    for biz in paginated:
        cnpj = format_cnpj(biz)
        cnae_raw = str(biz.get("cnae_fiscal") or biz.get("cnae_fiscal_principal") or "")
        prefix = cnae_raw[:2]
        sub = TECH_CNAE_SUBCATEGORY.get(prefix, {"label": "Tecnología", "icon": "💡"})

        items.append(
            TechBusiness(
                cnpj=cnpj,
                nome_fantasia=biz.get("nome_fantasia") or f"Empresa Tech {cnpj[:8]}",
                cnae=cnae_raw,
                cnae_label=sub["label"],
                cnae_icon=sub["icon"],
                bairro=biz.get("bairro") or "Centro",
                logradouro=biz.get("logradouro") or "",
                municipio=biz.get("municipio") or "Londrina",
                business_type="tech",
            )
        )

    print(
        f"Returning {len(items)} tech businesses (total={total}, offset={offset}, search='{search}')."
    )
    return TechBusinessesResponse(total=total, offset=offset, limit=limit, items=items)


@router.get("/api/businesses/near")
def get_businesses_near(lat: float, lon: float, radius: int = 500):
    """
    Returns businesses within `radius` meters of (lat, lon).
    Uses PostGIS ST_DWithin on the geography column for accurate meter-based search.
    Fallback to load_businesses() + haversine if geom column is unavailable.
    """
    if radius > 2000:
        radius = 2000
    if radius < 1:
        radius = 500

    cache_key = f"near_{lat:.3f}_{lon:.3f}_{radius}"  # ~110 m cells
    cached = get_cached_response(cache_key)
    if cached is not None:
        return cached

    if db_engine:
        try:
            with db_engine.connect() as conn:
                query = text("""
                    SELECT
                        cnpj_completo,
                        nome_fantasia,
                        business_type,
                        cnae_fiscal,
                        logradouro,
                        numero,
                        bairro,
                        municipio,
                        porte_empresa,
                        latitude,
                        longitude,
                        ST_Distance(
                            geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                        )::int as distance_m
                    FROM estabelecimentos
                    WHERE ST_DWithin(
                        geom::geography,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                        :radius
                    )
                      AND situacao_cadastral = 2
                      AND geom IS NOT NULL
                    ORDER BY distance_m ASC
                    LIMIT 200
                """)
                result = conn.execute(query, {"lat": lat, "lon": lon, "radius": radius})
                items = []
                for row in result:
                    r = dict(row._mapping)
                    items.append({
                        "cnpj": r.get("cnpj_completo", ""),
                        "nome_fantasia": fix_encoding(r.get("nome_fantasia") or ""),
                        "business_type": r.get("business_type") or "",
                        "cnae": str(r.get("cnae_fiscal") or ""),
                        "logradouro": fix_encoding(r.get("logradouro") or ""),
                        "numero": r.get("numero") or "",
                        "bairro": fix_encoding(r.get("bairro") or ""),
                        "municipio": fix_encoding(r.get("municipio") or ""),
                        "lat": float(r["latitude"]) if r.get("latitude") else 0,
                        "lon": float(r["longitude"]) if r.get("longitude") else 0,
                        "distance_m": r.get("distance_m", 0),
                        "cnae_label": cnae_to_category(r.get("cnae_fiscal")),
                        "cnae_icon": "",
                        "porte_empresa": str(r.get("porte_empresa") or ""),
                    })
                response = {"items": items, "total": len(items), "radius": radius}
                set_cached_response(cache_key, response, ttl=120)
                return response
        except Exception as e:
            print(f"PostGIS /businesses/near failed: {e}. Falling back to haversine.")

    # Fallback: load all businesses and filter by haversine
    businesses = load_businesses()
    items = []
    for biz in businesses:
        biz_lat = biz.get("latitude")
        biz_lon = biz.get("longitude")
        if biz_lat is None or biz_lon is None:
            continue
        dist = haversine_m(lat, lon, float(biz_lat), float(biz_lon))
        if dist <= radius:
            cnpj = format_cnpj(biz)
            cnae_raw = str(
                biz.get("cnae_fiscal") or biz.get("cnae_fiscal_principal") or ""
            )
            items.append({
                "cnpj": cnpj,
                "nome_fantasia": fix_encoding(biz.get("nome_fantasia") or ""),
                "business_type": biz.get("business_type") or "",
                "cnae": cnae_raw,
                "logradouro": fix_encoding(biz.get("logradouro") or ""),
                "numero": biz.get("numero") or "",
                "bairro": fix_encoding(biz.get("bairro") or ""),
                "municipio": fix_encoding(biz.get("municipio") or ""),
                "lat": float(biz_lat),
                "lon": float(biz_lon),
                "distance_m": dist,
                "cnae_label": cnae_to_category(cnae_raw),
                "cnae_icon": "",
                "porte_empresa": str(biz.get("porte_empresa") or ""),
            })
    items.sort(key=lambda x: x["distance_m"])
    items = items[:200]
    response = {"items": items, "total": len(items), "radius": radius}
    set_cached_response(cache_key, response, ttl=120)
    return response


@router.patch("/api/businesses/{cnpj}/status", dependencies=[Depends(get_current_user_id)])
def update_business_status(cnpj: str, body: BusinessStatusUpdate):
    if body.status not in ("visited", "client"):
        raise HTTPException(status_code=400, detail="Status must be 'visited' or 'client'")
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            # Verificar que la loja existe (el CNPJ se almacena en cnpj_completo)
            exists = conn.execute(
                text("SELECT cnpj_completo FROM estabelecimentos WHERE cnpj_completo = :cnpj"),
                {"cnpj": cnpj},
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Business not found")

            # Upsert en business_status (sin route_id por ahora, status global)
            conn.execute(
                text("""
                    INSERT INTO business_status (cnpj, status, updated_at)
                    VALUES (:cnpj, :status, NOW())
                    ON CONFLICT (cnpj) DO UPDATE SET status = :status, updated_at = NOW()
                """),
                {"cnpj": cnpj, "status": body.status},
            )
            conn.commit()
            return {"cnpj": cnpj, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update status: {e}")


@router.get("/api/businesses/status")
def get_businesses_status(cnpjs: str):
    """Get status for a comma-separated list of CNPJs."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    cnpj_list = [c.strip() for c in cnpjs.split(",") if c.strip()]
    if not cnpj_list:
        return []
    try:
        with db_engine.connect() as conn:
            placeholders = ", ".join(f":cnpj_{i}" for i in range(len(cnpj_list)))
            params = {f"cnpj_{i}": c for i, c in enumerate(cnpj_list)}
            rows = conn.execute(
                text(f"SELECT cnpj, status FROM business_status WHERE cnpj IN ({placeholders})"),
                params,
            ).fetchall()
            return {r[0]: r[1] for r in rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch statuses: {e}")


@router.get("/api/businesses")
@router.get("/api/businesses/for-routes")
def get_businesses_for_routes(
    city: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
):
    """Return businesses with persisted visit metrics and route urgency."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 5000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")

    query = """
        SELECT
            e.id,
            e.cnpj_completo AS cnpj,
            e.nome_fantasia AS name,
            e.nome_fantasia,
            e.latitude AS lat,
            e.longitude AS lng,
            e.municipio AS city,
            e.bairro,
            e.logradouro,
            e.last_visit_date,
            COALESCE(e.visits_count, 0) AS visits_count,
            e.avg_visit_interval_days
        FROM estabelecimentos e
        WHERE e.situacao_cadastral = 2
          AND (e.latitude IS NOT NULL OR e.geom IS NOT NULL)
    """
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if city and city.strip():
        query += " AND e.municipio ILIKE :city"
        params["city"] = f"%{city.strip()}%"
    query += " ORDER BY e.nome_fantasia NULLS LAST, e.id LIMIT :limit OFFSET :offset"

    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text(query), params)
            businesses = []
            for row in rows:
                item = dict(row._mapping)
                item["lat"] = float(item["lat"]) if item["lat"] is not None else None
                item["lng"] = float(item["lng"]) if item["lng"] is not None else None
                item["name"] = fix_encoding(item.get("name") or "")
                item["city"] = fix_encoding(item.get("city") or "")
                item["bairro"] = fix_encoding(item.get("bairro") or "")
                item["logradouro"] = fix_encoding(item.get("logradouro") or "")
                businesses.append(_business_route_metrics(item))
            return businesses
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch businesses: {e}")


@router.get("/api/businesses/search")
def search_businesses(q: str, limit: int = 50):
    limit = max(1, min(limit, MAX_LIMIT))
    if len(q.strip()) < 3:
        raise HTTPException(status_code=400, detail="Mínimo 3 caracteres")
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT cnpj_completo, nome_fantasia, cnae_label, bairro,
                           logradouro, municipio,
                           ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
                    FROM estabelecimentos
                    WHERE situacao_cadastral = 2
                      AND geom IS NOT NULL
                      AND (
                        nome_fantasia ILIKE :q
                        OR cnpj_completo ILIKE :q
                        OR logradouro ILIKE :q
                      )
                    ORDER BY nome_fantasia
                    LIMIT :limit
                    """
                ),
                {"q": f"%{q.strip()}%", "limit": limit},
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "bairro": fix_encoding(r[3]),
                    "logradouro": fix_encoding(r[4]),
                    "municipio": fix_encoding(r[5]),
                    "lat": float(r[6]),
                    "lon": float(r[7]),
                }
                for r in rows
            ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


@router.get("/api/stats/summary")
def get_stats_summary():
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            total = conn.execute(
                text(
                    "SELECT COUNT(*) FROM estabelecimentos WHERE situacao_cadastral = 2 AND geom IS NOT NULL"
                )
            ).scalar() or 0
            visited = conn.execute(
                text("SELECT COUNT(DISTINCT cnpj) FROM visits")
            ).scalar() or 0
            clients = conn.execute(
                text("SELECT COUNT(*) FROM business_status WHERE status = 'client'")
            ).scalar() or 0

            city_rows = conn.execute(
                text(
                    """
                    SELECT c.id, c.name, c.state, c.lat, c.lon,
                        (SELECT COUNT(*) FROM estabelecimentos e
                         WHERE e.situacao_cadastral = 2 AND e.geom IS NOT NULL
                           AND e.municipio = c.name) as total,
                        (SELECT COUNT(DISTINCT v.cnpj) FROM visits v
                         JOIN estabelecimentos e ON e.cnpj_completo = v.cnpj
                         WHERE e.municipio = c.name) as visited
                    FROM cities c
                    ORDER BY c.name
                    """
                )
            ).fetchall()
            cities_stats = [
                {
                    "id": int(r[0]),
                    "name": r[1],
                    "state": r[2],
                    "lat": float(r[3]) if r[3] else 0,
                    "lon": float(r[4]) if r[4] else 0,
                    "total": int(r[5] or 0),
                    "visited": int(r[6] or 0),
                }
                for r in city_rows
            ]

            return {
                "total_businesses": int(total),
                "visited": int(visited),
                "clients": int(clients),
                "cities": cities_stats,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats failed: {e}")


@router.get("/api/businesses/clients")
def get_clients(limit: int = 500):
    limit = max(1, min(limit, MAX_LIMIT))
    """Lista todos los clientes (business_status = 'client')."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT e.cnpj_completo, e.nome_fantasia, e.cnae_label, e.bairro,
                           e.logradouro, e.municipio,
                           ST_Y(e.geom::geometry) as lat, ST_X(e.geom::geometry) as lon
                    FROM business_status bs
                    JOIN estabelecimentos e ON e.cnpj_completo = bs.cnpj
                    WHERE bs.status = 'client'
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "bairro": fix_encoding(r[3]),
                    "logradouro": fix_encoding(r[4]),
                    "municipio": fix_encoding(r[5]),
                    "lat": float(r[6]),
                    "lon": float(r[7]),
                }
                for r in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@router.get("/api/businesses/city-category")
def get_businesses_by_city_and_category(city: str, category: str = "pizza", limit: int = 50):
    limit = max(1, min(limit, MAX_LIMIT))
    """
    Busca establecimientos por ciudad (municipio) y categoría (ej. pizza/pizzería).
    Filtra los establecimientos activos (situacao_cadastral = 2).
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT cnpj_completo, nome_fantasia, cnae_label, cnae_fiscal_descricao,
                           bairro, logradouro, municipio,
                           ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
                    FROM estabelecimentos
                    WHERE situacao_cadastral = 2
                      AND geom IS NOT NULL
                      AND municipio ILIKE :city
                      AND (
                        nome_fantasia ILIKE :cat
                        OR cnae_fiscal_descricao ILIKE :cat
                        OR cnae_label ILIKE :cat
                      )
                    ORDER BY nome_fantasia
                    LIMIT :limit
                    """
                ),
                {
                    "city": f"%{city.strip()}%",
                    "cat": f"%{category.strip()}%",
                    "limit": limit
                },
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "cnae_fiscal_descricao": fix_encoding(r[3]),
                    "bairro": fix_encoding(r[4]),
                    "logradouro": fix_encoding(r[5]),
                    "municipio": fix_encoding(r[6]),
                    "lat": float(r[7]) if r[7] is not None else None,
                    "lon": float(r[8]) if r[8] is not None else None,
                }
                for r in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query businesses: {e}")
