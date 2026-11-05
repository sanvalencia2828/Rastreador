"""El trigger de street_coverage ya no asume LONDRINA: esquema, migracion y comportamiento real."""

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / "street_tracking_schema.sql",
    ROOT / "docker-entrypoint-initdb.d" / "street_tracking_schema.sql",
    ROOT / "migrations" / "005_street_coverage_no_default_city.sql",
]
FUNCTION = re.compile(r"CREATE OR REPLACE FUNCTION update_street_coverage\(\).*?\$\$ language 'plpgsql';\n", re.S)


def _function(path):
    return FUNCTION.search(path.read_text(encoding="utf-8").replace("\r\n", "\n")).group(0)


def test_function_is_identical_in_schema_copies_and_migration():
    bodies = [_function(p) for p in FILES]
    assert bodies[0] == bodies[1] == bodies[2]


def test_function_has_no_fixed_city():
    assert "LONDRINA" not in _function(FILES[2]).upper()


PG = os.environ.get("TEST_PG_URL")


@pytest.fixture
def pg():
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
        c.execute(text("""CREATE TABLE street_coverage (id SERIAL PRIMARY KEY, logradouro TEXT NOT NULL, bairro TEXT,
            municipio TEXT NOT NULL, state VARCHAR(2) NOT NULL DEFAULT 'PR', last_visited TIMESTAMPTZ,
            visit_count INTEGER DEFAULT 0, total_businesses INTEGER DEFAULT 0, covered_businesses INTEGER DEFAULT 0,
            geom GEOMETRY(Point, 4326), updated_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE (logradouro, municipio))"""))
        c.execute(text(_function(FILES[2])))
        c.execute(text("""CREATE TRIGGER trigger_update_street_coverage AFTER INSERT ON visits
            FOR EACH ROW EXECUTE FUNCTION update_street_coverage()"""))
        c.execute(text("""INSERT INTO estabelecimentos VALUES
            ('M1', 7691, '44', 'ZONA 7', 'RUA X'), ('M2', 7691, NULL, 'ZONA 7', 'RUA X'),
            ('L1', 7667, 'LONDRINA', 'CENTRO', 'RUA X')"""))
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS visits, street_coverage, estabelecimentos CASCADE"))
    engine.dispose()


def _visit(engine, cnpj, street="RUA X"):
    with engine.begin() as c:
        c.execute(text("INSERT INTO visits (user_id, cnpj, lat, lon, logradouro) VALUES "
                       "(gen_random_uuid(), :c, -23.4, -51.9, :s)"), {"c": cnpj, "s": street})


def _coverage(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT municipio, total_businesses, covered_businesses FROM street_coverage "
                              "ORDER BY municipio")).fetchall()


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
