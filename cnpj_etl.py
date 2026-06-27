#!/usr/bin/env python3
"""
ETL Script for Brazilian CNPJ Data Processing

This script processes CNPJ (Cadastro Nacional da Pessoa Jurídica) data from the
Brazilian Federal Revenue Service, filtering for businesses in Londrina/PR and
its nearby municipalities that are active and operate in retail or gastronomy sectors.

Author: Claude Code (Data Engineering Assistant)
Date: 2026-05-23
"""

import pandas as pd
from sqlalchemy import create_engine
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
    "4711301",
    "4711302",
    "4712100",
    "4713000",
    "4721101",
    "4721102",
    "4721103",
    "4722901",
    "4722902",
    "4723700",
    "4724500",
    "4729601",
    "4729602",
    "4729603",
    "4729699",
    "4731800",
    "4732600",
    "4741500",
    "4742300",
    "4743100",
    "4744001",
    "4744002",
    "4744003",
    "4751201",
    "4751202",
    "4752100",
    "4753900",
    "4754701",
    "4754702",
    "4755501",
    "4755502",
    "4756300",
    "4757100",
    "4759801",
    "4759899",
    "4761001",
    "4761002",
    "4761003",
    "4762800",
    "4763601",
    "4763602",
    "4763603",
    "4763604",
    "4763605",
    "4771701",
    "4771702",
    "4771703",
    "4771704",
    "4771705",
    "4771706",
    "4771799",
    "4772500",
    "4773300",
    "4774100",
    "4781400",
    "4782201",
    "4782202",
    "4783101",
    "4783102",
    "4784900",
    "4785701",
    "4785702",
    "4785799",
    "4789001",
    "4789002",
    "4789099",
]

GASTRONOMY_CNAE_CODES = [
    # Restaurants and similar establishments
    "5611201",
    "5611202",
    "5611203",
    "5611204",
    "5611205",
    "5612100",
    "5613900",
    "5620101",
    "5620102",
    "5620103",
    "5620104",
]

TECH_CNAE_CODES = [
    # IT Services and Information Services
    "6201501",
    "6202300",
    "6203100",
    "6204000",
    "6209100",
    "6311900",
    "6319400",
    # Retail of tech (computers, phones, electronics)
    "4751201",
    "4751202",
    "4752100",
    "4753900",
    # Wholesale of tech
    "4651400",
    "4652200",
    "4652201",
    "4652202",
    # Telecom
    "6110801",
    "6110802",
    "6110803",
    "6120501",
    "6120502",
    "6130200",
    "6190601",
    "6190602",
    "6190699",
    # Repair of IT
    "9511800",
    "9512600",
    # Tech training
    "8599603",
]

REPAIRS_CNAE_CODES = [
    # Technical Assistance & Repairs (computers, cellphones, electronics, appliances)
    "9511800",
    "9512600",
    "9521500",
    "9529104",
    "9529199",
]

# Combine all valid CNAE codes
VALID_CNAE_CODES = (
    RETAIL_CNAE_CODES + GASTRONOMY_CNAE_CODES + TECH_CNAE_CODES + REPAIRS_CNAE_CODES
)


def load_cnpj_data(file_path: str, chunk_size: int = 10000) -> pd.DataFrame:
    """
    Load CNPJ data from CSV file in chunks and apply filters

    Args:
        file_path: Path to the CNPJ CSV file
        chunk_size: Number of rows to process at a time

    Returns:
        Filtered DataFrame with Londrina businesses
    """
    print(f"Loading CNPJ data from {file_path}")

    # Define column names based on CNPJ public data structure
    # This assumes the basic enterprises file structure
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

    filtered_chunks = []
    total_processed = 0

    try:
        # Process file in chunks
        for chunk in pd.read_csv(
            file_path,
            encoding="latin1",
            sep=";",  # CNPJ data typically uses semicolon separator
            chunksize=chunk_size,
            names=estabelecimento_columns,
            dtype=str,  # Read all as strings to avoid parsing issues
            header=None,  # No header in CNPJ files
        ):
            total_processed += len(chunk)
            if total_processed % 100000 == 0:
                print(f"Processed {total_processed} rows...")

            # Apply filters
            filtered_chunk = filter_cnpj_data(chunk)
            if not filtered_chunk.empty:
                filtered_chunks.append(filtered_chunk)

    except Exception as e:
        print(f"Error loading data: {e}")
        return pd.DataFrame()

    if not filtered_chunks:
        print("No data matched the filters.")
        return pd.DataFrame()

    # Concatenate all filtered chunks
    result_df = pd.concat(filtered_chunks, ignore_index=True)
    print(f"Final dataset contains {len(result_df)} records.")
    return result_df


def filter_cnpj_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply business filters to CNPJ data

    Args:
        df: DataFrame with CNPJ data

    Returns:
        Filtered DataFrame
    """
    # Convert relevant columns to appropriate types
    df["codigo_municipio"] = pd.to_numeric(df["codigo_municipio"], errors="coerce")
    df["situacao_cadastral"] = pd.to_numeric(df["situacao_cadastral"], errors="coerce")

    # Filter 1: Regional cities (Londrina + nearby)
    regional_filter = df["codigo_municipio"].isin(REGIONAL_IBGE_CODES)

    # Filter 2: Active businesses (situation code 2 = active)
    active_filter = df["situacao_cadastral"] == 2

    # Filter 3: Retail or gastronomy activities
    cnae_filter = df["cnae_fiscal_principal"].isin(VALID_CNAE_CODES)

    # Apply all filters
    filtered_df = df[regional_filter & active_filter & cnae_filter].copy()

    # Clean up the data
    if not filtered_df.empty:
        # Remove unnecessary columns to reduce size
        columns_to_keep = [
            "cnpj_basico",
            "cnpj_ordem",
            "cnpj_dv",
            "nome_fantasia",
            "cnae_fiscal_principal",
            "logradouro",
            "numero",
            "bairro",
            "cep",
            "telefone_1",
            "porte_empresa",
            "municipio",
        ]

        # Only keep columns that exist in the dataframe
        existing_columns = [
            col for col in columns_to_keep if col in filtered_df.columns
        ]
        filtered_df = filtered_df[existing_columns]

        # Add classification column
        filtered_df["business_type"] = filtered_df["cnae_fiscal_principal"].apply(
            lambda x: (
                "tech"
                if x in TECH_CNAE_CODES
                else (
                    "repairs"
                    if x in REPAIRS_CNAE_CODES
                    else ("retail" if x in RETAIL_CNAE_CODES else "gastronomy")
                )
            )
        )

    return filtered_df


def export_to_json(df: pd.DataFrame, output_file: str) -> None:
    """
    Export DataFrame to JSON file

    Args:
        df: DataFrame to export
        output_file: Path to output JSON file
    """
    try:
        # Convert DataFrame to JSON
        df.to_json(output_file, orient="records", indent=2, force_ascii=False)
        print(f"Data exported to {output_file}")
    except Exception as e:
        print(f"Error exporting to JSON: {e}")


def export_to_postgresql(
    df: pd.DataFrame, connection_string: str, table_name: str
) -> None:
    """
    Export DataFrame to PostgreSQL database

    Args:
        df: DataFrame to export
        connection_string: PostgreSQL connection string
        table_name: Name of the table to create/insert into
    """
    try:
        # Create database engine
        engine = create_engine(connection_string)

        # Export DataFrame to PostgreSQL
        df.to_sql(table_name, engine, if_exists="replace", index=False)
        print(f"Data exported to PostgreSQL table '{table_name}'")
    except Exception as e:
        print(f"Error exporting to PostgreSQL: {e}")


def main():
    """
    Main function to run the ETL process
    """
    # Example usage - modify these paths according to your setup
    input_file = "sample_estabelecimentos.csv"  # Using our sample data
    output_json = "londrina_businesses.json"

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found.")
        print(
            "Please download CNPJ data from http://receita.economia.gov.br/orientacao/tributaria/cadastros/cadastro-nacional-de-pessoas-juridicas-cnpj/DadosPublicosCNPJ"
        )
        print("Or run generate_sample_data.py to create sample data.")
        return

    # Process the data
    print("Starting CNPJ ETL process...")
    filtered_data = load_cnpj_data(input_file)

    if filtered_data.empty:
        print("No data to export.")
        return

    # Option 1: Export to JSON
    export_to_json(filtered_data, output_json)

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
            postgres_connection = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )
        else:
            db_host = None

    if postgres_connection:
        print(
            f"Database connection credentials found. Exporting to PostgreSQL at {db_host or 'configured connection string'}..."
        )
        export_to_postgresql(filtered_data, postgres_connection, "londrina_businesses")
    else:
        print("Database connection variables not set. Skipping PostgreSQL export.")

    print("ETL process completed successfully!")


if __name__ == "__main__":
    main()
