"""Carga las calles de MARINGÁ (solo ese municipio) y cruza el volcado de la Receita con OSM.

    python scripts/cargar_calles_osm.py                       # usa el volcado de <RASTREADOR_DATA_DIR>/maringa
    python scripts/cargar_calles_osm.py --dump ruta.ESTABELE --refresh

- Volcado: solo filas con municipio Receita 7691. Se leen dirección y situación; nada de negocios/contacto.
- OSM: Overpass, vías con nombre dentro del área del límite con IBGE:GEOCODIGO=4115200 (no por nombre).
  Se cachea en <RASTREADOR_DATA_DIR>/osm/. La petición no lleva ningún dato de clientes.
- Salida en <RASTREADOR_DATA_DIR>/osm/: calles_maringa.json (índice) y calles_maringa_sin_cruzar.csv.
- No escribe en la base de datos: eso va después de validar la tasa de cruce.
"""

import argparse
import csv
import glob
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from app.services import streets as S  # noqa: E402


def main(argv=None) -> int:
    data_dir = os.environ.get("RASTREADOR_DATA_DIR") or os.path.join(REPO_ROOT, ".data")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--municipio", default=S.MARINGA_IBGE, help="solo se admite 4115200 (Maringá)")
    p.add_argument("--dump", help=".ESTABELE de la Receita (por defecto el último de <data>/maringa)")
    p.add_argument("--refresh", action="store_true", help="vuelve a descargar de Overpass aunque haya caché")
    p.add_argument("--umbral-largo-m", type=float, default=S.CALLE_LARGA_M)
    p.add_argument("--umbral-largo-comercios", type=int, default=S.CALLE_LARGA_COMERCIOS)
    args = p.parse_args(argv)

    if args.municipio != S.MARINGA_IBGE:
        print(f"Solo se cargan calles de Maringá (IBGE {S.MARINGA_IBGE}); recibido {args.municipio!r}.", file=sys.stderr)
        return 2
    dump = args.dump or (sorted(glob.glob(os.path.join(data_dir, "maringa", "*.ESTABELE")) or [""])[-1])
    if not dump or not os.path.exists(dump):
        print("No encuentro el volcado .ESTABELE (usa --dump).", file=sys.stderr)
        return 1

    osm_dir = os.path.join(data_dir, "osm")
    try:
        osm = S.fetch_osm_streets(osm_dir, S.MARINGA_IBGE, refresh=args.refresh)
    except Exception as e:  # class name only: no URLs/bodies in output
        print(f"Fallo al obtener OSM ({type(e).__name__}).", file=sys.stderr)
        return 1

    report = S.match_streets(
        S.build_dump_index(dump), S.index_osm_ways(osm), args.umbral_largo_m, args.umbral_largo_comercios
    )
    with open(os.path.join(osm_dir, "calles_maringa.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False)
    with open(os.path.join(osm_dir, "calles_maringa_sin_cruzar.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tipo", "nombre", "comercios_activos"])
        w.writerows([r["tipo"], r["nome"], r["n_comercios_ativos"]] for r in report["sin_cruzar"])
    print(json.dumps(report["resumen"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
