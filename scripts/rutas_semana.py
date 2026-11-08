#!/usr/bin/env python3
"""Rutas semanales de clientes de Maringa: agrupa por cercania (KMeans) y ordena cada dia.

    python scripts/rutas_semana.py [--csv RUTA] [--dias 5] [--max-paradas 10]

Origen opcional: ROUTE_DEPOT_LAT / ROUTE_DEPOT_LON en el entorno (nunca en git).
Escribe <RASTREADOR_DATA_DIR o .data>/rutas/rutas_semana_<fecha>.md. El CSV es privado: debe estar
dentro de esa carpeta de datos y no rastreado por git. Por consola solo salen conteos.
Las distancias son en LINEA RECTA (Haversine), no por calle.
"""

import argparse
import math
import os
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seed_clientes import SeedError, parse_rows  # noqa: E402

from app.optimizer import optimize_open_path  # noqa: E402
from app.services.geo import haversine_km  # noqa: E402

MAX_WAYPOINTS = 9  # Google Maps: 9 waypoints por enlace (+ origen y destino)


def data_dir() -> Path:
    return Path(os.environ.get("RASTREADOR_DATA_DIR") or REPO / ".data").resolve()


def check_csv(path: Path) -> None:
    """Misma idea que el resto del proyecto: el CSV real vive en la carpeta de datos, fuera de git."""
    if not path.resolve().is_relative_to(data_dir()):
        raise SeedError("el CSV esta fuera de la carpeta de datos (.data/); se niega a correr")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.resolve())],
        cwd=REPO, capture_output=True,
    ).returncode == 0
    if tracked:
        raise SeedError("el CSV esta rastreado por git; se niega a correr")


def is_maringa(municipio: str) -> bool:
    plain = unicodedata.normalize("NFKD", municipio).encode("ascii", "ignore").decode()
    return plain.strip().casefold() == "maringa"


def split_rows(rows):
    """(en Maringa con coords, fuera de Maringa con coords, sin coords)."""
    located = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
    pending = [r for r in rows if r not in located]
    inside = [r for r in located if is_maringa(r["municipio"])]
    return inside, [r for r in located if r not in inside], pending


def cluster_days(rows, dias, max_paradas):
    """KMeans (semilla fija) y tope de paradas por dia. Devuelve (dias, sin_asignar)."""
    from sklearn.cluster import KMeans

    if not rows:
        return [], []
    k = min(dias, len(rows))
    pts = [(r["lat"], r["lon"]) for r in rows]
    km = KMeans(n_clusters=k, random_state=0, n_init=10).fit(pts)
    groups = [[i for i, lab in enumerate(km.labels_) if lab == c] for c in range(k)]
    dist = lambda i, c: haversine_km(*pts[i], *km.cluster_centers_[c])  # noqa: E731
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
    return [[rows[i] for i in g] for g in groups if g], [rows[i] for i in overflow]


def order_day(stops, depot):
    """Orden de visita con el optimizador existente. Nodos ficticios de costo 0 dan inicio/fin libres."""
    pts = [(r["lat"], r["lon"]) for r in stops]
    n = len(pts)
    if depot:
        pts = pts + [depot]
    m = [[haversine_km(*a, *b) for b in pts] for a in pts]
    start = n if depot else None
    # El optimizador necesita ancla de entrada y de salida: ficticias (costo 0) donde no hay depot.
    size = len(m)
    for row in m:
        row.extend([0.0, 0.0])
    m.extend([[0.0] * (size + 2), [0.0] * (size + 2)])
    entry = start if start is not None else size
    exit_ = size + 1
    order = optimize_open_path(m, [entry, exit_], list(range(n)))
    return [i for i in order if i < n]


def maps_links(points):
    """Enlaces de Google Maps: origen, hasta 9 waypoints y destino; se parte si hay mas."""
    links, i = [], 0
    while True:
        chunk = points[i:i + MAX_WAYPOINTS + 2]
        way = "|".join(f"{a},{b}" for a, b in chunk[1:-1])
        url = (f"https://www.google.com/maps/dir/?api=1&origin={chunk[0][0]},{chunk[0][1]}"
               f"&destination={chunk[-1][0]},{chunk[-1][1]}")
        links.append(url + (f"&waypoints={quote(way, safe=',')}" if way else ""))
        i += MAX_WAYPOINTS + 1
        if i >= len(points) - 1:
            return links


def label(r):
    return r["nombre_negocio"] or r["nombre_cliente"] or r["external_id"]


def build_markdown(days, depot, overflow, outside, pending):
    out = ["# Rutas de la semana", "",
           "Distancias aproximadas en **linea recta** (Haversine), no por calle.", ""]
    for n, stops in enumerate(days, 1):
        order = order_day(stops, depot)
        ordered = [stops[i] for i in order]
        pts = ([depot] if depot else []) + [(r["lat"], r["lon"]) for r in ordered]
        km = sum(haversine_km(*pts[j], *pts[j + 1]) for j in range(len(pts) - 1))
        out += [f"## Dia {n} ({len(ordered)} paradas, ~{km:.1f} km en linea recta)", ""]
        out += [f"{j}. {label(r)} - {r['direccion']}, {r['bairro']}" for j, r in enumerate(ordered, 1)]
        out += [""]
        if len(pts) >= 2:
            out += [f"- [Ruta en Google Maps{f' (parte {j})' if len(maps_links(pts)) > 1 else ''}]({u})"
                    for j, u in enumerate(maps_links(pts), 1)] + [""]
    for title, group in (("Sin asignar (exceden el tope de paradas)", overflow),
                         ("Fuera de Maringa (viaje aparte)", outside),
                         ("Pendientes de ubicar", pending)):
        if group:
            out += [f"## {title}", ""] + [f"- {label(r)} - {r['direccion']}, {r['municipio']}" for r in group] + [""]
    return "\n".join(out)


def depot_from_env():
    lat, lon = os.environ.get("ROUTE_DEPOT_LAT"), os.environ.get("ROUTE_DEPOT_LON")
    if not lat and not lon:
        return None
    try:
        depot = (float(lat), float(lon))
    except (TypeError, ValueError):
        raise SeedError("ROUTE_DEPOT_LAT/LON deben ser ambos numericos") from None
    if not (math.isfinite(depot[0]) and math.isfinite(depot[1]) and abs(depot[0]) <= 90 and abs(depot[1]) <= 180):
        raise SeedError("ROUTE_DEPOT_LAT/LON fuera de rango")
    return depot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", default=str(data_dir() / "clientes" / "clientes_maringa.csv"))
    ap.add_argument("--dias", type=int, default=5)
    ap.add_argument("--max-paradas", type=int, default=10)
    args = ap.parse_args(argv)
    if args.dias < 1 or args.max_paradas < 1:
        print("--dias y --max-paradas deben ser >= 1.", file=sys.stderr)
        return 2
    try:
        check_csv(Path(args.csv))
        depot = depot_from_env()
        rows, errors = parse_rows(args.csv)
        if errors:
            raise SeedError(f"{len(errors)} problemas en el CSV; corrige con seed_clientes (dry-run)")
    except SeedError as e:
        print(e, file=sys.stderr)
        return 1
    inside, outside, pending = split_rows(rows)
    days, overflow = cluster_days(inside, args.dias, args.max_paradas)
    out_dir = data_dir() / "rutas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"rutas_semana_{date.today().isoformat()}.md"
    out.write_text(build_markdown(days, depot, overflow, outside, pending), encoding="utf-8")
    print(f"{len(days)} dias, {sum(map(len, days))} paradas en Maringa, {len(overflow)} sin asignar, "
          f"{len(outside)} fuera de Maringa, {len(pending)} pendientes de ubicar. Archivo escrito en rutas/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
