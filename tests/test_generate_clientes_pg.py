"""/api/routes/generate para Maringa con los clientes del usuario, contra Postgres real (omitido sin TEST_PG_URL).

La base debe llamarse test* y ser local: estos tests hacen DROP TABLE.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.security import create_jwt_token
from app.db import bootstrap
from app.db.bootstrap import CLIENTES_DDL
from app.main import app
from app.routes import cities, planned_routes

PG = os.environ.get("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="TEST_PG_URL no definido (Postgres desechable)")

DDL = [
    "DROP TABLE IF EXISTS route_stops, routes, clientes, cities, users CASCADE",
    """CREATE TABLE users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL DEFAULT 'x')""",
    """CREATE TABLE cities (id SERIAL PRIMARY KEY, name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PR',
        lat NUMERIC(10,7), lon NUMERIC(10,7), UNIQUE (name, state))""",
    """CREATE TABLE routes (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID, city_id INTEGER REFERENCES cities(id),
        name VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())""",
    """CREATE TABLE route_stops (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), route_id UUID REFERENCES routes(id) ON DELETE CASCADE,
        stop_order INTEGER NOT NULL, address TEXT NOT NULL, lat NUMERIC(10,7) NOT NULL, lon NUMERIC(10,7) NOT NULL,
        cep VARCHAR(10), display_name TEXT)""",
    CLIENTES_DDL,
]


@pytest.fixture
def pg(monkeypatch):
    url = make_url(PG)
    if not (url.database or "").startswith("test") or url.host not in (None, "localhost", "127.0.0.1"):
        pytest.exit("TEST_PG_URL debe ser local y apuntar a una base cuyo nombre empiece por 'test'", returncode=2)
    engine = create_engine(PG)
    with engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
    for mod in (bootstrap, planned_routes, cities):
        monkeypatch.setattr(mod, "db_engine", engine)
    monkeypatch.setenv("APP_ENV", "production")
    bootstrap._ensure_route_stops_cliente_id()  # agrega route_stops.cliente_id
    bootstrap._ensure_maringa_city()
    yield engine
    with engine.begin() as c:  # route_stops.cliente_id (FK) bloquearia el DROP TABLE clientes de otros tests
        c.execute(text("DROP TABLE IF EXISTS route_stops, routes, cities CASCADE"))
    engine.dispose()


def _user(engine, name):
    with engine.begin() as c:
        return str(c.execute(text("INSERT INTO users(username) VALUES (:n) RETURNING id"), {"n": name}).scalar())


def _cliente(engine, uid, n, municipio="Maringa", lat=-23.42, lon=-51.93, status="ok", name=None):
    if status != "ok":
        lat = lon = None
    with engine.begin() as c:
        c.execute(
            text("""INSERT INTO clientes(user_id, external_id, nombre_cliente, nombre_negocio, direccion, bairro,
                    municipio, lat, lon, geocode_status, geocode_source)
                    VALUES (:u, :e, 'c', :nm, 'Rua X', 'Zona 1', :m, :la, :lo, :s, CASE WHEN :s = 'ok' THEN 'usuario' END)"""),
            {"u": uid, "e": str(n), "nm": name or f"Neg {n}", "m": municipio, "la": lat, "lo": lon, "s": status},
        )


def _h(uid):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"}


def _maringa_id(engine):
    with engine.begin() as c:
        return c.execute(text("SELECT id FROM cities WHERE name = 'Maringá'")).scalar()


def test_maringa_city_migration_is_idempotent(pg):
    bootstrap._ensure_maringa_city()
    bootstrap._ensure_route_stops_cliente_id()
    with pg.begin() as c:
        assert c.execute(text("SELECT count(*) FROM cities WHERE name = 'Maringá' AND state = 'PR'")).scalar() == 1


def test_generate_uses_only_own_clientes_caps_at_10_and_lists_the_rest(pg):
    a, b = _user(pg, "a"), _user(pg, "b")
    for i in range(12):  # 12 en Maringa, en linea: el tope es 10
        _cliente(pg, a, i, lat=-23.42 - i / 1000)
    _cliente(pg, a, 100, municipio="Mandaguari", lat=-23.54, lon=-51.70, name="Fuera-A")
    _cliente(pg, a, 101, municipio="Apucarana", lat=-23.55, lon=-51.46, name="Fuera-B")
    _cliente(pg, a, 102, status="pendiente", name="Pend-A")
    _cliente(pg, b, 200, name="SECRETO-DE-B")
    r = TestClient(app).post("/api/routes/generate", headers=_h(a), json={"city_id": _maringa_id(pg), "max_lojas": 80})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["selected"] == 10 and d["total_candidates"] == 12 and len(d["stops"]) == 10
    assert all(s["cliente_id"] and s["cnpj"] == "" for s in d["stops"])
    assert sorted(x["nombre"] for x in d["fuera_de_maringa"]) == ["Fuera-A", "Fuera-B"]
    assert [x["nombre"] for x in d["pendientes"]] == ["Pend-A"]
    assert d["distance_kind"] == "linea_recta" and d["distance_km"] > 0
    assert len(d["maps_links"]) == 1 and all("google.com/maps/dir" in u for u in d["maps_links"])  # 10 puntos caben en un enlace
    assert "SECRETO-DE-B" not in r.text


def test_generate_requires_login(pg):
    assert TestClient(app).post("/api/routes/generate", json={"city_id": _maringa_id(pg)}).status_code == 401


def test_saved_route_keeps_cliente_id_and_rejects_foreign_ones(pg):
    a, b = _user(pg, "a"), _user(pg, "b")
    _cliente(pg, a, 1)
    _cliente(pg, b, 2)
    with pg.begin() as c:
        mine = str(c.execute(text("SELECT id FROM clientes WHERE user_id = :u"), {"u": a}).scalar())
        theirs = str(c.execute(text("SELECT id FROM clientes WHERE user_id = :u"), {"u": b}).scalar())
    cid = _maringa_id(pg)
    client = TestClient(app)

    def save(cliente_id):
        stop = {"address": "Rua X", "lat": -23.42, "lon": -51.93, "cliente_id": cliente_id}
        return client.post(f"/api/cities/{cid}/routes", headers=_h(a), json={"name": "R", "city_id": cid, "stops": [stop]})

    assert save(theirs).status_code == 403
    assert save("no-es-uuid").status_code == 400
    with pg.begin() as c:
        assert c.execute(text("SELECT count(*) FROM routes")).scalar() == 0  # nada se guardo
    assert save(mine).status_code == 200
    with pg.begin() as c:
        assert str(c.execute(text("SELECT cliente_id FROM route_stops")).scalar()) == mine
