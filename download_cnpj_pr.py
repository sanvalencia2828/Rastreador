#!/usr/bin/env python3
"""
download_cnpj_pr.py
===================
Pipeline ETL: DuckDB (dados-abertos-cnpj) → PostgreSQL (estabelecimentos) en Railway.
Filtra estrictamente por CNAEs del sector tecnológico (Tech + Repairs)
en la región metropolitana de Londrina y ciudades cercanas.

Output: Tabla `estabelecimentos` con datos reales de Receita Federal,
listos para geocodificar via enriquecer_lojas.py
"""

import os
import sys
import duckdb
import psycopg2
import psycopg2.extras
from typing import List, Optional

# ============================================================
# CONFIG
# ============================================================
DB_FILE = "cnpj_data/dados_abertos_cnpj.db"
REMOTE_GDRIVE_URL = "https://drive.usercontent.google.com/download?id=1SgMhyuMWgBWrrBc5H-Raj_-hJlK8k1y8&confirm=t"


def load_env_list(env_key: str, default_value: str) -> List[str]:
    raw_value = os.environ.get(env_key, default_value)
    return [item.strip().upper() for item in raw_value.split(",") if item.strip()]


TARGET_MUNICIPIOS = load_env_list(
    "TARGET_MUNICIPIOS", "LONDRINA,CAMBE,IBIPORA,APUCARANA,JANDAIA DO SUL"
)

MUN_NAME_MAP = {
    "LONDRINA": "Londrina",
    "CAMBE": "Cambé",
    "IBIPORA": "Ibiporã",
    "APUCARANA": "Apucarana",
    "JANDAIA DO SUL": "Jandaia do Sul",
}

TECH_CNAE_CODES = {6201501, 6202300, 6209100}

REPAIRS_CNAE_CODES = {9511800, 9512600}

ALL_CNAES = TECH_CNAE_CODES | REPAIRS_CNAE_CODES


# ============================================================
# HELPERS
# ============================================================
def safe_int(val):
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


def normalize_municipio(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    raw = raw.strip()
    # Intentar decodificar como UTF-8 limpio
    try:
        raw.encode("utf-8").decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Si hay bytes Latin-1 malinterpretados como UTF-8, reparar
    try:
        raw_bytes = raw.encode("latin-1")
        fixed = raw_bytes.decode("utf-8")
        return fixed.upper()
    except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
        return raw.upper()


def get_db_connection() -> psycopg2.extensions.connection:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_user = os.environ.get("DB_USER", "postgres")
        db_password = os.environ.get("DB_PASSWORD", "postgres")
        db_host = os.environ.get("DB_HOST", "localhost")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "londrina_comercio")
        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    conn = psycopg2.connect(db_url)
    conn.set_client_encoding("UTF8")
    return conn


def ensure_table_schema(conn: psycopg2.extensions.connection) -> None:
    cursor = conn.cursor()
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    cursor.execute("""
        ALTER TABLE estabelecimentos
        ADD COLUMN IF NOT EXISTS business_type VARCHAR(20);
    """)
    cursor.execute("""
        ALTER TABLE estabelecimentos
        ADD COLUMN IF NOT EXISTS geocoded BOOLEAN DEFAULT FALSE;
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_estabelecimentos_geocoded
        ON estabelecimentos(geocoded);
    """)
    conn.commit()
    cursor.close()


# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore

    print("=" * 60)
    print("  Data Pipeline CNPJ - Sector Tech (DuckDB → PostgreSQL)")
    print("  Filtro: Tech + Repairs | Municipios: 5 RML")
    print("=" * 60)

    # 1. Conexión DuckDB
    conn = None
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 100 * 1024:
        print(f"[1/4] Conectando a DuckDB local: {DB_FILE}...")
        try:
            conn = duckdb.connect(DB_FILE)
        except Exception as e:
            print(f"  Error DuckDB local: {e}")

    if conn is None:
        print("[1/4] Conectando a fuente remota...")
        try:
            conn = duckdb.connect()
            conn.execute("INSTALL httpfs;")
            conn.execute("LOAD httpfs;")
            conn.execute(
                f"ATTACH '{REMOTE_GDRIVE_URL}' AS remote_db (TYPE DUCKDB, READ_ONLY);"
            )
            conn.execute("USE remote_db;")
            print("  Conexión remota exitosa!")
        except Exception as e:
            print(f"  No se pudo conectar: {e}")
            print(f"  Coloca '{DB_FILE}' localmente y reintenta.")
            sys.exit(1)

    # 2. Consulta SQL con filtro tech + repairs
    print("\n[2/4] Extrayendo establecimientos tech de DuckDB...")
    cnaes_str = ",".join(map(str, ALL_CNAES))
    muns_str = ",".join(f"'{m}'" for m in TARGET_MUNICIPIOS)

    query = f"""
    SELECT
        e.cnpj_basico,
        e.cnpj_ordem,
        e.cnpj_dv,
        e.nome_fantasia,
        CAST(e.codigo_cnae_fiscal_principal AS VARCHAR) as cnae_fiscal,
        e.logradouro,
        e.numero,
        e.bairro,
        e.cep,
        e.telefone_1,
        e.ddd_1,
        emp.codigo_porte_empresa as porte_empresa,
        upper(trim(m.descricao)) as municipio_raw,
        e.codigo_cnae_fiscal_principal as cnae_int,
        e.identificador_matriz_filial,
        e.situacao_cadastral,
        e.correio_eletronico
    FROM estabelecimentos e
    JOIN municipios m ON e.codigo_municipio = m.codigo
    LEFT JOIN empresas emp ON e.cnpj_basico = emp.cnpj_basico
    WHERE e.uf = 'PR'
      AND e.codigo_situacao_cadastral = 2
      AND upper(trim(m.descricao)) IN ({muns_str})
      AND e.codigo_cnae_fiscal_principal IN ({cnaes_str})
    """

    try:
        rows = conn.execute(query).fetchall()
        print(f"  Registros extraídos: {len(rows)}")
    except Exception as e:
        print(f"  Error en consulta: {e}")
        conn.close()
        sys.exit(1)
    conn.close()

    if not rows:
        print("  Sin registros para procesar. Saliendo.")
        return

    # 3. Clasificar
    print("\n[3/4] Clasificando y preparando inserción...")
    type_counts = {"tech": 0, "repairs": 0}
    mun_counts = {}

    pg_rows: List[tuple] = []

    for row in rows:
        (
            cnpj_basico,
            cnpj_ordem,
            cnpj_dv,
            nome_fantasia,
            cnae_fiscal,
            logradouro,
            numero,
            bairro,
            cep,
            telefone_1,
            ddd_1,
            porte_empresa,
            municipio_raw,
            cnae_int,
            matriz_filial,
            situacao_cadastral,
            email,
        ) = row

        if cnae_int in TECH_CNAE_CODES:
            btype = "tech"
        else:
            btype = "repairs"

        type_counts[btype] += 1

        mun_normalized = normalize_municipio(municipio_raw)
        if mun_normalized:
            municipio = MUN_NAME_MAP.get(mun_normalized, mun_normalized.title())
        else:
            municipio = "Unknown"
        mun_counts[municipio] = mun_counts.get(municipio, 0) + 1

        cnpj_basico_s = str(cnpj_basico).strip().zfill(8) if cnpj_basico else "00000000"
        cnpj_ordem_s = str(cnpj_ordem).strip().zfill(4) if cnpj_ordem else "0000"
        cnpj_dv_s = str(cnpj_dv).strip().zfill(2) if cnpj_dv else "00"
        cnpj_completo = f"{cnpj_basico_s}{cnpj_ordem_s}{cnpj_dv_s}"

        pg_rows.append(
            (
                cnpj_basico_s,
                cnpj_ordem_s,
                cnpj_dv_s,
                cnpj_completo,
                safe_int(matriz_filial),
                nome_fantasia or None,
                safe_int(situacao_cadastral),
                None,
                None,
                None,
                None,
                safe_int(cnae_int),
                None,
                None,
                None,
                (logradouro or "").strip(),
                (numero or "").strip(),
                None,
                (bairro or "").strip(),
                str(cep).strip() if cep else None,
                "PR",
                None,
                municipio,
                ddd_1.strip() if ddd_1 else None,
                str(telefone_1).strip() if telefone_1 else None,
                None,
                None,
                None,
                None,
                email.strip() if email else None,
                None,
                None,
                None,
                None,
                None,
                btype,
            )
        )

    # 4. Insertar en PostgreSQL
    print(
        f"\n[4/4] Insertando {len(pg_rows)} registros en estabelecimentos (Railway)..."
    )
    pg_conn = get_db_connection()
    try:
        ensure_table_schema(pg_conn)
        cursor = pg_conn.cursor()

        insert_sql = """
            INSERT INTO estabelecimentos (
                cnpj_basico, cnpj_ordem, cnpj_dv, cnpj_completo,
                identificador_matriz_filial, nome_fantasia,
                situacao_cadastral, data_situacao_cadastral,
                motivo_situacao_cadastral, nome_cidade_exterior, codigo_pais,
                cnae_fiscal, cnae_fiscal_descricao,
                descricao_tipo_logradouro, logradouro,
                numero, complemento, bairro, cep,
                uf, codigo_municipio, municipio,
                ddd_1, telefone_1,
                ddd_2, telefone_2, ddd_fax, fax, correio_eletronico,
                situacao_especial, data_situacao_especial,
                latitude, longitude, geocoded, business_type
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (cnpj_completo) DO UPDATE SET
                nome_fantasia = EXCLUDED.nome_fantasia,
                cnae_fiscal = EXCLUDED.cnae_fiscal,
                logradouro = EXCLUDED.logradouro,
                numero = EXCLUDED.numero,
                bairro = EXCLUDED.bairro,
                municipio = EXCLUDED.municipio,
                business_type = EXCLUDED.business_type,
                situacao_cadastral = EXCLUDED.situacao_cadastral
        """

        psycopg2.extras.execute_batch(cursor, insert_sql, pg_rows, page_size=500)
        pg_conn.commit()
        cursor.close()
        print(
            f"  [OK] {len(pg_rows)} registros insertados/actualizados en estabelecimentos."
        )
    except Exception as e:
        pg_conn.rollback()
        print(f"  [ERROR] Falló inserción en PostgreSQL: {e}")
        sys.exit(1)
    finally:
        pg_conn.close()

    # Resumen
    print("\n" + "=" * 60)
    print("  MÉTRICAS DE VERIFICACIÓN")
    print("=" * 60)
    print(f"  Total tech registros:  {len(rows)}")
    print("  Desglose:")
    for k, v in type_counts.items():
        print(f"    - {k:8s}: {v}")
    print("  Por municipio:")
    for k, v in sorted(mun_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {k:20s}: {v}")
    print("=" * 60)
    print("  Pipeline completado. Ejecuta ahora enriquecer_lojas.py")
    print("  para geocodificar direcciones via Nominatim.")
    print("=" * 60)


if __name__ == "__main__":
    main()
