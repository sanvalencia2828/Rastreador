#!/usr/bin/env python3
"""
ETL Script for Brazilian CNPJ Data Processing using Polars

This script processes CNPJ (Cadastro Nacional da Pessoa Jurídica) data from the
Brazilian Federal Revenue Service, filtering for businesses in Londrina/PR
that are active and operate in retail or gastronomy sectors.

Polars version - more memory efficient for large datasets.

Author: Claude Code (Data Engineering Assistant)
Date: 2026-05-23
"""

import polars as pl
from sqlalchemy import create_engine
import json
import sys
import os

# ==============================================================================
# ENVIRONMENT VARIABLE LOADER (ZERO-DEPENDENCY)
# ==============================================================================
def load_env_file(dotenv_path: str = ".env") -> None:
    """Loads environment variables from a .env file if it exists."""
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
            print(f"Loaded environment variables from {dotenv_path}")
        except Exception as e:
            print(f"Warning: Could not read {dotenv_path}: {e}")

load_env_file()



# Regional cities IBGE codes (Londrina, Cambé, Ibiporã, Apucarana, Jandaia do Sul)
REGIONAL_IBGE_CODES = [4113700, 4103701, 4109807, 4101408, 4112108]

# CNAE codes for retail and gastronomy (simplified list)
RETAIL_CNAE_CODES = [
    # Retail trade
    '4711301', '4711302', '4712100', '4713000', '4721101', '4721102', '4721103',
    '4722901', '4722902', '4723700', '4724500', '4729601', '4729602', '4729603',
    '4729699', '4731800', '4732600', '4741500', '4742300', '4743100', '4744001',
    '4744002', '4744003', '4751201', '4751202', '4752100', '4753900', '4754701',
    '4754702', '4755501', '4755502', '4756300', '4757100', '4759801', '4759899',
    '4761001', '4761002', '4761003', '4762800', '4763601', '4763602', '4763603',
    '4763604', '4763605', '4771701', '4771702', '4771703', '4771704', '4771705',
    '4771706', '4771799', '4772500', '4773300', '4774100', '4781400', '4782201',
    '4782202', '4783101', '4783102', '4784900', '4785701', '4785702', '4785799',
    '4789001', '4789002', '4789099'
]

GASTRONOMY_CNAE_CODES = [
    # Restaurants and similar establishments
    '5611201', '5611202', '5611203', '5611204', '5611205', '5612100', '5613900',
    '5620101', '5620102', '5620103', '5620104'
]

TECH_CNAE_CODES = [
    # IT Services and Information Services
    '6201501', '6202300', '6203100', '6204000', '6209100', '6311900', '6319400'
]

# Combine all valid CNAE codes
VALID_CNAE_CODES = RETAIL_CNAE_CODES + GASTRONOMY_CNAE_CODES + TECH_CNAE_CODES


def load_cnpj_data_polars(file_path: str, chunk_size: int = 50000) -> pl.DataFrame:
    """
    Load CNPJ data from CSV file using Polars and apply filters

    Args:
        file_path: Path to the CNPJ CSV file
        chunk_size: Number of rows to process at a time

    Returns:
        Filtered DataFrame with Londrina businesses
    """
    print(f"Loading CNPJ data from {file_path} using Polars")

    # Define column names based on CNPJ public data structure
    estabelecimento_columns = [
        'cnpj_basico', 'cnpj_ordem', 'cnpj_dv', 'identificador_matriz_filial',
        'nome_fantasia', 'situacao_cadastral', 'data_situacao_cadastral',
        'motivo_situacao_cadastral', 'nome_cidade_exterior', 'pais',
        'data_inicio_atividade', 'cnae_fiscal_principal', 'cnae_fiscal_secundaria',
        'tipo_logradouro', 'logradouro', 'numero', 'complemento', 'bairro',
        'cep', 'uf', 'codigo_municipio', 'municipio', 'ddd_1', 'telefone_1',
        'ddd_2', 'telefone_2', 'ddd_fax', 'fax', 'correio_eletronico',
        'situacao_especial', 'data_situacao_especial', 'porte_empresa'
    ]

    try:
        # Load data with Polars
        # Note: Polars handles large files more efficiently than Pandas
        df = pl.read_csv(
            file_path,
            separator=';',
            encoding='latin1',
            has_header=False,  # CNPJ data doesn't have proper headers
            new_columns=estabelecimento_columns,
            infer_schema_length=10000  # Sample more rows for schema inference
        )

        print(f"Loaded {len(df)} rows from {file_path}")

        # Apply filters
        filtered_df = filter_cnpj_data_polars(df)

        return filtered_df

    except Exception as e:
        print(f"Error loading data: {e}")
        return pl.DataFrame()


def filter_cnpj_data_polars(df: pl.DataFrame) -> pl.DataFrame:
    """
    Apply business filters to CNPJ data using Polars

    Args:
        df: DataFrame with CNPJ data

    Returns:
        Filtered DataFrame
    """
    try:
        # Apply all filters in a single operation
        filtered_df = df.with_columns(
            pl.col("cnae_fiscal_principal").cast(pl.Utf8, strict=False)
        ).filter(
            (pl.col("codigo_municipio").cast(pl.Int64, strict=False).is_in(REGIONAL_IBGE_CODES)) &
            (pl.col("situacao_cadastral").cast(pl.Int64, strict=False) == 2) &
            (pl.col("cnae_fiscal_principal").is_in(VALID_CNAE_CODES))
        )

        print(f"Filtered data contains {len(filtered_df)} rows")

        # Clean up columns and add categorizations if we have matches
        if len(filtered_df) > 0:
            # Classification: tech, retail or gastronomy
            filtered_df = filtered_df.with_columns([
                pl.when(pl.col("cnae_fiscal_principal").is_in(TECH_CNAE_CODES))
                .then(pl.lit("tech"))
                .when(pl.col("cnae_fiscal_principal").is_in(RETAIL_CNAE_CODES))
                .then(pl.lit("retail"))
                .otherwise(pl.lit("gastronomy"))
                .alias("business_type")
            ])

            # Select only relevant columns (including municipio)
            columns_to_keep = [
                "cnpj_basico", "cnpj_ordem", "cnpj_dv", "nome_fantasia",
                "cnae_fiscal_principal", "logradouro", "numero", "bairro", "cep", "telefone_1",
                "business_type", "porte_empresa", "municipio"
            ]

            # Only keep columns that exist in the dataframe
            existing_columns = [col for col in columns_to_keep if col in filtered_df.columns]
            filtered_df = filtered_df.select(existing_columns)

        return filtered_df

    except Exception as e:
        print(f"Error filtering data: {e}")
        return pl.DataFrame()


def export_to_json_polars(df: pl.DataFrame, output_file: str) -> None:
    """
    Export Polars DataFrame to JSON file

    Args:
        df: DataFrame to export
        output_file: Path to output JSON file
    """
    try:
        # Convert Polars DataFrame to list of dicts and write using standard json module
        data_dicts = df.to_dicts()
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data_dicts, f, indent=2, ensure_ascii=False)
        print(f"Data exported to {output_file}")
    except Exception as e:
        print(f"Error exporting to JSON: {e}")


def export_to_postgresql_polars(df: pl.DataFrame, connection_string: str, table_name: str) -> None:
    """
    Export Polars DataFrame to PostgreSQL database

    Args:
        df: DataFrame to export
        connection_string: PostgreSQL connection string
        table_name: Name of the table to create/insert into
    """
    try:
        # Convert to Pandas for SQLAlchemy compatibility
        pandas_df = df.to_pandas()

        # Create database engine
        engine = create_engine(connection_string)

        # Export DataFrame to PostgreSQL
        pandas_df.to_sql(table_name, engine, if_exists='replace', index=False)
        print(f"Data exported to PostgreSQL table '{table_name}'")
    except Exception as e:
        print(f"Error exporting to PostgreSQL: {e}")


def main():
    """
    Main function to run the ETL process with Polars
    """
    # Example usage - modify these paths according to your setup
    input_file = "Estabelecimentos0.csv"  # Replace with actual path to your CNPJ data file
    if not os.path.exists(input_file) and os.path.exists("sample_estabelecimentos.csv"):
        input_file = "sample_estabelecimentos.csv"
    output_json = "londrina_businesses.json"

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found.")
        print("Please download CNPJ data from http://receita.economia.gov.br/orientacao/tributaria/cadastros/cadastro-nacional-de-pessoas-juridicas-cnpj/DadosPublicosCNPJ")
        return

    # Process the data
    print("Starting CNPJ ETL process with Polars...")
    filtered_data = load_cnpj_data_polars(input_file)

    if len(filtered_data) == 0:
        print("No data to export.")
        return

    # Export to JSON
    export_to_json_polars(filtered_data, output_json)

    # Option 2: Export to PostgreSQL (automatic detection via env variables)
    postgres_connection = os.environ.get("DATABASE_URL")
    db_host = "Database URL"

    if not postgres_connection:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            postgres_connection = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        else:
            db_host = None

    if postgres_connection:
        print(f"Database connection credentials found. Exporting to PostgreSQL at {db_host or 'configured connection string'}...")
        export_to_postgresql_polars(filtered_data, postgres_connection, "londrina_businesses")
    else:
        print("Database connection variables not set. Skipping PostgreSQL export.")

    print("ETL process completed successfully with Polars!")


if __name__ == "__main__":
    main()