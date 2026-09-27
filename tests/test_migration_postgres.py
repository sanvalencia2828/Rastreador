"""Applies 021 twice against TEST_DATABASE_URL. Skipped locally when unset."""

import os

import pytest

pytest.importorskip("psycopg2")
sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text

from app.migrate import apply_sql

SQL = open("migrations/021_planner_routes.sql", encoding="utf-8").read()


@pytest.fixture()
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS route_stops CASCADE")
        conn.exec_driver_sql("DROP TABLE IF EXISTS routes CASCADE")
        conn.exec_driver_sql("DROP TABLE IF EXISTS cities CASCADE")
        conn.exec_driver_sql("DROP TABLE IF EXISTS schema_migrations CASCADE")
    yield eng
    eng.dispose()


def test_migration_021_is_idempotent_and_rejects_planned(engine):
    apply_sql(engine, SQL)
    apply_sql(engine, SQL)
    with engine.begin() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                     WHERE table_name = 'route_stops'
                    """
                )
            )
        }
        assert {"seq", "visit_date", "tarjeta_status", "maps_url", "lng"} <= columns
        city_id = conn.execute(text("SELECT id FROM cities WHERE name = 'Londrina'")).scalar()
        assert city_id
        route_id = conn.execute(
            text(
                """
                INSERT INTO routes (city_id, name, status, "date")
                VALUES (:city_id, 'hoy', 'draft', DATE '2026-09-26')
                RETURNING id
                """
            ),
            {"city_id": city_id},
        ).scalar()
        conn.execute(
            text(
                """
                INSERT INTO route_stops (route_id, stop_order, address, lat, lon)
                VALUES (:route_id, 1, 'Rua X', -23.3, -51.1)
                """
            ),
            {"route_id": route_id},
        )
        row = conn.execute(
            text("SELECT seq, visit_date, tarjeta_status, lng FROM route_stops WHERE route_id = :id"),
            {"id": route_id},
        ).one()
        assert row.seq == 1
        assert row.visit_date is not None
        assert row.tarjeta_status == "TT"
        assert float(row.lng) == pytest.approx(-51.1)
        with pytest.raises(Exception):
            conn.execute(
                text(
                    """
                    INSERT INTO routes (name, status, "date")
                    VALUES ('legacy', 'planned', CURRENT_DATE)
                    """
                )
            )
