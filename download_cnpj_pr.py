#!/usr/bin/env python3
"""
download_cnpj_pr.py
===================
Script para descargar y procesar los datos reales de CNPJ del Paraná
directamente desde la Receita Federal / dados.gov.br.

Flujo:
  1. Consulta la API de dados.gov.br para obtener los URLs de descarga actuales
  2. Descarga los archivos Estabelecimentos*.zip más recientes
  3. Descomprime y filtra solo los registros del PR (municipios de Londrina y región)
  4. Guarda el resultado en londrina_businesses.json (mismo formato que el ETL existente)

Uso:
  python download_cnpj_pr.py
"""

import os
import sys
import json
import zipfile
import urllib.request
import io
import csv
import time

# ============================================================
# CONFIG
# ============================================================
IBGE_MUNICIPIOS = {
    4113700: "Londrina",
    4103701: "Cambé",
    4109807: "Ibiporã",
    4101408: "Apucarana",
    4112108: "Jandaia do Sul",
}

RETAIL_CNAE_CODES = {
    '4711301', '4711302', '4712100', '4713000', '4721101', '4721102', '4721103',
    '4722901', '4722902', '4723700', '4724500', '4729601', '4729602', '4729603',
    '4729699', '4731800', '4732600', '4741500', '4742300', '4743100', '4744001',
    '4744002', '4744003', '4751201', '4751202', '4752100', '4753900', '4754701',
    '4754702', '4755501', '4755502', '4756300', '4757100', '4759801', '4759899',
    '4761001', '4761002', '4761003', '4762800', '4763601', '4763602', '4763603',
    '4763604', '4763605', '4771701', '4771702', '4771703', '4771704', '4771705',
    '4771706', '4771799', '4772500', '4773300', '4774100', '4781400', '4782201',
    '4782202', '4783101', '4783102', '4784900', '4785701', '4785702', '4785799',
    '4789001', '4789002', '4789099',
}
GASTRONOMY_CNAE_CODES = {
    '5611201', '5611202', '5611203', '5611204', '5611205', '5612100', '5613900',
    '5620101', '5620102', '5620103', '5620104',
}
TECH_CNAE_CODES = {
    '6201501', '6202300', '6203100', '6204000', '6209100', '6311900', '6319400',
    '6120501', '6120502', '6190601', '6190699',
    '4651601', '4651602', '4661300', '2621300', '2622100',
}
REPAIRS_CNAE_CODES = {
    '9511800', '9512600', '9521500', '9529104', '9529199'
}
VALID_CNAE = RETAIL_CNAE_CODES | GASTRONOMY_CNAE_CODES | TECH_CNAE_CODES | REPAIRS_CNAE_CODES

OUTPUT_FILE = "londrina_businesses.json"

# Column indices in the Estabelecimentos CSV (0-indexed):
#  0:cnpj_basico  1:cnpj_ordem  2:cnpj_dv  3:identificador_matriz_filial
#  4:nome_fantasia  5:situacao_cadastral  6:data_situacao_cadastral
#  7:motivo  8:nome_cidade_exterior  9:pais  10:data_inicio_atividade
# 11:cnae_fiscal_principal  12:cnae_fiscal_secundaria
# 13:tipo_logradouro  14:logradouro  15:numero  16:complemento
# 17:bairro  18:cep  19:uf  20:codigo_municipio  21:municipio
# 22:ddd_1  23:telefone_1  ... 31:porte_empresa
COL_CNPJ_BASICO     = 0
COL_CNPJ_ORDEM      = 1
COL_CNPJ_DV         = 2
COL_NOME_FANTASIA   = 4
COL_SITUACAO        = 5
COL_CNAE            = 11
COL_LOGRADOURO      = 14
COL_NUMERO          = 15
COL_BAIRRO          = 17
COL_CEP             = 18
COL_UF              = 19
COL_COD_MUN         = 20
COL_MUNICIPIO       = 21
COL_TELEFONE        = 23
COL_PORTE           = 31

# ============================================================
# STEP 1 - Fetch current download URLs via dados.gov.br API
# ============================================================

GITHUB_REPO = "jonathands/dados-abertos-receita-cnpj"

def get_download_urls():
    """Get Estabelecimentos ZIP URLs from GitHub releases (jonathands mirror)."""
    import urllib.request, json
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=3"
    print(f"[1/4] Consultando GitHub releases de {GITHUB_REPO}...")
    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            releases = json.loads(resp.read())

        # Find the most recent release with Estabelecimentos assets
        for rel in releases:
            assets = rel.get("assets", [])
            estab_urls = [
                a["browser_download_url"]
                for a in assets
                if a["name"].startswith("Estabelecimentos") and a["name"].endswith(".zip")
            ]
            if estab_urls:
                print(f"    Release encontrado: {rel['tag_name']} con {len(estab_urls)} archivos Estabelecimentos.")
                return sorted(estab_urls)  # Estabelecimentos0.zip first

        print("    No se encontraron assets Estabelecimentos en los releases recientes.")
        return []
    except Exception as e:
        print(f"    Error consultando GitHub API: {e}")
        return []


# ============================================================
# STEP 2 - Stream download + filter in-memory
# ============================================================

def process_zip_stream(url: str, all_records: list) -> int:
    """Download a ZIP in streaming mode, filter PR records, append to list."""
    print(f"    Descargando: {url.split('/')[-1]} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = resp.headers.get("Content-Length", "?")
            data = bytearray()
            chunk_size = 1024 * 1024  # 1MB chunks
            downloaded = 0
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                data.extend(chunk)
                downloaded += len(chunk)
                mb = downloaded / (1024 * 1024)
                sys.stdout.write(f"\r      {mb:.1f} MB descargados...")
                sys.stdout.flush()
            print()

        zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
        csv_name = zf.namelist()[0]
        print(f"      Procesando {csv_name}...")

        added = 0
        with zf.open(csv_name) as csv_file:
            reader = csv.reader(
                io.TextIOWrapper(csv_file, encoding="latin1", errors="replace"),
                delimiter=";"
            )
            for row in reader:
                if len(row) < 22:
                    continue
                # Filter: active (situacao=2) + target municipalities + valid CNAE
                try:
                    situacao = row[COL_SITUACAO].strip()
                    if situacao != "2":
                        continue
                    cod_mun_raw = row[COL_COD_MUN].strip()
                    if not cod_mun_raw.isdigit():
                        continue
                    cod_mun = int(cod_mun_raw)
                    if cod_mun not in IBGE_MUNICIPIOS:
                        continue
                    cnae = row[COL_CNAE].strip()
                    if cnae not in VALID_CNAE:
                        continue

                    if cnae in TECH_CNAE_CODES:
                        btype = "tech"
                    elif cnae in REPAIRS_CNAE_CODES:
                        btype = "repairs"
                    elif cnae in GASTRONOMY_CNAE_CODES:
                        btype = "gastronomy"
                    else:
                        btype = "retail"

                    record = {
                        "cnpj_basico":            row[COL_CNPJ_BASICO].strip(),
                        "cnpj_ordem":             row[COL_CNPJ_ORDEM].strip(),
                        "cnpj_dv":                row[COL_CNPJ_DV].strip(),
                        "nome_fantasia":          row[COL_NOME_FANTASIA].strip() or None,
                        "cnae_fiscal_principal":  cnae,
                        "logradouro":             row[COL_LOGRADOURO].strip(),
                        "numero":                 row[COL_NUMERO].strip(),
                        "bairro":                 row[COL_BAIRRO].strip(),
                        "cep":                    row[COL_CEP].strip(),
                        "telefone_1":             row[COL_TELEFONE].strip() if len(row) > COL_TELEFONE else "",
                        "porte_empresa":          row[COL_PORTE].strip() if len(row) > COL_PORTE else "",
                        "municipio":              IBGE_MUNICIPIOS[cod_mun],
                        "business_type":          btype,
                    }
                    all_records.append(record)
                    added += 1
                except (IndexError, ValueError):
                    continue

        print(f"      +{added} registros del PR.")
        return added

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return -1  # File doesn't exist, skip silently
        print(f"      HTTP Error {e.code}: {url}")
        return 0
    except Exception as e:
        print(f"      Error: {e}")
        return 0

def find_local_zips() -> list:
    """Find locally-downloaded Estabelecimentos*.zip files in current directory."""
    import glob
    zips = glob.glob("Estabelecimentos*.zip") + glob.glob("estabelecimentos*.zip")
    return sorted(zips)


def process_local_zip(path: str, all_records: list) -> int:
    """Process a local ZIP file already downloaded."""
    print(f"    Procesando local: {path} ...")
    try:
        zf = zipfile.ZipFile(path)
        csv_name = zf.namelist()[0]
        added = 0
        with zf.open(csv_name) as csv_file:
            reader = csv.reader(
                io.TextIOWrapper(csv_file, encoding="latin1", errors="replace"),
                delimiter=";"
            )
            for i, row in enumerate(reader):
                if len(row) < 22:
                    continue
                try:
                    situacao = row[COL_SITUACAO].strip()
                    if situacao != "2":
                        continue
                    cod_mun_raw = row[COL_COD_MUN].strip()
                    if not cod_mun_raw.isdigit():
                        continue
                    cod_mun = int(cod_mun_raw)
                    if cod_mun not in IBGE_MUNICIPIOS:
                        continue
                    cnae = row[COL_CNAE].strip()
                    if cnae not in VALID_CNAE:
                        continue
                    if cnae in TECH_CNAE_CODES:
                        btype = "tech"
                    elif cnae in REPAIRS_CNAE_CODES:
                        btype = "repairs"
                    elif cnae in GASTRONOMY_CNAE_CODES:
                        btype = "gastronomy"
                    else:
                        btype = "retail"
                    all_records.append({
                        "cnpj_basico":           row[COL_CNPJ_BASICO].strip(),
                        "cnpj_ordem":            row[COL_CNPJ_ORDEM].strip(),
                        "cnpj_dv":               row[COL_CNPJ_DV].strip(),
                        "nome_fantasia":         row[COL_NOME_FANTASIA].strip() or None,
                        "cnae_fiscal_principal": cnae,
                        "logradouro":            row[COL_LOGRADOURO].strip(),
                        "numero":                row[COL_NUMERO].strip(),
                        "bairro":                row[COL_BAIRRO].strip(),
                        "cep":                   row[COL_CEP].strip(),
                        "telefone_1":            row[COL_TELEFONE].strip() if len(row) > COL_TELEFONE else "",
                        "porte_empresa":         row[COL_PORTE].strip() if len(row) > COL_PORTE else "",
                        "municipio":             IBGE_MUNICIPIOS[cod_mun],
                        "business_type":         btype,
                    })
                    added += 1
                    if i % 500000 == 0 and i > 0:
                        sys.stdout.write(f"\r      {i:,} filas procesadas, {added} encontradas...")
                        sys.stdout.flush()
                except (IndexError, ValueError):
                    continue
        print(f"\n      +{added} registros del PR.")
        return added
    except Exception as e:
        print(f"      Error procesando {path}: {e}")
        return 0


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("  Downloader de Datos Reales CNPJ - Paraná")
    print("  Municipios: Londrina, Cambé, Ibiporã, Apucarana, Jandaia")
    print("=" * 60)

    all_records = []

    # ── Prioridad 1: ZIPs ya descargados localmente ──────────
    local_zips = find_local_zips()
    if local_zips:
        print(f"\n[AUTO] Encontrados {len(local_zips)} archivos ZIP locales:")
        for z in local_zips:
            print(f"       {z}")
        print("\n[2/4] Procesando ZIPs locales...")
        for z in local_zips:
            process_local_zip(z, all_records)
    else:
        # ── Prioridad 2: Intentar descarga automática ─────────
        print(f"\n[1/4] No hay ZIPs locales. Intentando descarga automática...")
        urls = get_download_urls()
        if not urls:
            urls = try_known_urls()

        print(f"[2/4] Probando {len(urls)} URLs...")
        for url in urls:
            result = process_zip_stream(url, all_records)
            if result > 0:
                pass
            elif result == -1:
                pass  # 404 silencioso

    if not all_records:
        print("\n" + "=" * 60)
        print("  DESCARGA MANUAL REQUERIDA")
        print("=" * 60)
        print("""
El servidor de la Receita Federal bloquea descargas automáticas.
Debés descargar los archivos manualmente desde tu navegador:

  URL: https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/

Pasos:
  1. Abrí ese URL en tu navegador
  2. Entrá a la carpeta del mes más reciente (ej: 2026-05/)
  3. Descargá los archivos: Estabelecimentos0.zip ... Estabelecimentos9.zip
     (Son ~100-200 MB cada uno. Con 1-2 archivos ya tenés suficiente para PR)
  4. Colocá los .zip en esta carpeta del proyecto
  5. Volvé a ejecutar: python download_cnpj_pr.py

⚡ TIP: Podés empezar con solo Estabelecimentos0.zip para probar.
        """)
        sys.exit(1)

    print(f"\n[3/4] Total registros filtrados: {len(all_records)}")
    types = {}
    munis = {}
    for r in all_records:
        types[r["business_type"]] = types.get(r["business_type"], 0) + 1
        munis[r["municipio"]] = munis.get(r["municipio"], 0) + 1
    print(f"    Tipos:      {types}")
    print(f"    Municipios: {munis}")

    print(f"\n[4/4] Guardando en {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    print(f"    ✅ {len(all_records)} negocios reales guardados en {OUTPUT_FILE}")
    print("\n¡Listo! Reiniciá la API de Python para usar los datos reales.")


if __name__ == "__main__":
    main()
