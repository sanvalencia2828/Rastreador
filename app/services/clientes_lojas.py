"""Clientes propios (tabla `clientes`) mezclados en las vistas de lojas, solo para su dueño.

Nunca se copian a `estabelecimentos`: recargar el CSV los duplicaría. Sin teléfono ni email (la tabla no los tiene).
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.services.geo import fix_encoding, haversine_m

_ROWS = text("""
    SELECT id, nombre_negocio, nombre_cliente, direccion, bairro, municipio, lat, lon, visita_diaria, atrasado
    FROM clientes
    WHERE user_id = :u
    ORDER BY atrasado DESC, visita_diaria DESC, nombre_negocio, id
""")

_COUNTS = text("SELECT municipio, COUNT(*) FROM clientes WHERE user_id = :u GROUP BY 1")


def _rows(conn, user_id: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
    """Clientes del usuario; `city` filtra por subcadena de municipio (casefold, sin depender del locale)."""
    out = []
    for r in conn.execute(_ROWS, {"u": user_id}).fetchall():
        m = dict(r._mapping)
        if city and city_key(city.strip()) not in city_key(m["municipio"]):
            continue
        m["id"] = str(m["id"])
        m["lat"] = float(m["lat"]) if m["lat"] is not None else None
        m["lon"] = float(m["lon"]) if m["lon"] is not None else None
        out.append(m)
    return out


def city_key(name: Optional[str]) -> str:
    """Clave para comparar ciudades: en producción cities.name tiene mojibake ("MaringÃ¡";
    base_schema.py está bien, el origen no está claro) y clientes.municipio no. casefold en Python: UPPER de Postgres depende del locale."""
    return fix_encoding(name or "").casefold()


def counts_by_city(conn, user_id: str) -> Dict[str, int]:
    """{city_key(municipio): nº de clientes}, con y sin ubicación."""
    out: Dict[str, int] = {}
    for name, n in conn.execute(_COUNTS, {"u": user_id}).fetchall():
        if name:
            out[city_key(name)] = out.get(city_key(name), 0) + int(n)
    return out


def for_routes(conn, user_id: str, city: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filas con la forma de /api/businesses (antes de _business_route_metrics)."""
    return [{
        "id": c["id"], "cnpj": None, "name": c["nombre_negocio"] or c["nombre_cliente"] or "",
        "nome_fantasia": c["nombre_negocio"], "lat": c["lat"], "lng": c["lon"], "city": c["municipio"] or "",
        "bairro": c["bairro"] or "", "logradouro": c["direccion"] or "", "last_visit_date": None,
        "visits_count": 0, "avg_visit_interval_days": None, "origen": "cliente",
        "visita_diaria": c["visita_diaria"], "atrasado": c["atrasado"],
    } for c in _rows(conn, user_id, city)]


def near(conn, user_id: str, lat: float, lon: float, radius: int) -> List[Dict[str, Any]]:
    """Clientes con ubicación a menos de `radius` m, con la forma de /api/businesses/near."""
    # shortcut: distancia en Python sobre todos los clientes del usuario (decenas); pasar a SQL si son miles
    items = []
    for c in _rows(conn, user_id):
        if c["lat"] is None:
            continue
        d = haversine_m(lat, lon, c["lat"], c["lon"])
        if d <= radius:
            items.append({
                "id": c["id"], "cnpj": f"cliente:{c['id']}", "nome_fantasia": c["nombre_negocio"] or "",
                "business_type": "", "cnae": "", "logradouro": c["direccion"] or "", "numero": "",
                "bairro": c["bairro"] or "", "municipio": c["municipio"] or "", "lat": c["lat"], "lon": c["lon"],
                "distance_m": d, "cnae_label": "Cliente", "cnae_icon": "", "porte_empresa": "",
                "origen": "cliente", "visita_diaria": c["visita_diaria"], "atrasado": c["atrasado"],
            })
    return items
