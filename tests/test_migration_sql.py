from pathlib import Path

from app.sql_split import split_sql
from app.tarjeta import normalize_route_status

SQL = Path("migrations/021_planner_routes.sql").read_text(encoding="utf-8")


def test_migration_is_idempotent_and_has_contract():
    assert "ADD COLUMN IF NOT EXISTS" in SQL
    assert "CREATE TABLE IF NOT EXISTS" in SQL
    assert "routes_status_check" in SQL
    assert "tarjeta_status" in SQL
    assert "visit_date" in SQL
    assert "idx_routes_city_date_status" in SQL
    assert "idx_route_stops_visit_tarjeta" in SQL
    assert "UNIQUE (route_id, seq)" in SQL or "route_id, seq" in SQL
    assert "planned" in SQL and "locked" in SQL
    assert "postgresql://" not in SQL
    assert "password" not in SQL.lower()


def test_splitter_keeps_function_body_intact():
    statements = split_sql(SQL)
    functions = [item for item in statements if "CREATE OR REPLACE FUNCTION" in item]
    assert len(statements) > 10
    assert len(functions) >= 2
    assert any(";" in item and "NEW.tarjeta_status" in item for item in functions)


def test_planned_maps_to_locked():
    assert normalize_route_status("planned") == "locked"
    assert normalize_route_status("DRAFT") == "draft"
