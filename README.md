# CNPJ ETL Processor

This project provides an ETL (Extract, Transform, Load) script for processing Brazilian CNPJ (Cadastro Nacional da Pessoa Jurídica) data from the Federal Revenue Service, filtering for businesses in Londrina/PR that are active and operate in retail or gastronomy sectors.

## Features

- Loads large CNPJ CSV files in chunks to manage memory efficiently
- Filters data for:
  - Businesses located in Londrina/PR (IBGE code: 4113700)
  - Active businesses only (situacao_cadastral = 2)
  - Retail and gastronomy activities based on CNAE codes
- Exports results to JSON or PostgreSQL database
- Two implementations: one using Pandas and another using Polars (more memory efficient)

## Requirements

- Python 3.7+
- pandas
- polars (optional but recommended for better performance)
- sqlalchemy
- psycopg2-binary (for PostgreSQL connectivity)

## Installation

1. Install the required packages:
```bash
pip install -r requirements.txt
```

Or use our installation script:
```bash
python install_deps.py
```

## Data Source

Download the CNPJ data from the official source:
http://receita.economia.gov.br/orientacao/tributaria/cadastros/cadastro-nacional-de-pessoas-juridicas-cnpj/DadosPublicosCNPJ

The data is organized in several files:
- Empresas: Basic company information
- Estabelecimentos: Business establishment information (addresses, activities)
- Socios: Partner/shareholder information

For this script, we primarily use the "Estabelecimentos" files which contain the location and activity information.

## Usage

We provide two implementations:

1. **Pandas version** (`cnpj_etl.py`): Traditional approach using pandas
2. **Polars version** (`cnpj_etl_polars.py`): More memory-efficient approach using polars

To run either version:
```bash
python cnpj_etl.py
# or
python cnpj_etl_polars.py
```

## Configuration

1. Download and extract the CNPJ data files
2. Modify the `input_file` variable in the script to point to your data file
3. (Optional) Adjust filtering criteria in the constants section

## Output Options

The script supports two output formats:

1. **JSON**: Exports to a JSON file with all filtered records
2. **PostgreSQL**: Inserts data into a PostgreSQL database table

To use PostgreSQL export, uncomment the relevant lines in the main() function and configure your connection string.

## Customization

You can modify the filtering criteria by adjusting:
- `LONDRINA_IBGE_CODE`: Change to filter for a different municipality
- `RETAIL_CNAE_CODES` and `GASTRONOMY_CNAE_CODES`: Add/remove CNAE codes for different business categories
- Chunk size in `load_cnpj_data()` function for memory/performance tuning

## CNAE Codes Reference

The script includes CNAE codes for:
- Retail trade (sections 47xxxxx)
- Food and beverage services (section 56xxxxx)

You can extend this list based on your specific requirements.

## Performance Comparison

- **Pandas version**: More familiar to most data scientists, good for medium datasets
- **Polars version**: Better memory efficiency and performance for large datasets

For processing the full CNPJ dataset (which can be tens of GB), the Polars version is recommended.

## License

This project is provided for educational and research purposes. Please ensure compliance with the terms of use of the CNPJ public data.