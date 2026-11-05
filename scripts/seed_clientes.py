#!/usr/bin/env python3
"""Load a customer CSV into the `clientes` table of an EXISTING user.

    python scripts/seed_clientes.py --csv RUTA --user USERNAME            # dry-run (default, no DB)
    python scripts/seed_clientes.py --csv RUTA --user USERNAME --apply    # writes

The CSV holds private data: keep it outside git (see .gitignore) and never print its contents.
Output is limited to counts and (line, column, code) for invalid rows; DB errors print only the
exception class, because SQLAlchemy messages embed the bound parameters.
Refuses to run with APP_ENV=production unless --confirm-production is passed.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

HEADER = ["id", "cliente", "nombre_negocio", "direccion", "bairro", "municipio", "cep", "lat", "lon", "estado", "nota"]
STATE_MAP = {"coords_del_enlace": ("ok", "usuario"), "pendiente_geocodificar": ("pendiente", None)}

UPSERT = text("""
    INSERT INTO clientes (user_id, external_id, nombre_cliente, nombre_negocio, direccion, bairro,
                          municipio, cep, lat, lon, geocode_status, geocode_source, nota)
    VALUES (:user_id, :external_id, :nombre_cliente, :nombre_negocio, :direccion, :bairro,
            :municipio, :cep, :lat, :lon, :geocode_status, :geocode_source, :nota)
    ON CONFLICT (user_id, external_id) DO UPDATE SET
        nombre_cliente = EXCLUDED.nombre_cliente, nombre_negocio = EXCLUDED.nombre_negocio,
        direccion = EXCLUDED.direccion, bairro = EXCLUDED.bairro, municipio = EXCLUDED.municipio,
        cep = EXCLUDED.cep, nota = EXCLUDED.nota,
        lat = CASE WHEN EXCLUDED.geocode_status = 'ok' THEN EXCLUDED.lat ELSE clientes.lat END,
        lon = CASE WHEN EXCLUDED.geocode_status = 'ok' THEN EXCLUDED.lon ELSE clientes.lon END,
        geocode_source = CASE WHEN EXCLUDED.geocode_status = 'ok' THEN EXCLUDED.geocode_source
                              ELSE clientes.geocode_source END,
        geocode_status = CASE WHEN EXCLUDED.geocode_status = 'ok' THEN 'ok' ELSE clientes.geocode_status END,
        updated_at = NOW()
    WHERE clientes.geocode_source IS DISTINCT FROM 'manual'
""")  # a pending CSV row must not wipe resolved coords; rows edited by hand ('manual') are never touched


class SeedError(Exception):
    """Message never contains CSV content."""


def _coord(raw: str, lo: float, hi: float):
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if lo <= value <= hi else None  # NaN/inf fail the comparison


def parse_rows(path):
    """Return (rows, errors). errors are (line, column, code) tuples: never values."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header != HEADER:
                raise SeedError("cabecera inesperada")
            raw_rows = [(reader.line_num, r) for r in reader if any(c.strip() for c in r)]
    except (csv.Error, UnicodeDecodeError, OSError) as e:
        raise SeedError(f"no se pudo leer el CSV ({type(e).__name__})") from None

    rows, errors, seen = [], [], set()
    for line, cells in raw_rows:
        if len(cells) != len(HEADER):
            errors.append((line, "*", "columnas"))
            continue
        r = dict(zip(HEADER, (c.strip() for c in cells)))
        bad = len(errors)
        status = source = lat = lon = None
        if not r["id"] or len(r["id"]) > 64:
            errors.append((line, "id", "invalido"))
        elif r["id"] in seen:
            errors.append((line, "id", "duplicado"))
        seen.add(r["id"])
        if r["estado"] not in STATE_MAP:
            errors.append((line, "estado", "desconocido"))
        else:
            status, source = STATE_MAP[r["estado"]]
            lat = _coord(r["lat"], -90, 90) if r["lat"] else None
            lon = _coord(r["lon"], -180, 180) if r["lon"] else None
            if status == "ok":
                if lat is None:
                    errors.append((line, "lat", "invalido"))
                if lon is None:
                    errors.append((line, "lon", "invalido"))
            elif r["lat"] or r["lon"]:
                errors.append((line, "lat/lon", "no_vacio"))
        if len(errors) == bad:
            rows.append({
                "external_id": r["id"], "nombre_cliente": r["cliente"], "nombre_negocio": r["nombre_negocio"],
                "direccion": r["direccion"], "bairro": r["bairro"], "municipio": r["municipio"],
                "cep": r["cep"] or None, "lat": lat, "lon": lon, "geocode_status": status,
                "geocode_source": source, "nota": r["nota"] or None,
            })
    return rows, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", required=True)
    ap.add_argument("--user", required=True, help="username of an existing user")
    ap.add_argument("--apply", action="store_true", help="write to the database (default: dry-run)")
    ap.add_argument("--confirm-production", action="store_true")
    args = ap.parse_args(argv)

    if os.environ.get("APP_ENV", "").strip().lower() == "production" and not args.confirm_production:
        print("APP_ENV=production: se niega a correr sin --confirm-production.", file=sys.stderr)
        return 2
    try:
        rows, errors = parse_rows(args.csv)
    except SeedError as e:
        print(e, file=sys.stderr)
        return 1
    if errors:
        print(f"{len(errors)} problemas en el CSV (linea, columna, codigo):", file=sys.stderr)
        for item in errors[:50]:
            print("  %s %s %s" % item, file=sys.stderr)
        return 1
    ok = sum(r["geocode_status"] == "ok" for r in rows)
    print(f"{len(rows)} filas validas ({ok} con coords, {len(rows) - ok} pendientes).")
    if not args.apply:
        print("Dry-run: no se escribio nada. Usa --apply para cargar.")
        return 0

    from app.core.database import db_engine
    from app.db.bootstrap import ensure_schema

    if db_engine is None:
        print("No hay base de datos configurada (DATABASE_URL o DB_*).", file=sys.stderr)
        return 1
    try:
        ensure_schema()
        with db_engine.begin() as conn:
            found = conn.execute(text("SELECT id FROM users WHERE username = :u"), {"u": args.user}).fetchone()
            if found is None:
                print("Usuario no encontrado (no se crea).", file=sys.stderr)
                return 1
            skipped = conn.execute(
                text("SELECT count(*) FROM clientes WHERE user_id = :u AND geocode_source = 'manual' "
                     "AND external_id = ANY(:ids)"),
                {"u": found[0], "ids": [r["external_id"] for r in rows]},
            ).scalar()
            conn.execute(UPSERT, [{**r, "user_id": found[0]} for r in rows])
    except Exception as e:  # SQLAlchemy messages embed parameters: class name only
        print(f"Fallo de base de datos ({type(e).__name__}); nada se escribio.", file=sys.stderr)
        return 1
    print(f"Cargadas {len(rows) - skipped} filas; {skipped} omitidas por estar editadas a mano (manual).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
