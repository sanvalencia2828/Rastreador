#!/usr/bin/env python3
"""Carga filtered.csv (Receita, 30 columnas) en estabelecimentos de PROD_DATABASE_URL.

Por defecto es DRY-RUN de solo lectura. Insertar exige --apply.
Uso: python load_filtered_cnpj.py <filtered.csv> [--apply] [--skip-bad] [--no-db] [--encoding ENC]

--no-db     solo valida el CSV (no se conecta a ninguna base).
--skip-bad  permite --apply aunque haya filas con error de formato (se omiten).
"""
import argparse
import csv
import os
import sys
from collections import Counter

import psycopg2
import psycopg2.extras

MUN = {"7425": "Apucarana", "7427": "Arapongas", "7691": "Maringá"}
TECH = {"6201501", "6202300", "6209100"}


def prod_url() -> str:
    if "PROD_DATABASE_URL" not in os.environ and os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "PROD_DATABASE_URL":
                os.environ[k] = v.strip("'\"")
    return os.environ["PROD_DATABASE_URL"]


def row_to_dict(r):
    return {
        "cnpj_basico": r[0].zfill(8), "cnpj_ordem": r[1].zfill(4), "cnpj_dv": r[2].zfill(2),
        "cnpj_completo": r[0].zfill(8) + r[1].zfill(4) + r[2].zfill(2),
        "identificador_matriz_filial": int(r[3]) if r[3].isdigit() else None,
        "nome_fantasia": r[4].strip() or None, "situacao_cadastral": int(r[5]),
        "cnae_fiscal": r[11], "logradouro": r[14].strip(), "numero": r[15].strip(),
        "bairro": r[17].strip(), "cep": r[18].strip() or None, "uf": "PR",
        "codigo_municipio": r[20], "municipio": MUN[r[20]],
        "ddd_1": r[21].strip() or None, "telefone_1": r[22].strip() or None,
        "correio_eletronico": r[27].strip() or None,
        "business_type": "tech" if r[11] in TECH else "repairs",
    }


INSERT_SQL = """
INSERT INTO estabelecimentos (
    cnpj_basico, cnpj_ordem, cnpj_dv, cnpj_completo, identificador_matriz_filial,
    nome_fantasia, situacao_cadastral, cnae_fiscal, logradouro, numero, bairro, cep,
    uf, codigo_municipio, municipio, ddd_1, telefone_1, correio_eletronico,
    business_type, geocoded
) VALUES (
    %(cnpj_basico)s, %(cnpj_ordem)s, %(cnpj_dv)s, %(cnpj_completo)s, %(identificador_matriz_filial)s,
    %(nome_fantasia)s, %(situacao_cadastral)s, %(cnae_fiscal)s, %(logradouro)s, %(numero)s,
    %(bairro)s, %(cep)s, %(uf)s, %(codigo_municipio)s, %(municipio)s, %(ddd_1)s, %(telefone_1)s,
    %(correio_eletronico)s, %(business_type)s, FALSE
)
ON CONFLICT (cnpj_completo) DO UPDATE SET
    nome_fantasia = EXCLUDED.nome_fantasia, cnae_fiscal = EXCLUDED.cnae_fiscal,
    logradouro = EXCLUDED.logradouro, numero = EXCLUDED.numero, bairro = EXCLUDED.bairro,
    municipio = EXCLUDED.municipio, business_type = EXCLUDED.business_type,
    situacao_cadastral = EXCLUDED.situacao_cadastral
"""


def parse_rows(path, encoding="utf-8"):
    """Devuelve (filas_validas, rechazadas); rechazada = (linea, motivo, detalle).

    Motivos con error de formato: 'corta', 'municipio_desconocido', 'formato'.
    'inactiva' (situacao_cadastral != 2) se omite sin considerarse error.
    """
    rows, rejected = [], []
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        for r in reader:
            line = reader.line_num
            if len(r) < 30:
                rejected.append((line, "corta", f"{len(r)} columnas"))
            elif r[20] not in MUN:
                rejected.append((line, "municipio_desconocido", r[20]))
            elif r[5].strip() != "2":
                rejected.append((line, "inactiva", f"situacao_cadastral={r[5]!r}"))
            else:
                try:
                    rows.append(row_to_dict(r))
                except (ValueError, IndexError) as e:
                    rejected.append((line, "formato", repr(e)))
    return rows, rejected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--skip-bad", action="store_true")
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--encoding", default="utf-8")
    args = ap.parse_args()
    apply = args.apply
    if apply and args.no_db:
        sys.exit("--apply y --no-db son incompatibles.")
    rows, rejected = parse_rows(args.path, args.encoding)
    by_reason = Counter(m for _, m, _ in rejected)
    bad_format = sum(n for m, n in by_reason.items() if m != "inactiva")
    print(f"filas válidas: {len(rows)}   rechazadas: {len(rejected)}")
    for m, n in sorted(by_reason.items()):
        print(f"  {m}: {n}")
    for line, m, d in rejected[:20]:
        print(f"  línea {line}: {m} ({d})")
    if apply and bad_format and not args.skip_bad:
        sys.exit(f"{bad_format} filas con error de formato: --apply se niega. "
                 "Corrige el CSV o usa --skip-bad para omitirlas.")
    if args.no_db:
        print("--no-db: solo validación, sin conexión a la base.")
        return
    conn = psycopg2.connect(prod_url())
    conn.set_session(readonly=not apply)
    cur = conn.cursor()
    cur.execute("SELECT cnpj_completo FROM estabelecimentos WHERE cnpj_completo = ANY(%s)",
                ([r["cnpj_completo"] for r in rows],))
    existing = {x[0] for x in cur.fetchall()}
    new, upd = Counter(), Counter()
    for r in rows:
        (upd if r["cnpj_completo"] in existing else new)[r["municipio"]] += 1
    print(f"{'ciudad':<12}{'nuevas':>8}{'update':>8}{'total':>8}")
    for m in MUN.values():
        print(f"{m:<12}{new[m]:>8}{upd[m]:>8}{new[m] + upd[m]:>8}")
    print(f"{'TOTAL':<12}{sum(new.values()):>8}{sum(upd.values()):>8}{len(rows):>8}")
    if not apply:
        print("DRY-RUN: no se escribió nada.")
        return
    psycopg2.extras.execute_batch(cur, INSERT_SQL, rows, page_size=500)
    conn.commit()
    print(f"INSERT/UPDATE aplicado: {len(rows)} filas.")


if __name__ == "__main__":
    main()
