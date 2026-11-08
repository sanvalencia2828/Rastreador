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


DIAS_SEMANA = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]


def cluster_days(points, dias, max_paradas):
    """Agrupa [(lat, lon)] por cercania en `dias` grupos (KMeans, semilla fija) con tope por dia.

    Devuelve (grupos de indices, indices sin asignar). Los grupos salen ordenados de oeste a este,
    asi el dia N es siempre el mismo para los mismos datos.
    """
    from sklearn.cluster import KMeans

    if not points:
        return [], []
    k = min(dias, len(points))
    km = KMeans(n_clusters=k, random_state=0, n_init=10).fit(points)
    groups = [[i for i, lab in enumerate(km.labels_) if lab == c] for c in range(k)]
    dist = lambda i, c: haversine_km(*points[i], *km.cluster_centers_[c])  # noqa: E731
    overflow = []
    for c, g in enumerate(groups):
        while len(g) > max_paradas:
            far = max(g, key=lambda i: dist(i, c))
            g.remove(far)
            room = [o for o in range(k) if len(groups[o]) < max_paradas]
            if room:
                groups[min(room, key=lambda o: dist(far, o))].append(far)
            else:
                overflow.append(far)
    center = lambda g: (sum(points[i][1] for i in g) / len(g), sum(points[i][0] for i in g) / len(g))  # noqa: E731
    return sorted((g for g in groups if g), key=center), overflow
