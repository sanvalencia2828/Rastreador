"""Carga las calles de MARINGÁ (solo ese municipio) y cruza el volcado de la Receita con OSM.

    python scripts/cargar_calles_osm.py                       # cruce EXACTO; informe y archivos en <data>/osm
    python scripts/cargar_calles_osm.py --diagnostico         # evalúa por separado los cruces opcionales (no activa nada)
    python scripts/cargar_calles_osm.py --activar flexible    # usa un cruce opcional (solo tras revisar la muestra)

- Volcado: solo filas con municipio Receita 7691. Se leen dirección y situación; nada de negocios/contacto.
  Los comercios de bairros de distrito (Floriano, Iguatemi) se cuentan aparte y no entran en el plan.
- OSM: Overpass, vías con nombre dentro del área del límite con IBGE:GEOCODIGO=4115200 (no por nombre).
  Se cachea en <RASTREADOR_DATA_DIR>/osm/. La petición no lleva ningún dato de clientes.
- Salida en <RASTREADOR_DATA_DIR>/osm/: calles_maringa.json y calles_maringa_sin_cruzar.csv.
- No escribe en la base de datos (para eso, scripts/cargar_calles_db.py).
"""

import argparse
import csv
import glob
import json
import os
import random
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from app.services import streets as S  # noqa: E402

METHODS = {"flexible": S.flexible_aliases, "ref": S.ref_aliases, "tolerancia": S.tolerance_aliases}


def build(args, data_dir):
    dump = args.dump or (sorted(glob.glob(os.path.join(data_dir, "maringa", "*.ESTABELE")) or [""])[-1])
    if not dump or not os.path.exists(dump):
        raise FileNotFoundError("volcado .ESTABELE")
    distritos = Counter()
    index = S.build_dump_index(dump, distritos=distritos)
    osm = S.fetch_osm_streets(os.path.join(data_dir, "osm"), S.MARINGA_IBGE, refresh=args.refresh)
    return index, S.index_osm_ways(osm, radio_m=args.radio_casco_m), distritos


def diagnose(index, ways, seed, n_sample, out_dir):
    """Cada método sobre el mismo punto de partida (cruce exacto), con muestra aleatoria de pares de NOMBRES."""
    base = S.match_streets(index, ways)["resumen"]
    exact_osm = {k for k, s in index.items() if S._is_exact(k, ways)}
    total_com, total_calles = base["comercios_activos"], base["calles_con_comercios_activos"]
    print(f"Base exacta: {base['cruzadas']}/{total_calles} calles, "
          f"{base['pct_comercios_en_calles_cruzadas']} % de comercios\n")
    for name, finder in METHODS.items():
        aliases = finder(index, ways)
        com = sum(index[k]["n_ativos"] for k in aliases)
        print(f"== {name}: +{len(aliases)} calles, +{com} comercios -> "
              f"{round(100 * (base['cruzadas'] + len(aliases)) / total_calles, 1)} % calles, "
              f"{round(100 * (base['comercios_en_calles_cruzadas'] + com) / total_com, 1)} % comercios")
        pairs = [
            (f"{index[k]['tipo'] or ''} {index[k]['nome']}".strip(), ways[ok]["name"],
             "OSM ya cruzada exacta por otra calle del volcado" if ok in exact_osm else "")
            for k, (ok, _) in aliases.items()
        ]
        sample = random.Random(seed).sample(pairs, min(n_sample, len(pairs)))
        with open(os.path.join(out_dir, f"muestra_{name}.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["volcado", "osm", "nota"])
            w.writerows(sample)
        for dump_name, osm_name, note in sample:
            print(f"   {dump_name}  <->  {osm_name}" + (f"   [{note}]" if note else ""))
        print()


def sensitivity(index, data_dir):
    osm = S.fetch_osm_streets(os.path.join(data_dir, "osm"), S.MARINGA_IBGE)
    print("== Sensibilidad al radio del casco (calles cruzadas por estado):")
    for radio in (8000, 10000, 12000):
        r = S.match_streets(index, S.index_osm_ways(osm, radio_m=radio))["resumen"]
        print(f"   {radio / 1000:g} km: cruzadas {r['cruzadas']}, por estado {r['por_estado']}, "
              f"comercios en plan {r['comercios_en_plan_automatico']}")


def main(argv=None) -> int:
    data_dir = os.environ.get("RASTREADOR_DATA_DIR") or os.path.join(REPO_ROOT, ".data")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--municipio", default=S.MARINGA_IBGE, help="solo se admite 4115200 (Maringá)")
    p.add_argument("--dump", help=".ESTABELE de la Receita (por defecto el último de <data>/maringa)")
    p.add_argument("--refresh", action="store_true", help="vuelve a descargar de Overpass aunque haya caché")
    p.add_argument("--umbral-largo-m", type=float, default=S.CALLE_LARGA_M)
    p.add_argument("--umbral-largo-comercios", type=int, default=S.CALLE_LARGA_COMERCIOS)
    p.add_argument("--radio-casco-m", type=float, default=S.RADIO_CASCO_M)
    p.add_argument("--diagnostico", action="store_true", help="evalúa los cruces opcionales sin activarlos")
    p.add_argument("--activar", choices=sorted(METHODS), nargs="*", default=[], help="cruces opcionales a usar")
    p.add_argument("--muestra", type=int, default=30)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)

    if args.municipio != S.MARINGA_IBGE:
        print(f"Solo se cargan calles de Maringá (IBGE {S.MARINGA_IBGE}); recibido {args.municipio!r}.", file=sys.stderr)
        return 2
    try:
        index, ways, distritos = build(args, data_dir)
    except FileNotFoundError:
        print("No encuentro el volcado .ESTABELE (usa --dump).", file=sys.stderr)
        return 1
    except Exception as e:  # class name only: no URLs/bodies in output
        print(f"Fallo al obtener OSM ({type(e).__name__}).", file=sys.stderr)
        return 1

    osm_dir = os.path.join(data_dir, "osm")
    if args.diagnostico:
        diagnose(index, ways, args.seed, args.muestra, osm_dir)
        sensitivity(index, data_dir)
        return 0

    aliases = {}
    for name in args.activar:
        for k, v in METHODS[name](index, ways).items():
            aliases.setdefault(k, v)
    report = S.match_streets(index, ways, aliases, args.umbral_largo_m, args.umbral_largo_comercios, distritos=distritos)
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
