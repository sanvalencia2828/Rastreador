"""street_coverage: sin LONDRINA fijo, Maringá por código 7691 y cobertura POR USUARIO (esquema, migración, trigger real)."""

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.security import create_jwt_token
from app.main import app
from app.routes import visits as visits_routes

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "007_street_coverage_per_user.sql"
FILES = [ROOT / "street_tracking_schema.sql", ROOT / "docker-entrypoint-initdb.d" / "street_tracking_schema.sql", MIGRATION]
FUNCTION = re.compile(r"CREATE OR REPLACE FUNCTION update_street_coverage\(\).*?\$\$ language 'plpgsql';\n", re.S)
UA, UB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _sql(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _function(path):
    return FUNCTION.search(_sql(path)).group(0)


def test_function_is_identical_in_schema_copies_and_migration():
    bodies = [_function(p) for p in FILES]
    assert bodies[0] == bodies[1] == bodies[2]


def test_function_has_no_fixed_city_and_every_visit_aggregate_is_per_user():
    body = _function(MIGRATION)
    assert "LONDRINA" not in body.upper()
    assert body.count("AND v.user_id = NEW.user_id") == 3
    assert "ON CONFLICT (user_id, logradouro, municipio)" in body


PG = os.environ.get("TEST_PG_URL")


@pytest.fixture
def pg(monkeypatch):
    if not PG:
        pytest.skip("TEST_PG_URL no definido")
    url = make_url(PG)
    if not (url.database or "").startswith("test") or url.host not in (None, "localhost", "127.0.0.1"):
        pytest.exit("TEST_PG_URL debe ser local y apuntar a una base cuyo nombre empiece por 'test'", returncode=2)
    engine = create_engine(PG)
    try:
        with engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    except Exception:
        engine.dispose()
        pytest.skip("la base de pruebas no tiene PostGIS")
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS visits, street_coverage, estabelecimentos CASCADE"))
        c.execute(text("""CREATE TABLE estabelecimentos (cnpj_completo TEXT, codigo_municipio INTEGER,
            municipio TEXT, bairro TEXT, logradouro TEXT)"""))
        c.execute(text("""CREATE TABLE visits (id SERIAL PRIMARY KEY, user_id UUID, route_id UUID, cnpj TEXT,
            lat NUMERIC(10,7), lon NUMERIC(10,7), logradouro TEXT NOT NULL, bairro TEXT, notes TEXT,
            source TEXT, visited_at TIMESTAMPTZ DEFAULT NOW())"""))
        # the OLD shape (global, UNIQUE(logradouro, municipio)) with a legacy row, then the real migration on top
        c.execute(text("""CREATE TABLE street_coverage (id SERIAL PRIMARY KEY, logradouro TEXT NOT NULL, bairro TEXT,
            municipio TEXT NOT NULL, state VARCHAR(2) NOT NULL DEFAULT 'PR', last_visited TIMESTAMPTZ,
            visit_count INTEGER DEFAULT 0, total_businesses INTEGER DEFAULT 0, covered_businesses INTEGER DEFAULT 0,
            geom GEOMETRY(Point, 4326), updated_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE (logradouro, municipio))"""))
        c.execute(text("INSERT INTO street_coverage (logradouro, municipio, visit_count) VALUES ('RUA ANTIGUA', 'LONDRINA', 9)"))
        c.execute(text(_sql(MIGRATION)))
        c.execute(text("""CREATE TRIGGER trigger_update_street_coverage AFTER INSERT ON visits
            FOR EACH ROW EXECUTE FUNCTION update_street_coverage()"""))
        c.execute(text("""INSERT INTO estabelecimentos VALUES
            ('M1', 7691, '44', 'ZONA 7', 'RUA X'), ('M2', 7691, NULL, 'ZONA 7', 'RUA X'),
            ('L1', 7667, 'LONDRINA', 'CENTRO', 'RUA X')"""))
    monkeypatch.setattr(visits_routes, "db_engine", engine)
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS visits, street_coverage, estabelecimentos CASCADE"))
    engine.dispose()


def _visit(engine, cnpj, street="RUA X", user=UA):
    with engine.begin() as c:
        c.execute(text("INSERT INTO visits (user_id, cnpj, lat, lon, logradouro) VALUES "
                       "(:u, :c, -23.4, -51.9, :s)"), {"u": user, "c": cnpj, "s": street})


def _coverage(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT municipio, total_businesses, covered_businesses FROM street_coverage "
                              "WHERE user_id IS NOT NULL ORDER BY municipio")).fetchall()


def test_maringa_cnpj_creates_MARINGA_row_counted_by_code(pg):
    _visit(pg, "M1")
    # municipio holds a DDD ('44') in the Maringa rows: the code 7691 decides, and both M1 and M2 count
    assert _coverage(pg) == [("MARINGA", 2, 1)]


def test_other_city_keeps_estabelecimentos_municipio(pg):
    _visit(pg, "L1")
    assert _coverage(pg) == [("LONDRINA", 1, 1)]


@pytest.mark.parametrize("cnpj", [None, "DESCONOCIDO"])
def test_unresolvable_municipality_creates_no_row_and_not_londrina(pg, cnpj):
    _visit(pg, cnpj)
    assert _coverage(pg) == []
    with pg.connect() as c:
        assert c.execute(text("SELECT count(*) FROM visits")).scalar() == 1  # the visit itself is kept


def test_same_street_name_in_two_cities_keeps_separate_counters(pg):
    _visit(pg, "M1")
    _visit(pg, "L1")
    with pg.connect() as c:
        rows = c.execute(text("SELECT municipio, total_businesses, covered_businesses, visit_count "
                              "FROM street_coverage WHERE user_id IS NOT NULL ORDER BY municipio")).fetchall()
    assert rows == [("LONDRINA", 1, 1, 1), ("MARINGA", 2, 1, 1)]


def test_two_users_get_separate_rows_and_counters(pg):
    _visit(pg, "M1", user=UA)
    _visit(pg, "M1", user=UA)
    _visit(pg, "M2", user=UB)
    with pg.connect() as c:
        rows = c.execute(text("SELECT user_id::text, covered_businesses, visit_count FROM street_coverage "
                              "WHERE user_id IS NOT NULL ORDER BY user_id")).fetchall()
    assert rows == [(UA, 1, 2), (UB, 1, 1)]  # B's visit does not touch A's counters (and vice versa)


def test_endpoint_returns_only_the_callers_rows_and_not_legacy_ones(pg):
    _visit(pg, "M1", user=UA)
    _visit(pg, "M2", user=UB)
    _visit(pg, "M2", user=UB)

    def get(uid):
        token = create_jwt_token({"user_id": uid})
        return TestClient(app).get("/api/street-coverage", headers={"Authorization": f"Bearer {token}"}).json()

    mine, theirs = get(UA), get(UB)
    assert [(r["logradouro"], r["visit_count"]) for r in mine] == [("RUA X", 1)]
    assert [(r["logradouro"], r["visit_count"]) for r in theirs] == [("RUA X", 2)]
    assert "RUA ANTIGUA" not in {r["logradouro"] for r in mine + theirs}  # legacy row (user_id NULL): nobody sees it
    with pg.connect() as c:  # ...but it was not deleted
        assert c.execute(text("SELECT count(*) FROM street_coverage WHERE logradouro = 'RUA ANTIGUA'")).scalar() == 1


def test_migration_is_idempotent(pg):
    with pg.begin() as c:
        c.execute(text(_sql(MIGRATION)))  # second run must not fail or duplicate anything
    _visit(pg, "M1")
    assert _coverage(pg) == [("MARINGA", 2, 1)]
