#!/usr/bin/env python3
"""
scripts/descargar_maringa.py
Descarga el volcado CNPJ más reciente de la Receita Federal (las 10 partes de
Estabelecimentos) y se queda solo con los establecimientos de los municipios
pedidos (Maringá por defecto). Lee cada ZIP en streaming: nunca descomprime los
~5 GB a disco y el resultado pesa pocas decenas de MB.

Fuente oficial (carpetas mensuales AAAA-MM):
    https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9

Uso:
    python scripts/descargar_maringa.py --mes 2026-09
    python scripts/descargar_maringa.py --mes 2026-09 --municipios 7691,8461,7731,7687   # región de Maringá
    python scripts/descargar_maringa.py --zips "C:/Users/santi/Downloads/Estabelecimentos*.zip"   # ZIPs ya bajados a mano

Salida: .data/maringa/<mes>_<municipios>.ESTABELE con el mismo formato crudo de la
Receita. Va en su propia carpeta para no mezclarse con otros volcados:
    ML__DATA__INPUT_GLOB=".data/maringa/2026-09_*" python -m ml run
    python scripts/analizar_zonas.py --estabelecimentos ".data/maringa/2026-09_*"

Códigos de municipio de la Receita (no son IBGE), verificados por CEP en el volcado:
Maringá 7691 · Sarandi 8461 · Paiçandu 7731 · Marialva 7687 · Londrina 7667 · Cambé 7471.
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
import os
import sys
import time
import urllib.request
import zipfile

SHARE = "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9"
UF_IDX, MUNICIPIO_IDX, N_COLS = 19, 20, 30


def candidate_urls(month: str, name: str) -> list[str]:
    token = SHARE.rsplit("/", 1)[-1]
    base = SHARE.split("/index.php")[0]
    return [
        f"{SHARE}/download?path=/{month}&files={name}",
        f"{base}/public.php/dav/files/{token}/{month}/{name}",
    ]


def download(month: str, name: str, dest: str) -> str:
    if os.path.exists(dest) and zipfile.is_zipfile(dest):
        print(f"  {name}: ya descargado")
        return dest
    last_error: Exception | None = None
    for url in candidate_urls(month, name):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "rastreador-cnpj/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest + ".part", "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done, t0 = 0, time.time()
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {name}: {done / 1e6:,.0f}/{total / 1e6:,.0f} MB "
                              f"({done / max(time.time() - t0, 1e-6) / 1e6:.1f} MB/s)", end="")
            print()
            if not zipfile.is_zipfile(dest + ".part"):
                raise ValueError("la respuesta no es un ZIP (¿cambió la URL o el mes no existe?)")
            os.replace(dest + ".part", dest)
            return dest
        except Exception as err:  # prueba la siguiente forma de URL
            last_error = err
    raise SystemExit(f"No se pudo descargar {name} de {month}: {last_error}\n"
                     f"Descárgalo a mano desde {SHARE} y usa --zips.")


def filter_zip(path: str, municipios: set[str], writer: csv.writer) -> tuple[int, int]:
    read = kept = 0
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                for row in csv.reader(text, delimiter=";", quotechar='"'):
                    read += 1
                    if len(row) != N_COLS:
                        raise SystemExit(f"{member}: fila con {len(row)} columnas (se esperaban {N_COLS}); "
                                         "el layout cambió, revisar ml/contracts/estabelecimentos_raw.yaml")
                    if row[MUNICIPIO_IDX] in municipios and row[UF_IDX] == "PR":
                        writer.writerow(row)
                        kept += 1
    return read, kept


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mes", help="carpeta AAAA-MM de la Receita (la más reciente publicada)")
    p.add_argument("--municipios", default="7691", help="códigos Receita separados por coma (7691 = Maringá)")
    p.add_argument("--zips", help="glob de ZIPs ya descargados (omite la descarga)")
    p.add_argument("--descargas", default=".data/receita", help="carpeta para los ZIPs")
    p.add_argument("--borrar-zips", action="store_true", help="borra cada ZIP después de filtrarlo")
    args = p.parse_args()
    municipios = {m.strip() for m in args.municipios.split(",") if m.strip()}

    if args.zips:
        zips = sorted(glob.glob(args.zips))
        label = "manual"
    elif args.mes:
        os.makedirs(args.descargas, exist_ok=True)
        zips = [os.path.join(args.descargas, args.mes, f"Estabelecimentos{i}.zip") for i in range(10)]
        os.makedirs(os.path.dirname(zips[0]), exist_ok=True)
        label = args.mes
    else:
        p.error("indica --mes AAAA-MM o --zips")
    if not zips:
        raise SystemExit("No se encontraron ZIPs")

    os.makedirs(os.path.join(".data", "maringa"), exist_ok=True)
    out_path = os.path.join(".data", "maringa", f"{label}_{'-'.join(sorted(municipios))}.ESTABELE")
    total_read = total_kept = 0
    with open(out_path, "w", encoding="latin-1", newline="") as out:
        writer = csv.writer(out, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL, lineterminator="\n")
        for path in zips:
            if args.mes and not args.zips:
                download(args.mes, os.path.basename(path), path)
            read, kept = filter_zip(path, municipios, writer)
            total_read += read
            total_kept += kept
            print(f"  {os.path.basename(path)}: {read:,} filas · {kept:,} de {sorted(municipios)}")
            if args.borrar_zips:
                os.remove(path)
    print(f"\nListo: {total_kept:,} establecimientos de {total_read:,} → {out_path}")
    if total_kept == 0:
        print("Advertencia: 0 filas. ¿Código de municipio correcto? (Receita, no IBGE)", file=sys.stderr)


if __name__ == "__main__":
    main()
