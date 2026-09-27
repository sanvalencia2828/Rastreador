"""Apply idempotent SQL migrations. Failures are logged and do not crash the API."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.sql_split import split_sql

log = logging.getLogger("rastreador.migrate")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def redact(message: str) -> str:
    return re.sub(r"(://[^:/\s]+):([^@/\s]+)@", r"\1:***@", message)


def apply_migrations(engine) -> bool:
    if engine is None:
        log.info("DATABASE_URL is not set; skipping migrations")
        return False
    sql_path = MIGRATIONS_DIR / "021_planner_routes.sql"
    if not sql_path.is_file():
        log.error("migration file missing: %s", sql_path)
        return False
    try:
        apply_sql(engine, sql_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("migration 021 failed: %s", redact(str(exc)))
        return False
    log.info("migration 021 applied")
    return True


def apply_sql(engine, script: str) -> None:
    statements = split_sql(script)
    with engine.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)
