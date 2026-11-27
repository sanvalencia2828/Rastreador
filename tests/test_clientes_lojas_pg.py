"""Clientes propios en las vistas de lojas (cities/stats, stats/summary, businesses, near) y PATCH, en Postgres real.

Se omite sin TEST_PG_URL (ver tests/test_clientes_pg.py). Datos sintéticos; la base debe llamarse test*.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.cache import clear_response_cache
from app.core.security import create_jwt_token
from app.db.bootstrap import CLIENTES_ATRASADO_DDL, CLIENTES_DDL, CLIENTES_VISITA_DIARIA_DDL
from app.main import app
from app.routes import businesses, cities, clientes

PG = os.environ.get("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="TEST_PG_URL no definido (Postgres desechable)")

TABLES = "clientes, visits, business_status, estabelecimentos, cities, users"
SETUP = [
    "CREATE EXTENSION IF NOT EXISTS postgis",
    """CREATE TABLE users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL DEFAULT 'x')""",
    """CREATE TABLE cities (id SERIAL PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PR',
        lat NUMERIC(10,7), lon NUMERIC(10,7), UNIQUE (name, state))""",
    """CREATE TABLE estabelecimentos (id SERIAL PRIMARY KEY, cnpj_completo VARCHAR(14) UNIQUE, nome_fantasia TEXT,
        situacao_cadastral INTEGER, cnae_fiscal INTEGER, business_type TEXT, logradouro TEXT, numero TEXT, bairro TEXT,
        municipio TEXT, porte_empresa TEXT, telefone_1 TEXT, correio_eletronico TEXT,
        latitude DECIMAL(10, 8), longitude DECIMAL(11, 8), geom geography(Point, 4326),
        last_visit_date DATE, visits_count INTEGER, avg_visit_interval_days NUMERIC)""",
    "CREATE TABLE visits (id SERIAL PRIMARY KEY, cnpj VARCHAR(14))",
    "CREATE TABLE business_status (cnpj VARCHAR(14) PRIMARY KEY, status TEXT)",
    CLIENTES_DDL,
    CLIENTES_VISITA_DIARIA_DDL,
    CLIENTES_ATRASADO_DDL,
]
LAT, LON = -23.42, -51.93  # Maringá
CONTACT = {"telefone", "telefone_1", "telefono", "correio_eletronico", "email", "correo"}


@pytest.fixture
def pg(monkeypatch):
    url = make_url(PG)  # not an assert: python -O would strip it and the fixture DROPs tables
    if not (url.database or "").startswith("test") or url.host not in (None, "localhost", "127.0.0.1"):
        pytest.exit("TEST_PG_URL debe ser local y apuntar a una base cuyo nombre empiece por 'test'", returncode=2)
    engine = create_engine(PG)
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {TABLES} CASCADE"))
        for ddl in SETUP:
            c.execute(text(ddl))
        c.execute(text("INSERT INTO cities (name, lat, lon) VALUES ('Maringá', :la, :lo), ('Arapongas', -23.41, -51.42)"),
                  {"la": LAT, "lo": LON})
        c.execute(text("""INSERT INTO estabelecimentos (cnpj_completo, nome_fantasia, situacao_cadastral, municipio,
                              latitude, longitude, geom, telefone_1, correio_eletronico)
                          VALUES ('00000000000001', 'NEGOCIO_CERCA', 2, 'Maringá', :la, :lo,
                                  ST_SetSRID(ST_MakePoint(:lo, :la), 4326)::geography, 'SECRET-TEL', 'SECRET-MAIL')"""),
                  {"la": LAT, "lo": LON})
    for mod in (businesses, cities, clientes):
        monkeypatch.setattr(mod, "db_engine", engine)
    monkeypatch.setenv("APP_ENV", "production")
    clear_response_cache()
    yield engine
    engine.dispose()


def _user(engine, name):
    with engine.begin() as c:
        return str(c.execute(text("INSERT INTO users(username) VALUES (:n) RETURNING id"), {"n": name}).scalar())


def _cliente(engine, uid, nombre, municipio="Maringá", lat=None, lon=None, diario=False, atrasado=False):
    with engine.begin() as c:
        return str(c.execute(text("""INSERT INTO clientes (user_id, external_id, nombre_negocio, municipio, lat, lon,
                                         geocode_status, visita_diaria, atrasado)
                                     VALUES (:u, :n, :n, :m, :la, :lo, :s, :d, :a) RETURNING id"""),
                             {"u": uid, "n": nombre, "m": municipio, "la": lat, "lo": lon,
                              "s": "ok" if lat is not None else "pendiente", "d": diario, "a": atrasado}).scalar())


def auth(uid):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"}


@pytest.fixture
def data(pg):
    a, b = _user(pg, "a"), _user(pg, "b")
    ids = {
        "a_cerca": _cliente(pg, a, "A_CERCA", lat=LAT + 0.001, lon=LON, atrasado=True),
        "a_sin": _cliente(pg, a, "A_SIN_UBICACION", diario=True),
        "a_arap": _cliente(pg, a, "A_ARAPONGAS", municipio="Arapongas", lat=-23.41, lon=-51.42),
        "b_cerca": _cliente(pg, b, "B_CERCA", lat=LAT, lon=LON + 0.001),
    }
    return a, b, ids


client = TestClient(app)


def _names(items, key):
    return sorted(i[key] for i in items)


def test_city_stats_counts_only_the_callers_clientes(data):
    a, b, _ = data
    maringa = 1
    public = client.get(f"/api/cities/{maringa}/stats").json()
    assert (public["total_negocios"], public["total_clientes"], public["total_businesses"]) == (1, 0, 1)
    mine = client.get(f"/api/cities/{maringa}/stats", headers=auth(a))
    assert (mine.json()["total_clientes"], mine.json()["total_businesses"]) == (2, 3)
    assert "no-store" in mine.headers["cache-control"]
    assert client.get(f"/api/cities/{maringa}/stats", headers=auth(b)).json()["total_clientes"] == 1
    # un token inválido no da error ni clientes: cuenta como sin sesión
    assert client.get(f"/api/cities/{maringa}/stats", headers={"Authorization": "Bearer x"}).json()["total_clientes"] == 0


def test_stats_summary_adds_per_city_clientes_only_with_session(data):
    a, _, _ = data
    public = client.get("/api/stats/summary").json()
    assert public["clientes_propios"] == 0 and all(c["clientes"] == 0 for c in public["cities"])
    mine = client.get("/api/stats/summary", headers=auth(a)).json()
    assert mine["clientes_propios"] == 3
    assert {c["name"]: c["clientes"] for c in mine["cities"]} == {"Maringá": 2, "Arapongas": 1}
    assert mine["total_businesses"] == public["total_businesses"] == 1


def test_businesses_list_includes_own_clientes_with_origen(data):
    a, _, _ = data
    public = client.get("/api/businesses").json()
    assert [(i["name"], i["origen"]) for i in public] == [("NEGOCIO_CERCA", "negocio")]
    mine = client.get("/api/businesses", headers=auth(a)).json()
    assert _names([i for i in mine if i["origen"] == "cliente"], "name") == ["A_ARAPONGAS", "A_CERCA", "A_SIN_UBICACION"]
    assert mine[0]["name"] == "A_CERCA" and mine[0]["atrasado"] is True  # atrasados primero
    assert all(not set(i) & CONTACT for i in mine)
    city = client.get("/api/businesses?city=arapon", headers=auth(a)).json()
    assert [i["name"] for i in city] == ["A_ARAPONGAS"]
    # segunda página: sin clientes repetidos
    assert all(i["origen"] == "negocio" for i in client.get("/api/businesses?offset=1", headers=auth(a)).json())


def test_near_includes_only_own_located_clientes_in_radius(data):
    a, b, _ = data
    q = f"/api/businesses/near?lat={LAT}&lon={LON}&radius=500"
    public = client.get(q).json()  # primero sin sesión: llena la caché, que no debe guardar clientes
    assert _names(public["items"], "nome_fantasia") == ["NEGOCIO_CERCA"]
    mine = client.get(q, headers=auth(a)).json()
    assert [(i["nome_fantasia"], i["origen"]) for i in mine["items"]] == [("A_CERCA", "cliente"), ("NEGOCIO_CERCA", "negocio")]
    assert mine["total"] == 2 and all(not set(i) & CONTACT for i in mine["items"])
    assert _names(client.get(q, headers=auth(b)).json()["items"], "nome_fantasia") == ["B_CERCA", "NEGOCIO_CERCA"]
    assert _names(client.get(q).json()["items"], "nome_fantasia") == ["NEGOCIO_CERCA"]


def test_patch_owner_only_and_fields(data, pg):
    a, b, ids = data
    cid = ids["a_sin"]
    assert client.patch(f"/api/clientes/{cid}", headers=auth(b), json={"atrasado": True}).status_code == 404
    assert client.patch(f"/api/clientes/{cid}", json={"atrasado": True}).status_code == 401
    r = client.patch(f"/api/clientes/{cid}", headers=auth(a),
                     json={"atrasado": True, "visita_diaria": False, "nombre_negocio": " Nuevo ", "nota": "n1",
                           "lat": -23.41, "lon": -51.43})
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["atrasado"], got["visita_diaria"], got["nombre_negocio"], got["nota"]) == (True, False, "Nuevo", "n1")
    assert (got["lat"], got["lon"], got["geocode_status"], got["geocode_source"]) == (-23.41, -51.43, "ok", "manual")
    assert got["municipio"] == "Arapongas"  # ciudad más cercana a las coords nuevas
    # solo cambia lo enviado; nota "" la borra
    r = client.patch(f"/api/clientes/{cid}", headers=auth(a), json={"nota": ""}).json()
    assert r["nota"] is None and r["nombre_negocio"] == "Nuevo" and r["lat"] == -23.41
    with pg.begin() as c:
        assert c.execute(text("SELECT atrasado FROM clientes WHERE id = :i"), {"i": ids["b_cerca"]}).scalar() is False


@pytest.mark.parametrize("body", [
    {"lat": -25.43, "lon": -51.2},  # lat fuera de Paraná
    {"lat": -23.4, "lon": -49.0},  # lon fuera
    {"lat": -51.9, "lon": -23.4},  # al revés
    {"lat": -23.4},  # sin lon
    {"atrasado": None},
    {"nombre_negocio": ""},
    {},
])
def test_patch_rejects_bad_input(data, body):
    a, _, ids = data
    assert client.patch(f"/api/clientes/{ids['a_sin']}", headers=auth(a), json=body).status_code == 422
