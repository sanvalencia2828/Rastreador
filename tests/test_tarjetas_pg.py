"""Ruta de tarjetas contra Postgres real: qué negocios entran, entregas, 7 días y aislamiento entre usuarios.

Se omite sin TEST_PG_URL (el job backend-test de CI lo define). Ejemplo local:

    docker run -d --rm --name scratch_pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=test_rastreador -p 55432:5432 postgis/postgis:15-3.4
    TEST_PG_URL=postgresql://postgres:x@localhost:55432/test_rastreador pytest tests/test_tarjetas_pg.py

Estos tests hacen DROP TABLE: la base debe llamarse test*; nunca apuntes a la de desarrollo.
"""

import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.security import create_jwt_token
from app.db.bootstrap import CLIENTES_DDL, TARJETA_ENTREGAS_DDL
from app.main import app
from app.routes import planned_routes
from app.routes import tarjetas as R

PG = os.environ.get("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="TEST_PG_URL no definido (Postgres desechable)")
client = TestClient(app)
CONTACT = re.compile(r"telefone|telefono|\bddd|correio|correo|\bemail|e_mail|complemento|\bfax\b", re.IGNORECASE)
LAT, LON = -23.4205, -51.9330  # centro de Maringá en cities.py
HOY = "(NOW() AT TIME ZONE 'America/Sao_Paulo')::date"

TABLES = "tarjeta_entregas, route_stops, routes, clientes, estabelecimentos"
SETUP = [
    """CREATE TABLE IF NOT EXISTS users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL DEFAULT 'x')""",
    """CREATE TABLE estabelecimentos (id SERIAL PRIMARY KEY, cnpj_completo VARCHAR(14) UNIQUE, nome_fantasia TEXT,
        situacao_cadastral INTEGER, cnae_fiscal INTEGER, descricao_tipo_logradouro TEXT, logradouro TEXT,
        numero TEXT, bairro TEXT, municipio TEXT, telefone_1 TEXT, correio_eletronico TEXT,
        latitude DECIMAL(10, 8), longitude DECIMAL(11, 8), geocoded BOOLEAN DEFAULT FALSE, business_type VARCHAR(20))""",
    """CREATE TABLE routes (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID, city_id INTEGER,
        name VARCHAR(255), start_lat NUMERIC(10,7), start_lng NUMERIC(10,7), status VARCHAR(20) NOT NULL DEFAULT 'planned',
        planned_at TIMESTAMPTZ DEFAULT NOW(), started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
        completed_date DATE, total_stops_planned INTEGER NOT NULL DEFAULT 0, total_stops_done INTEGER NOT NULL DEFAULT 0,
        total_distance_km DOUBLE PRECISION NOT NULL DEFAULT 0, total_duration_min DOUBLE PRECISION NOT NULL DEFAULT 0,
        notes TEXT)""",
    """CREATE TABLE route_stops (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE, business_id INTEGER REFERENCES estabelecimentos(id),
        stop_order INTEGER NOT NULL, visited BOOLEAN NOT NULL DEFAULT FALSE, visited_at TIMESTAMPTZ,
        skipped BOOLEAN NOT NULL DEFAULT FALSE, skip_reason TEXT, notes TEXT, address TEXT NOT NULL DEFAULT '',
        lat NUMERIC(10,7) NOT NULL DEFAULT 0, lon NUMERIC(10,7) NOT NULL DEFAULT 0, display_name TEXT)""",
    CLIENTES_DDL,
    TARJETA_ENTREGAS_DDL,
]

# (nombre, situacao, geocoded, lat, lon, municipio, tipo); cnpj = índice en 14 dígitos
NEGOCIOS = [
    ("OK_CERCA", 2, True, LAT, LON, "Maringá", "food"),
    ("OK_TECH", 2, True, LAT + 0.002, LON, "Maringá", "tech"),
    ("OK_LEJOS", 2, True, LAT + 0.01, LON, "Maringá", "food"),
    ("INACTIVO", 8, True, LAT, LON + 0.001, "Maringá", "food"),
    ("SIN_GEOCODIFICAR", 2, False, LAT, LON + 0.002, "Maringá", "food"),
    ("SIN_COORDS", 2, True, None, None, "Maringá", "food"),
    ("JUNTO_A_CLIENTE", 2, True, LAT - 0.003, LON, "Maringá", "food"),
    ("A_80M_DEL_CLIENTE", 2, True, LAT - 0.003 + 0.00072, LON, "Maringá", "food"),
    ("ENTREGADO", 2, True, LAT + 0.001, LON, "Maringá", "food"),
    ("MARIALVA", 2, True, -23.4855, -51.7927, "Marialva", "food"),
    ("ARAPONGAS", 2, True, -23.4194, -51.4244, "Arapongas", "food"),
]
CNPJ = {n[0]: f"{i:014d}" for i, n in enumerate(NEGOCIOS, 1)}


@pytest.fixture
def pg(monkeypatch):
    # not an assert: python -O would strip it and the fixture DROPs tables
    url = make_url(PG)
    if not (url.database or "").startswith("test") or url.host not in (None, "localhost", "127.0.0.1"):
        pytest.exit("TEST_PG_URL debe ser local y apuntar a una base cuyo nombre empiece por 'test'", returncode=2)
    engine = create_engine(PG)
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {TABLES} CASCADE"))
        for ddl in SETUP:
            c.execute(text(ddl))
        c.execute(text("DELETE FROM users"))
        for i, (nombre, sit, geo, lat, lon, mun, tipo) in enumerate(NEGOCIOS, 1):
            c.execute(text("""INSERT INTO estabelecimentos (cnpj_completo, nome_fantasia, situacao_cadastral, geocoded,
                                  latitude, longitude, municipio, business_type, logradouro, numero, bairro,
                                  telefone_1, correio_eletronico)
                              VALUES (:c, :n, :s, :g, :lat, :lon, :m, :t, 'RUA X', '1', 'ZONA 7', 'SECRET-TEL', 'SECRET-MAIL')"""),
                      {"c": f"{i:014d}", "n": nombre, "s": sit, "g": geo, "lat": lat, "lon": lon, "m": mun, "t": tipo})
    monkeypatch.setattr(R, "db_engine", engine)
    monkeypatch.setattr(planned_routes, "db_engine", engine)
    monkeypatch.delenv("OSRM_URL", raising=False)
    yield engine
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {TABLES} CASCADE"))
        c.execute(text("DELETE FROM users"))
    engine.dispose()


def _user(engine, name, cliente_en=None):
    with engine.begin() as c:
        uid = str(c.execute(text("INSERT INTO users(username) VALUES (:n) RETURNING id"), {"n": name}).scalar())
        if cliente_en:
            c.execute(text("""INSERT INTO clientes (user_id, external_id, nombre_negocio, lat, lon, geocode_status)
                              VALUES (:u, 'C1', 'Cliente', :lat, :lon, 'ok')"""),
                      {"u": uid, "lat": cliente_en[0], "lon": cliente_en[1]})
    return uid, {"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"}


def _ruta(headers, **body):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá"], **body}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["rutas"]


def _nombres(ruta):
    return [p["nombre"] for p in ruta["paradas"]]


def _entrega(headers, nombre, resultado="tarjeta_entregada", **extra):
    return client.post("/api/tarjetas/entregas", json={"cnpj": CNPJ[nombre], "resultado": resultado, **extra}, headers=headers)


def test_only_active_geocoded_undelivered_businesses_away_from_clients(pg):
    # cliente a 8 m de JUNTO_A_CLIENTE; A_80M_DEL_CLIENTE queda fuera del radio de 30 m
    _, h = _user(pg, "a", cliente_en=(LAT - 0.003 + 0.00007, LON))
    assert _entrega(h, "ENTREGADO").status_code == 200
    (ruta,) = _ruta(h)
    assert sorted(_nombres(ruta)) == ["A_80M_DEL_CLIENTE", "OK_CERCA", "OK_LEJOS", "OK_TECH"]
    assert ruta["route_id"]


def test_max_paradas_takes_the_nearest(pg):
    _, h = _user(pg, "a")
    (ruta,) = _ruta(h, max_paradas=2)
    assert sorted(_nombres(ruta)) == ["ENTREGADO", "OK_CERCA"]  # a 0 y 110 m del centro


def test_city_and_type_filters(pg):
    _, h = _user(pg, "a")
    assert _nombres(_ruta(h, cities=["Marialva"])[0]) == ["MARIALVA"]
    assert _nombres(_ruta(h, business_type="tech")[0]) == ["OK_TECH"]


def test_maringa_with_marialva_is_200_and_with_arapongas_is_422(pg):
    _, h = _user(pg, "a")
    (ruta,) = _ruta(h, cities=["Maringá", "Marialva"], juntar=True)
    assert "MARIALVA" in _nombres(ruta) and "OK_CERCA" in _nombres(ruta)
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá", "Arapongas"], "juntar": True}, headers=h)
    assert res.status_code == 422


def test_response_has_no_contact_data(pg):
    _, h = _user(pg, "a")
    res = client.post("/api/tarjetas/ruta", json={}, headers=h)
    assert res.status_code == 200 and "SECRET-" not in res.text and not CONTACT.search(res.text)


def test_cerrado_comes_back_after_7_days_and_not_before(pg):
    _, h = _user(pg, "a")
    assert _entrega(h, "OK_CERCA", "cerrado").status_code == 200
    assert "OK_CERCA" not in _nombres(_ruta(h)[0])
    with pg.begin() as c:
        c.execute(text(f"UPDATE tarjeta_entregas SET fecha = {HOY} - 6"))
    assert "OK_CERCA" not in _nombres(_ruta(h)[0])
    with pg.begin() as c:
        c.execute(text(f"UPDATE tarjeta_entregas SET fecha = {HOY} - 7"))
    assert "OK_CERCA" in _nombres(_ruta(h)[0])


def test_interesado_never_comes_back(pg):
    _, h = _user(pg, "a")
    _entrega(h, "OK_CERCA", "interesado")
    with pg.begin() as c:
        c.execute(text(f"UPDATE tarjeta_entregas SET fecha = {HOY} - 30"))
    assert "OK_CERCA" not in _nombres(_ruta(h)[0])


def test_same_day_retry_updates_the_row(pg):
    _, h = _user(pg, "a")
    _entrega(h, "OK_CERCA", "cerrado", nota="volver")
    assert _entrega(h, "OK_CERCA", "tarjeta_entregada", nota="ok").status_code == 200
    with pg.begin() as c:
        assert c.execute(text("SELECT resultado, nota FROM tarjeta_entregas")).fetchall() == [("tarjeta_entregada", "ok")]


def test_unknown_business_is_404(pg):
    _, h = _user(pg, "a")
    res = client.post("/api/tarjetas/entregas", json={"cnpj": "9" * 14, "resultado": "cerrado"}, headers=h)
    assert res.status_code == 404


def test_users_never_see_or_touch_each_others_deliveries(pg):
    ua, ha = _user(pg, "a")
    ub, hb = _user(pg, "b")
    (ruta_a,) = _ruta(ha)
    # B intenta escribir como A: el user_id del cuerpo se ignora y la parada de la ruta de A no se marca
    assert _entrega(hb, "OK_CERCA", user_id=ua, route_id=ruta_a["route_id"]).status_code == 200
    with pg.begin() as c:
        assert c.execute(text("SELECT user_id::text FROM tarjeta_entregas")).scalars().all() == [ub]
        assert c.execute(text("SELECT COUNT(*) FROM route_stops WHERE visited")).scalar() == 0
    assert "OK_CERCA" in _nombres(_ruta(ha)[0]) and "OK_CERCA" not in _nombres(_ruta(hb)[0])
    resumen_a = client.get("/api/tarjetas/resumen", headers=ha).json()
    resumen_b = client.get("/api/tarjetas/resumen", headers=hb).json()
    assert resumen_a["totales"]["total"] == 0 and resumen_b["totales"]["total"] == 1
    assert client.get(f"/api/tarjetas/ruta/{ruta_a['route_id']}", headers=hb).status_code == 404


def test_resume_shows_marked_stops_and_summary_counts(pg):
    _, h = _user(pg, "a")
    (ruta,) = _ruta(h)
    assert _entrega(h, "OK_CERCA", route_id=ruta["route_id"]).status_code == 200
    retomada = client.get(f"/api/tarjetas/ruta/{ruta['route_id']}", headers=h).json()
    assert [p["nombre"] for p in retomada["paradas"] if p["hecha"]] == ["OK_CERCA"]
    assert _nombres(retomada) == _nombres(ruta)
    maringa = next(c for c in client.get("/api/tarjetas/resumen", headers=h).json()["ciudades"] if c["ciudad"] == "Maringá")
    assert (maringa["hoy"], maringa["semana"], maringa["total"]) == (1, 1, 1)
    assert maringa["geocodificados"] == 6 and maringa["sin_tarjeta"] == 5  # activos + geocoded + coords


def test_city_without_geocoded_businesses_says_so(pg):
    _, h = _user(pg, "a")
    (ruta,) = _ruta(h, cities=["Mandaguari"])
    assert ruta["paradas"] == [] and ruta["route_id"] is None and "geocodificar" in ruta["aviso"]
