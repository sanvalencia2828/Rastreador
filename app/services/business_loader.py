"""Business loading from PostgreSQL with JSON fallback."""

import json
import os
from typing import List, Dict, Any

from sqlalchemy import create_engine, text


# ==============================================================================
# DATABASE OR LOCAL JSON LOADER
# ==============================================================================
def load_businesses() -> List[Dict[str, Any]]:
    """
    Loads businesses from PostgreSQL database if configured,
    otherwise falls back to reading the local JSON file.

    Priority:
    1. Table `estabelecimentos` (yield actual data, with stored lat/lon if geocoded)
    2. Table `londrina_businesses` (legacy)
    3. JSON files (fallback)
    """
    conn_str = os.environ.get("DATABASE_URL")
    db_host = "Database URL"

    if not conn_str:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            conn_str = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )
        else:
            db_host = None

    if conn_str:
        # Try estabelecimentos first (the new canonical table)
        for table_name in ["estabelecimentos", "londrina_businesses"]:
            try:
                engine = create_engine(conn_str)
                with engine.connect() as conn:
                    result = conn.execute(text(f"SELECT * FROM {table_name}"))
                    businesses = [dict(row._mapping) for row in result]
                    print(
                        f"Loaded {len(businesses)} businesses from PostgreSQL table '{table_name}'."
                    )
                    if len(businesses) > 0:
                        return businesses
            except Exception as e:
                print(f"PostgreSQL table '{table_name}' failed: {e}.")

    # Fallback to local JSON file
    json_paths = ["londrina_businesses.json", "londrina_businesses_polars.json"]
    for path in json_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"Loaded {len(data)} businesses from JSON file: {path}")
                    return data
            except Exception as e:
                print(f"Failed to read JSON at {path}: {e}")

    # If no data found, return empty list
    print("WARNING: No data source found! Please run the ETL script first.")
    return []
