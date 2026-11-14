"""Tiempo REAL por calle, derivado de visits.visited_at de una ruta (reutiliza las visitas ya sincronizadas).

Aproximación: la duración en una calle es el tiempo entre su primera visita y la primera de la calle siguiente,
así que incluye desplazamiento y pausas. Se descartan intervalos de más de 90 min (almuerzo, fin de jornada).
Mejora futura: started_at/ended_at por calle desde la app.
"""

from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import text

from app.services.streets import normalize_street, street_key

MAX_GAP_S = 90 * 60
MUNICIPIO = "MARINGA"  # solo hay catálogo de calles de Maringá


def derive_street_durations(
    visits: Iterable[Tuple[datetime, str]], max_gap_s: int = MAX_GAP_S
) -> Tuple[List[Tuple[str, int, int]], Dict[str, int]]:
    """[(clave_calle, segundos, n_visitas)] y contadores de lo descartado. `visits` = (visited_at, logradouro)."""
    groups: List[List[Any]] = []  # [key, first_ts, n]
    for ts, logradouro in sorted(visits, key=lambda v: v[0]):
        tipo, nome = normalize_street(logradouro or "")
        if not nome:
            continue
        key = street_key(tipo, nome)
        if groups and groups[-1][0] == key:
            groups[-1][2] += 1
        else:
            groups.append([key, ts, 1])
    stats = {"sin_siguiente": 1 if groups else 0, "sin_duracion": 0, "mas_de_90_min": 0}
    totals: "OrderedDict[str, List[int]]" = OrderedDict()
    for (key, ts, n), nxt in zip(groups, groups[1:]):
        seconds = int((nxt[1] - ts).total_seconds())
        if seconds <= 0:
            stats["sin_duracion"] += 1
        elif seconds > max_gap_s:
            stats["mas_de_90_min"] += 1
        else:
            acc = totals.setdefault(key, [0, 0])
            acc[0] += seconds
            acc[1] += n
    return [(k, s, n) for k, (s, n) in totals.items()], stats


def _resolve_to_catalog(conn, rows: List[Tuple[str, int, int]]) -> List[Tuple[str, int, int]]:
    """Mantiene solo calles del catálogo. Una visita sin tipo ("GASTAO VIDIGAL DOUTOR": así guarda el volcado
    el logradouro) se asigna por nombre solo si UNA sola calle del catálogo se llama así; si no, se descarta."""
    if not rows:
        return []
    keys = [k for k, _, _ in rows]
    exact = {r[0] for r in conn.execute(
        text("SELECT street_key FROM street_catalog WHERE municipio = :m AND street_key = ANY(:k)"),
        {"m": MUNICIPIO, "k": keys})}
    names = sorted({k[1:] for k in keys if k.startswith("|") and k not in exact})
    by_name = {}
    if names:
        for nombre, found in conn.execute(
            text("SELECT nombre, array_agg(street_key) FROM street_catalog WHERE municipio = :m AND nombre = ANY(:n)"
                 " GROUP BY nombre"),
            {"m": MUNICIPIO, "n": names},
        ):
            if len(found) == 1:
                by_name["|" + nombre] = found[0]
    merged: "OrderedDict[str, List[int]]" = OrderedDict()
    for key, seconds, n in rows:
        target = key if key in exact else by_name.get(key)
        if target:
            acc = merged.setdefault(target, [0, 0])
            acc[0] += seconds
            acc[1] += n
    return [(k, s, n) for k, (s, n) in merged.items()]


def refresh_street_times(conn, user_id: str, route_id: str) -> Dict[str, int]:
    """Recalcula (idempotente) las filas de street_time_log de una ruta del usuario. Solo calles del catálogo.

    Una fila por (usuario, ruta, calle): `seconds` suma los tramos de esa calle en la ruta, así que el recuento de
    registros (n_real) cuenta RUTAS, no pasadas.
    """
    visits = conn.execute(
        text("SELECT visited_at, logradouro FROM visits WHERE user_id = :u AND route_id = :r AND visited_at IS NOT NULL"
             " ORDER BY visited_at"),
        {"u": user_id, "r": route_id},
    ).fetchall()
    rows, stats = derive_street_durations([(v[0], v[1]) for v in visits])
    n_before = len(rows)
    rows = _resolve_to_catalog(conn, rows)
    kept = rows
    stats["fuera_del_catalogo"] = n_before - len(kept)
    conn.execute(text("DELETE FROM street_time_log WHERE user_id = :u AND route_id = :r"), {"u": user_id, "r": route_id})
    if kept:
        conn.execute(
            text("INSERT INTO street_time_log (user_id, route_id, municipio, street_key, seconds, n_visitas)"
                 " VALUES (:u, :r, :m, :k, :s, :n)"),
            [{"u": user_id, "r": route_id, "m": MUNICIPIO, "k": k, "s": s, "n": n} for k, s, n in kept],
        )
    stats["registradas"] = len(kept)
    return stats


def refresh_street_times_safely(conn, user_id: str, route_id: str) -> None:
    """Como refresh_street_times, pero un fallo (p. ej. sin catálogo) nunca rompe la operación que lo llama."""
    try:
        with conn.begin_nested():
            refresh_street_times(conn, user_id, route_id)
    except Exception as e:  # class name only
        print(f"street_time_log not updated ({type(e).__name__})")
