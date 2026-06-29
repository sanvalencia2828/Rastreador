#!/usr/bin/env python3
"""
cnpj_etl_polars.py
==================
Pipeline ETL alternativo: CSV crudo da Receita Federal → PostgreSQL (estabelecimentos).
Filtra estrictamente por CNAEs del sector tecnológico (Tech + Repairs)
en la región metropolitana de Londrina.

Usa Polars para procesamiento eficiente en memoria.
Encoding: CSV en Latin-1 → normalizado a UTF-8 para PostgreSQL.
"""

import polars as pl
import psycopg2
import psycopg2.extras
import json
import os
from typing import Optional


# ==============================================================================
# ENV LOADER
# ==============================================================================
def load_env_file(dotenv_path: str = ".env") -> None:
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            print(f"Loaded env from {dotenv_path}")
        except Exception as e:
            print(f"Warning: {dotenv_path}: {e}")


load_env_file()


# BR-369 corridor cities IBGE codes (Londrina → Jandaia do Sul) + Ibiporã
REGIONAL_IBGE_CODES = [
    4113700,  # Londrina
    4103701,  # Cambé
    4109807,  # Ibiporã
    4122404,  # Rolândia
    4101507,  # Arapongas
    4101408,  # Apucarana
    4103800,  # Cambira
    4112108,  # Jandaia do Sul
]

# CNAE codes for Tech + Repairs ONLY
TECH_CNAE_CODES = [
    "6201501",  # Desenvolvimento de programas de computador sob encomenda
    "6202300",  # Desenvolvimento e licenciamento de programas de computador customizáveis
    "6209100",  # Suporte técnico, manutenção e outros serviços em tecnologia da informação
]

REPAIRS_CNAE_CODES = [
    "9511800",  # Reparação e manutenção de computadores e de equipamentos periféricos
    "9512600",  # Reparação e manutenção de equipamentos de comunicação
]

VALID_CNAE_CODES = TECH_CNAE_CODES + REPAIRS_CNAE_CODES


def normalize_municipio(val: str) -> str:
    """Normaliza nombres de municipio con posible corrupción Latin-1/UTF-8."""
    if not val:
        return val
    try:
        val.encode("utf-8").decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        fixed = val.encode("latin-1").decode("utf-8")
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
        return val


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


def load_and_filter_tech_data(file_path: str) -> pl.DataFrame:
    """Carga CSV Latin-1 y filtra solo tech/repairs en RML."""
    print(f"Cargando {file_path} con Polars...")

    estabelecimento_columns = [
        "cnpj_basico",
        "cnpj_ordem",
        "cnpj_dv",
        "identificador_matriz_filial",
        "nome_fantasia",
        "situacao_cadastral",
        "data_situacao_cadastral",
        "motivo_situacao_cadastral",
        "nome_cidade_exterior",
        "pais",
        "data_inicio_atividade",
        "cnae_fiscal_principal",
        "cnae_fiscal_secundaria",
        "tipo_logradouro",
        "logradouro",
        "numero",
        "complemento",
        "bairro",
        "cep",
        "uf",
        "codigo_municipio",
        "municipio",
        "ddd_1",
        "telefone_1",
        "ddd_2",
        "telefone_2",
        "ddd_fax",
        "fax",
        "correio_eletronico",
        "situacao_especial",
        "data_situacao_especial",
        "porte_empresa",
    ]

    df = pl.read_csv(
        file_path,
        separator=";",
        encoding="latin1",
        has_header=False,
        new_columns=estabelecimento_columns,
        infer_schema_length=10000,
    )
    print(f"  Filas cargadas: {len(df)}")

    # Normalizar municipio (Latin-1 → UTF-8)
    df = df.with_columns(
        pl.col("municipio")
        .map_elements(
            lambda x: normalize_municipio(x) if x else x,
            return_dtype=pl.Utf8,
        )
        .alias("municipio")
    )

    # Filtrar
    filtered = df.with_columns(
        pl.col("cnae_fiscal_principal")
        .cast(pl.Utf8, strict=False)
        .str.replace_all(r"[-/\s\.]", ""),
        pl.col("codigo_municipio").cast(pl.Int64, strict=False),
        pl.col("situacao_cadastral").cast(pl.Int64, strict=False),
    ).filter(
        (pl.col("codigo_municipio").is_in(REGIONAL_IBGE_CODES))
        & (pl.col("situacao_cadastral") == 2)
        & (pl.col("cnae_fiscal_principal").is_in(VALID_CNAE_CODES))
    )

    print(f"  Filas tras filtro: {len(filtered)}")

    if len(filtered) == 0:
        return filtered

    # Clasificar business_type
    filtered = filtered.with_columns(
        [
            pl.when(pl.col("cnae_fiscal_principal").is_in(TECH_CNAE_CODES))
            .then(pl.lit("tech"))
            .otherwise(pl.lit("repairs"))
            .alias("business_type"),
        ]
    )

    # Construir cnpj_completo
    filtered = filtered.with_columns(
        [
            (
                pl.col("cnpj_basico").cast(pl.Utf8).str.zfill(8)
                + pl.col("cnpj_ordem").cast(pl.Utf8).str.zfill(4)
                + pl.col("cnpj_dv").cast(pl.Utf8).str.zfill(2)
            ).alias("cnpj_completo"),
        ]
    )

    return filtered


def export_to_postgresql(df: pl.DataFrame, conn: psycopg2.extensions.connection) -> int:
    """Inserta/actualiza registros en estabelecimentos."""
    ensure_table_schema(conn)
    cursor = conn.cursor()

    rows = df.select(
        [
            "cnpj_basico",
            "cnpj_ordem",
            "cnpj_dv",
            "cnpj_completo",
            "identificador_matriz_filial",
            "nome_fantasia",
            "situacao_cadastral",
            "cnae_fiscal_principal",
            "logradouro",
            "numero",
            "bairro",
            "cep",
            "uf",
            "codigo_municipio",
            "municipio",
            "ddd_1",
            "telefone_1",
            "correio_eletronico",
            "business_type",
        ]
    ).to_dicts()

    insert_sql = """
        INSERT INTO estabelecimentos (
            cnpj_basico, cnpj_ordem, cnpj_dv, cnpj_completo,
            identificador_matriz_filial, nome_fantasia,
            situacao_cadastral, cnae_fiscal,
            logradouro, numero, bairro, cep,
            uf, codigo_municipio, municipio,
            ddd_1, telefone_1, correio_eletronico,
            business_type, geocoded
        ) VALUES (
            %(cnpj_basico)s, %(cnpj_ordem)s, %(cnpj_dv)s, %(cnpj_completo)s,
            %(identificador_matriz_filial)s, %(nome_fantasia)s,
            %(situacao_cadastral)s, %(cnae_fiscal_principal)s,
            %(logradouro)s, %(numero)s, %(bairro)s, %(cep)s,
            %(uf)s, %(codigo_municipio)s, %(municipio)s,
            %(ddd_1)s, %(telefone_1)s, %(correio_eletronico)s,
            %(business_type)s, FALSE
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

    psycopg2.extras.execute_batch(cursor, insert_sql, rows, page_size=500)
    conn.commit()
    cursor.close()
    return len(rows)


def export_to_json(df: pl.DataFrame, output_file: str) -> None:
    """Exporta a JSON como respaldo."""
    data_dicts = df.to_dicts()
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data_dicts, f, indent=2, ensure_ascii=False)
    print(f"  Backup JSON: {output_file}")


def main(input_file: Optional[str] = None):
    if input_file is None:
        input_file = "Estabelecimentos0.csv"
        if not os.path.exists(input_file) and os.path.exists(
            "sample_estabelecimentos.csv"
        ):
            input_file = "sample_estabelecimentos.csv"

    if not os.path.exists(input_file):
        print(f"Archivo {input_file} no encontrado.")
        print("Descarga los CSVs desde http://receita.economia.gov.br/...")
        return

    print("=" * 60)
    print("  ETL Polars: CSV → PostgreSQL (estabelecimentos)")
    print("  Filtro: Tech + Repairs | RML")
    print("=" * 60)

    # Cargar y filtrar
    df = load_and_filter_tech_data(input_file)
    if len(df) == 0:
        print("Sin datos tech para exportar.")
        return

    # Backup JSON
    output_json = "londrina_tech_businesses.json"
    export_to_json(df, output_json)

    # PostgreSQL
    try:
        conn = get_db_connection()
        count = export_to_postgresql(df, conn)
        print(f"  [OK] {count} registros insertados/actualizados en estabelecimentos.")
        conn.close()
    except Exception as e:
        print(f"  [ERROR] PostgreSQL: {e}")
        return

    print("ETL Polars completado. Ejecuta enriquecer_lojas.py para geocodificar.")


if __name__ == "__main__":
    main()
