"""Global SQLAlchemy engine."""

import os

from sqlalchemy import create_engine

from app.core import config  # noqa: F401  (loads .env before env reads below)


# ------------------------------------------------------------------------------
# DB SETUP & GLOBAL ENGINE
# ------------------------------------------------------------------------------
def normalize_db_url(url):
    """SQLAlchemy 2 rejects the legacy postgres:// scheme that some hosts still hand out."""
    if url and url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


conn_str = normalize_db_url(os.environ.get("DATABASE_URL"))
if not conn_str:
    db_user = os.environ.get("DB_USER")
    db_password = os.environ.get("DB_PASSWORD")
    db_host = os.environ.get("DB_HOST", "db")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "londrina_comercio")
    if all([db_user, db_password, db_host, db_name]):
        conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# hide_parameters: driver errors must not echo bound values (customer names, addresses)
db_engine = create_engine(conn_str, hide_parameters=True) if conn_str else None
