"""Ruta de tarjetas: negocios activos y geocodificados a los que el usuario todavía no dejó su tarjeta.

La selección (activos, geocodificados, sin entrega vigente, lejos de los clientes del usuario) se hace en SQL
para que LIMIT devuelva siempre las paradas pedidas; el orden de visita lo pone el optimizador existente.
"""

from itertools import combinations
from typing import Optional

from sqlalchemy import text

from app.services.day_route import order_day
from app.services.geo import fix_encoding, haversine_km, haversine_m, osrm_table
from cities import CITIES

RESULTADOS = ("tarjeta_entregada", "cerrado", "rechazo", "interesado", "no_encontrado")
# No vuelven a salir. "rechazo" también: el negocio ya dijo que no.
DEFINITIVOS = ("tarjeta_entregada", "interesado", "rechazo")
DIAS_REINTENTO = 7  # "cerrado" y "no_encontrado" vuelven a salir pasado este plazo
RADIO_CLIENTE_M = 30
MAX_KM_MISMA_RUTA = 25
CIUDADES_POR_DEFECTO = ("Maringá", "Marialva", "Arapongas")
HOY_SQL = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"  # el día de quien reparte, no el UTC del servidor

_CIUDADES = {c.name: c for c in CITIES}

# Activo, geocodificado por el geocodificador (geocoded = TRUE solo con resultado real) y con coordenadas.
BASE_SQL = """
    e.situacao_cadastral = 2
    AND e.geocoded IS TRUE
    AND e.latitude IS NOT NULL AND e.longitude IS NOT NULL
    AND e.municipio = ANY(CAST(:cities AS text[]))
"""

# Sin entrega definitiva, ni otra en los últimos DIAS_REINTENTO días, de ESTE usuario.
SIN_ENTREGA_SQL = f"""
    NOT EXISTS (
        SELECT 1 FROM tarjeta_entregas t
         WHERE t.user_id = CAST(:user_id AS uuid)
           AND t.cnpj_completo = e.cnpj_completo
           AND (t.resultado IN ({", ".join(f"'{r}'" for r in DEFINITIVOS)})
                OR t.fecha > {HOY_SQL} - {DIAS_REINTENTO})
    )
"""

# A menos de RADIO_CLIENTE_M de un cliente del usuario: ya lo visita. La caja (~33 x 40 m) usa el índice
# implícito de la comparación; la distancia equirectangular basta a esta escala.
LEJOS_DE_CLIENTE_SQL = f"""
    NOT EXISTS (
        SELECT 1 FROM clientes c
         WHERE c.user_id = CAST(:user_id AS uuid)
           AND c.lat IS NOT NULL AND c.lon IS NOT NULL
           AND c.lat BETWEEN e.latitude - 0.0003 AND e.latitude + 0.0003
           AND c.lon BETWEEN e.longitude - 0.0004 AND e.longitude + 0.0004
           AND 111320 * sqrt(power(CAST(c.lat - e.latitude AS float8), 2)
                             + power(CAST(c.lon - e.longitude AS float8) * cos(radians(CAST(e.latitude AS float8))), 2))
               < {RADIO_CLIENTE_M}
    )
"""

CANDIDATOS_SQL = text(f"""
    SELECT e.id, e.cnpj_completo, e.nome_fantasia, e.descricao_tipo_logradouro, e.logradouro, e.numero,
           e.bairro, e.municipio, e.business_type,
           CAST(e.latitude AS float8) AS lat, CAST(e.longitude AS float8) AS lon
      FROM estabelecimentos e
     WHERE {BASE_SQL}
       AND (CAST(:business_type AS text) IS NULL OR e.business_type = CAST(:business_type AS text))
       AND (CAST(:cnae AS integer) IS NULL OR e.cnae_fiscal = CAST(:cnae AS integer))
       AND {SIN_ENTREGA_SQL}
       AND {LEJOS_DE_CLIENTE_SQL}
     ORDER BY power(CAST(e.latitude AS float8) - CAST(:lat AS float8), 2)
              + power((CAST(e.longitude AS float8) - CAST(:lon AS float8)) * cos(radians(CAST(:lat AS float8))), 2),
              e.id
     LIMIT :limit
""")

GEOCODIFICADOS_SQL = text(f"""
    SELECT e.municipio, COUNT(*) AS geocodificados,
           COUNT(*) FILTER (WHERE NOT EXISTS (
               SELECT 1 FROM tarjeta_entregas t
                WHERE t.user_id = CAST(:user_id AS uuid) AND t.cnpj_completo = e.cnpj_completo
                  AND t.resultado IN ('tarjeta_entregada', 'interesado'))) AS sin_tarjeta
      FROM estabelecimentos e
     WHERE {BASE_SQL}
     GROUP BY e.municipio
""")

ENTREGAS_SQL = text(f"""
    SELECT COALESCE(e.municipio, '') AS ciudad, t.resultado, COUNT(*) AS total,
           COUNT(*) FILTER (WHERE t.fecha = {HOY_SQL}) AS hoy,
           COUNT(*) FILTER (WHERE t.fecha >= CAST(date_trunc('week', {HOY_SQL}) AS date)) AS semana
      FROM tarjeta_entregas t
      LEFT JOIN estabelecimentos e ON e.cnpj_completo = t.cnpj_completo
     WHERE t.user_id = CAST(:user_id AS uuid)
     GROUP BY 1, 2
""")


def ciudades(nombres) -> list:
    """City de cities.py por nombre; ValueError con las válidas si alguno no existe."""
    desconocidas = [n for n in nombres if n not in _CIUDADES]
    if desconocidas:
        raise ValueError(f"Ciudad desconocida: {', '.join(desconocidas)}. Válidas: {', '.join(_CIUDADES)}.")
    return [_CIUDADES[n] for n in dict.fromkeys(nombres)]


def grupos(lista, juntar: bool) -> list:
    """Una ruta por ciudad; con `juntar`, una sola si todas están a menos de MAX_KM_MISMA_RUTA entre sí."""
    if not juntar:
        return [[c] for c in lista]
    for a, b in combinations(lista, 2):
        km = haversine_km(a.lat, a.lon, b.lat, b.lon)
        if km >= MAX_KM_MISMA_RUTA:
            raise ValueError(
                f"{a.name} y {b.name} están a {km:.0f} km: solo se juntan en una ruta ciudades a menos de "
                f"{MAX_KM_MISMA_RUTA} km. Pide rutas separadas."
            )
    return [lista]


def origen(grupo, lat: Optional[float], lon: Optional[float]) -> tuple:
    """El GPS si está cerca de alguna ciudad del grupo; si no (o si falta), el centro de la primera."""
    if lat is not None and lon is not None and any(
        haversine_km(lat, lon, c.lat, c.lon) < MAX_KM_MISMA_RUTA for c in grupo
    ):
        return lat, lon
    return grupo[0].lat, grupo[0].lon


def candidatos(conn, user_id: str, nombres, inicio, limite: int, business_type=None, cnae=None) -> list:
    rows = conn.execute(CANDIDATOS_SQL, {
        "user_id": user_id, "cities": list(nombres), "lat": inicio[0], "lon": inicio[1], "limit": limite,
        "business_type": business_type, "cnae": cnae,
    }).fetchall()
    return [dict(r._mapping) for r in rows]


def maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


def _direccion(r: dict) -> str:
    calle = " ".join(p for p in (r.get("descricao_tipo_logradouro"), r.get("logradouro")) if p)
    return fix_encoding(", ".join(p for p in (calle, r.get("numero")) if p))


def ordenar(rows: list, inicio) -> tuple:
    """(paradas en orden de visita con distancia desde la anterior, fuente de costos)."""
    points = [(r["lat"], r["lon"]) for r in rows]
    table = osrm_table(points + [inicio]) if points else None
    order = order_day(points, inicio, matrix=table[0] if table else None) if points else []
    paradas, prev = [], inicio
    for n, i in enumerate(order, 1):
        r = rows[i]
        paradas.append({
            "orden": n,
            "business_id": r["id"],
            "cnpj": r["cnpj_completo"],
            "nombre": fix_encoding(r.get("nome_fantasia") or "") or "(sin nombre)",
            "direccion": _direccion(r),
            "bairro": fix_encoding(r.get("bairro") or ""),
            "ciudad": fix_encoding(r.get("municipio") or ""),
            "tipo": r.get("business_type"),
            "lat": r["lat"],
            "lon": r["lon"],
            "distancia_m": haversine_m(*prev, r["lat"], r["lon"]),  # en línea recta
            "maps_url": maps_url(r["lat"], r["lon"]),
        })
        prev = (r["lat"], r["lon"])
    return paradas, "osrm" if table else "linea_recta"


def geocodificados(conn, user_id: str, nombres) -> dict:
    """{municipio: (geocodificados activos, sin tarjeta entregada)}."""
    rows = conn.execute(GEOCODIFICADOS_SQL, {"user_id": user_id, "cities": list(nombres)}).fetchall()
    return {r.municipio: (int(r.geocodificados), int(r.sin_tarjeta)) for r in rows}


def resumen(conn, user_id: str, nombres) -> dict:
    """Totales del usuario por ciudad y resultado, y cuántos negocios quedan sin tarjeta por ciudad."""
    vacio = lambda: {"hoy": 0, "semana": 0, "total": 0, "por_resultado": dict.fromkeys(RESULTADOS, 0)}  # noqa: E731
    por_ciudad = {n: vacio() for n in nombres}
    totales = vacio()
    for r in conn.execute(ENTREGAS_SQL, {"user_id": user_id}).fetchall():
        for bucket in (por_ciudad.setdefault(r.ciudad or "Sin ciudad", vacio()), totales):
            bucket["por_resultado"][r.resultado] += int(r.total)
            if r.resultado == "tarjeta_entregada":  # hoy / semana / total cuentan tarjetas entregadas
                bucket["hoy"] += int(r.hoy)
                bucket["semana"] += int(r.semana)
                bucket["total"] += int(r.total)
    conteo = geocodificados(conn, user_id, list(por_ciudad))
    return {
        "ciudades": [
            {"ciudad": n, **d, "geocodificados": conteo.get(n, (0, 0))[0], "sin_tarjeta": conteo.get(n, (0, 0))[1]}
            for n, d in por_ciudad.items()
        ],
        "totales": totales,
    }
