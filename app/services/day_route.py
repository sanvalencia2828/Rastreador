"""Orden de un dia de visitas y enlaces de Google Maps (compartido por scripts/rutas_semana.py y /api/routes/generate)."""

import unicodedata

from app.optimizer import optimize_open_path
from app.services.geo import haversine_km

MAX_WAYPOINTS = 9  # Google Maps: 9 waypoints por enlace (+ origen y destino)


def is_maringa(municipio: str | None) -> bool:
    plain = unicodedata.normalize("NFKD", municipio or "").encode("ascii", "ignore").decode()
    return plain.strip().casefold() == "maringa"


def order_day(points, depot=None):
    """Indices de `points` [(lat, lon)] en orden de visita (distancia en linea recta).

    El optimizador necesita ancla de entrada y de salida: nodos ficticios de costo 0 donde no hay depot.
    """
    n = len(points)
    pts = list(points) + ([depot] if depot else [])
    m = [[haversine_km(*a, *b) for b in pts] for a in pts]
    size = len(m)
    for row in m:
        row.extend([0.0, 0.0])
    m.extend([[0.0] * (size + 2), [0.0] * (size + 2)])
    entry = n if depot else size
    order = optimize_open_path(m, [entry, size + 1], list(range(n)))
    return [i for i in order if i < n]


def path_km(points):
    return sum(haversine_km(*points[j], *points[j + 1]) for j in range(len(points) - 1))


def maps_links(points):
    """Enlaces de Google Maps: origen, hasta 9 waypoints y destino; se parte si hay mas."""
    from urllib.parse import quote

    links, i = [], 0
    while len(points) >= 2:
        chunk = points[i:i + MAX_WAYPOINTS + 2]
        way = "|".join(f"{a},{b}" for a, b in chunk[1:-1])
        url = (f"https://www.google.com/maps/dir/?api=1&origin={chunk[0][0]},{chunk[0][1]}"
               f"&destination={chunk[-1][0]},{chunk[-1][1]}")
        links.append(url + (f"&waypoints={quote(way, safe=',')}" if way else ""))
        i += MAX_WAYPOINTS + 1
        if i >= len(points) - 1:
            break
    return links
