"""Carga el catálogo de calles de Maringá en la base (street_catalog + street_segments).

    python scripts/cargar_calles_osm.py            # 1) genera calles_maringa.json (cruce elegido)
    python scripts/cargar_calles_db.py             # 2) dry-run: cuántas filas escribiría
    python scripts/cargar_calles_db.py --apply     # 3) reemplaza el catálogo de MARINGA en la base

Es reemplazo completo del snapshot de MARINGA (catálogo y tramos); street_time_log no se toca. Solo datos
públicos agregados por calle (contadores, rango de numeración, CEP, geometría OSM): nada de negocios ni contacto.
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from sqlalchemy import text  # noqa: E402

from app.services import streets as S  # noqa: E402

MUNICIPIO = "MARINGA"


def main(argv=None) -> int:
    data_dir = os.environ.get("RASTREADOR_DATA_DIR") or os.path.join(REPO_ROOT, ".data")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report", default=os.path.join(data_dir, "osm", "calles_maringa.json"))
    p.add_argument("--apply", action="store_true", help="escribe en la base (sin esto solo informa)")
    p.add_argument("--radio-casco-m", type=float, default=S.RADIO_CASCO_M)
    args = p.parse_args(argv)

    if not os.path.exists(args.report):
        print("Falta calles_maringa.json: ejecuta antes scripts/cargar_calles_osm.py.", file=sys.stderr)
        return 1
    report = json.load(open(args.report, encoding="utf-8"))
    if report.get("municipio_ibge") != S.MARINGA_IBGE:
        print("El informe no es de Maringá (IBGE 4115200).", file=sys.stderr)
        return 2
    rows = report["calles"]
    needed = {r["osm_key"] for r in rows if r.get("osm_key")}
    osm = S.fetch_osm_streets(os.path.join(data_dir, "osm"), S.MARINGA_IBGE)
    segments = S.osm_segments(osm, needed, radio_m=args.radio_casco_m)
    print(f"{len(rows)} calles de catálogo ({len(needed)} con geometría OSM), {len(segments)} tramos.")
    if not args.apply:
        print("Dry-run: no se escribió nada. Usa --apply.")
        return 0

    from app.core.database import db_engine
    from app.db.bootstrap import STREETS_DDL

    if db_engine is None:
        print("No hay base de datos configurada (DATABASE_URL o DB_*).", file=sys.stderr)
        return 1
    catalog = [
        {"m": MUNICIPIO, "key": r["street_key"], "osm_key": r.get("osm_key"), "tipo": r["tipo"], "nombre": r["nome"],
         "n": r["n_comercios_ativos"], "nmin": r["numero_min"], "nmax": r["numero_max"], "sn": r["sem_numero"],
         "ceps": r["ceps"], "len": r["length_m"], "par": r["pareado_pct"], "spr": r["spread_m"],
         "mt": r["match_type"], "estado": r["estado"], "plan": r["en_plan_automatico"]}
        for r in rows
    ]
    segs = [
        {"m": MUNICIPIO, "osm_id": oid, "key": key, "name": name[:255], "len": length,
         "wkt": "LINESTRING(" + ", ".join(f"{lon:.7f} {lat:.7f}" for lon, lat in pts) + ")"}
        for oid, key, name, pts, length in segments
    ]
    try:
        with db_engine.begin() as conn:
            conn.execute(text(STREETS_DDL))
            conn.execute(text("DELETE FROM street_segments WHERE municipio = :m"), {"m": MUNICIPIO})
            conn.execute(text("DELETE FROM street_catalog WHERE municipio = :m"), {"m": MUNICIPIO})
            if catalog:
                conn.execute(text(
                    "INSERT INTO street_catalog (municipio, street_key, osm_key, tipo, nombre, n_comercios_activos,"
                    " numero_min, numero_max, sin_numero, ceps, length_m, pareado_pct, spread_m, match_type, estado,"
                    " en_plan_automatico) VALUES (:m, :key, :osm_key, :tipo, :nombre, :n, :nmin, :nmax, :sn, :ceps,"
                    " :len, :par, :spr, :mt, :estado, :plan)"), catalog)
            if segs:
                conn.execute(text(
                    "INSERT INTO street_segments (osm_id, name, geom, length_m, municipio, street_key) VALUES"
                    " (:osm_id, :name, ST_GeomFromText(:wkt, 4326), :len, :m, :key)"), segs)
    except Exception as e:  # class name only
        print(f"Fallo de base de datos ({type(e).__name__}); nada se escribió.", file=sys.stderr)
        return 1
    print("Catálogo de MARINGA reemplazado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
