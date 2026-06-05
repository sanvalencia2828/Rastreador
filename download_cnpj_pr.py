#!/usr/bin/env python3
"""
download_cnpj_pr.py
===================
Script optimizado para el pipeline de datos de CNPJ de Paraná.
Se conecta a la fuente de datos procesados del repositorio:
https://github.com/ricardonascimentosoares/dados-abertos-cnpj

Este script lee la base de datos DuckDB (dados_abertos_cnpj.db) y aplica los
filtros de negocio para la UF 'PR', municipios de interés y CNAEs objetivo.

Autor: Data Engineer
Fecha: 2026-06-02
"""

import os
import sys
import json
import duckdb

# ============================================================
# CONFIG
# ============================================================
DB_FILE = "cnpj_data/dados_abertos_cnpj.db"
OUTPUT_FILE = "londrina_businesses.json"
REMOTE_GDRIVE_URL = "https://drive.usercontent.google.com/download?id=1SgMhyuMWgBWrrBc5H-Raj_-hJlK8k1y8&confirm=t"

TARGET_MUNICIPIOS = ['LONDRINA', 'CAMBE', 'IBIPORA', 'APUCARANA', 'JANDAIA DO SUL']

MUN_NAME_MAP = {
    'LONDRINA': 'Londrina',
    'CAMBE': 'Cambé',
    'IBIPORA': 'Ibiporã',
    'APUCARANA': 'Apucarana',
    'JANDAIA DO SUL': 'Jandaia do Sul'
}

RETAIL_CNAE_CODES = {
    4711301, 4711302, 4712100, 4713000, 4721101, 4721102, 4721103,
    4722901, 4722902, 4723700, 4724500, 4729601, 4729602, 4729603,
    4729699, 4731800, 4732600, 4741500, 4742300, 4743100, 4744001,
    4744002, 4744003, 4751201, 4751202, 4752100, 4753900, 4754701,
    4754702, 4755501, 4755502, 4756300, 4757100, 4759801, 4759899,
    4761001, 4761002, 4761003, 4762800, 4763601, 4763602, 4763603,
    4763604, 4763605, 4771701, 4771702, 4771703, 4771704, 4771705,
    4771706, 4771799, 4772500, 4773300, 4774100, 4781400, 4782201,
    4782202, 4783101, 4783102, 4784900, 4785701, 4785702, 4785799,
    4789001, 4789002, 4789099
}

GASTRONOMY_CNAE_CODES = {
    5611201, 5611202, 5611203, 5611204, 5611205, 5612100, 5613900,
    5620101, 5620102, 5620103, 5620104
}

TECH_CNAE_CODES = {
    6201501, 6202300, 6203100, 6204000, 6209100, 6311900, 6319400,
    6120501, 6120502, 6190601, 6190699,
    4651601, 4651602, 4661300, 2621300, 2622100,
    4751201, 4751202, 4752100, 4753900,
    4651400, 4652200, 4652201, 4652202,
    6110801, 6110802, 6110803, 6130200, 6190602,
    9511800, 9512600,
    8599603
}

REPAIRS_CNAE_CODES = {
    9511800, 9512600, 9521500, 9529104, 9529199
}

ALL_CNAES = RETAIL_CNAE_CODES | GASTRONOMY_CNAE_CODES | TECH_CNAE_CODES | REPAIRS_CNAE_CODES

# ============================================================
# HELPERS
# ============================================================
def safe_int(val):
    """Safely convert value to integer if possible, else return string or None."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    val_str = str(val).strip()
    if val_str.isdigit():
        return int(val_str)
    try:
        return int(float(val_str))
    except ValueError:
        return val_str

# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    print("=" * 60)
    print("  Data Pipeline CNPJ - Parana (DuckDB Optimizado)")
    print("  Repositorio: ricardonascimentosoares/dados-abertos-cnpj")
    print("=" * 60)

    # 1. Establecer conexión con la base de datos DuckDB
    conn = None
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 100 * 1024:
        print(f"[1/4] Conectando a la base de datos local: {DB_FILE}...")
        try:
            conn = duckdb.connect(DB_FILE)
        except Exception as e:
            print(f"Error conectando a DuckDB local: {e}")
    
    if conn is None:
        print(f"[1/4] Intentando conectar a la fuente remota: {REMOTE_GDRIVE_URL}...")
        try:
            conn = duckdb.connect()
            conn.execute("INSTALL httpfs;")
            conn.execute("LOAD httpfs;")
            conn.execute(f"ATTACH '{REMOTE_GDRIVE_URL}' AS remote_db (TYPE DUCKDB, READ_ONLY);")
            conn.execute("USE remote_db;")
            print("  Conexión remota exitosa!")
        except Exception as e:
            print(f"  No se pudo conectar a la base de datos remota (posible límite de cuota superado): {e}")
            print(f"  Por favor, asegúrate de colocar el archivo 'dados_abertos_cnpj.db' en la ruta '{DB_FILE}'")
            sys.exit(1)

    # 2. Ejecutar consulta SQL optimizada con los filtros requeridos
    print("\n[2/4] Ejecutando consulta SQL en DuckDB con las reglas de negocio...")
    
    cnaes_str = ",".join(map(str, ALL_CNAES))
    muns_str = ",".join(f"'{m}'" for m in TARGET_MUNICIPIOS)
    
    query = f"""
    SELECT 
        e.cnpj_basico,
        e.cnpj_ordem,
        e.cnpj_dv,
        e.nome_fantasia,
        CAST(e.codigo_cnae_fiscal_principal AS VARCHAR) as cnae_fiscal_principal,
        e.logradouro,
        e.numero,
        e.bairro,
        e.cep,
        e.telefone_1,
        emp.codigo_porte_empresa as porte_empresa,
        upper(trim(m.descricao)) as municipio_name,
        e.codigo_cnae_fiscal_principal
    FROM estabelecimentos e
    JOIN municipios m ON e.codigo_municipio = m.codigo
    LEFT JOIN empresas emp ON e.cnpj_basico = emp.cnpj_basico
    WHERE e.uf = 'PR'
      AND e.codigo_situacao_cadastral = 2
      AND upper(trim(m.descricao)) IN ({muns_str})
      AND e.codigo_cnae_fiscal_principal IN ({cnaes_str})
    """
    
    try:
        results = conn.execute(query).fetchall()
        print(f"  Consulta finalizada. Registros extraídos: {len(results)}")
    except Exception as e:
        print(f"Error ejecutando consulta: {e}")
        conn.close()
        sys.exit(1)

    # 3. Procesar y clasificar los registros según tipo de negocio
    print("\n[3/4] Clasificando y formateando registros para el JSON...")
    
    records = []
    repairs_count = 0
    type_counts = {"retail": 0, "repairs": 0, "gastronomy": 0, "tech": 0}
    mun_counts = {}

    for row in results:
        # Column mappings
        cnpj_basico = row[0]
        cnpj_ordem = row[1]
        cnpj_dv = row[2]
        nome_fantasia = row[3]
        cnae_fiscal_principal = row[4]
        logradouro = row[5]
        numero = row[6]
        bairro = row[7]
        cep = row[8]
        telefone_1 = row[9]
        porte_empresa = row[10]
        mun_raw = row[11]
        cnae_int = row[12]

        # Classification
        if cnae_int in TECH_CNAE_CODES:
            btype = "tech"
        elif cnae_int in REPAIRS_CNAE_CODES:
            btype = "repairs"
            repairs_count += 1
        elif cnae_int in RETAIL_CNAE_CODES:
            btype = "retail"
        else:
            btype = "gastronomy"

        type_counts[btype] += 1
        
        # Proper case municipality name
        municipio = MUN_NAME_MAP.get(mun_raw, mun_raw.title() if mun_raw else "")
        mun_counts[municipio] = mun_counts.get(municipio, 0) + 1

        record = {
            "cnpj_basico":            safe_int(cnpj_basico),
            "cnpj_ordem":             safe_int(cnpj_ordem),
            "cnpj_dv":                safe_int(cnpj_dv),
            "nome_fantasia":          nome_fantasia or None,
            "cnae_fiscal_principal":  cnae_fiscal_principal,
            "logradouro":             logradouro or "",
            "numero":                 safe_int(numero),
            "bairro":                 bairro or "",
            "cep":                    safe_int(cep),
            "telefone_1":             safe_int(telefone_1),
            "porte_empresa":          safe_int(porte_empresa),
            "municipio":              municipio,
            "business_type":          btype
        }
        records.append(record)

    conn.close()

    # 4. Guardar archivo final
    print(f"\n[4/4] Guardando entregable en {OUTPUT_FILE}...")
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"  [OK] Guardado exitoso: {len(records)} registros escritos.")
    except Exception as e:
        print(f"Error escribiendo archivo JSON: {e}")
        sys.exit(1)

    # Impresión de Verificación
    print("\n" + "=" * 60)
    print("  MÉTRICAS DE VERIFICACIÓN (RESUMEN)")
    print("=" * 60)
    print(f"Total registros importados:  {len(records)}")
    print(f"Sectores (business_type):")
    for k, v in type_counts.items():
        print(f"  - {k:11s}: {v}")
    print(f"Municipios:")
    for k, v in mun_counts.items():
        print(f"  - {k:15s}: {v}")
    print("=" * 60)
    print("Proceso completado con exito!")

if __name__ == "__main__":
    main()
