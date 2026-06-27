#!/usr/bin/env python3
"""
Test script to validate the CNPJ ETL environment setup
"""


def test_dependencies():
    """Test if all required dependencies are installed"""
    dependencies = {
        "pandas": 'import pandas as pd; print(f"Pandas version: {pd.__version__}")',
        "polars": 'import polars as pl; print(f"Polars version: {pl.__version__}")',
        "sqlalchemy": 'import sqlalchemy; print(f"SQLAlchemy version: {sqlalchemy.__version__}")',
        "psycopg2": 'import psycopg2; print("psycopg2 imported successfully")',
    }

    print("Testing dependencies...")

    for dep_name, import_stmt in dependencies.items():
        try:
            exec(import_stmt)
            print(f"[OK] {dep_name}")
        except ImportError as e:
            print(f"[MISSING] {dep_name}: {e}")
        except Exception as e:
            print(f"[ERROR] {dep_name}: {e}")

    print("\nDependency check completed.")


if __name__ == "__main__":
    test_dependencies()
