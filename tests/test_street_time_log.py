"""street_time_log: derivación desde visited_at, refresco idempotente, /api/street-time y cambio a medias reales."""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.security import create_jwt_token
from app.db.bootstrap import STREETS_DDL
from app.main import app
from app.routes import street_time as street_time_routes
from app.services import street_time as T
from app.services.street_time_log import derive_street_durations, refresh_street_times

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


# ------------------------------------------------------------------ derivación pura
def test_duration_is_time_to_the_first_visit_of_the_next_street_and_last_street_is_dropped():
    rows, stats = derive_street_durations([
        (at(0), "Rua Curta"), (at(10), "RUA CURTA"), (at(30), "Rua Doutor João"), (at(50), "Rua Final"),
    ])
    assert rows == [("RUA|CURTA", 30 * 60, 2), ("RUA|DOUTOR JOAO", 20 * 60, 1)]
    assert stats["sin_siguiente"] == 1


def test_gaps_over_90_minutes_and_zero_gaps_are_discarded():
    rows, stats = derive_street_durations([
        (at(0), "Rua A"), (at(100), "Rua B"),   # 100 min: almuerzo / fin de jornada
        (at(100), "Rua C"),                     # mismo instante que B: sin duración
        (at(110), "Rua D"),
    ])
    assert rows == [("RUA|C", 10 * 60, 1)]
    assert stats["mas_de_90_min"] == 1 and stats["sin_duracion"] == 1


def test_street_visited_twice_not_consecutively_sums_and_input_order_does_not_matter():
    rows, _ = derive_street_durations([(at(40), "Rua A"), (at(0), "Rua A"), (at(10), "Rua B"), (at(50), "Rua B")])
    # sorted: A@0, B@10, A@40, B@50 -> A: 10 min + 10 min, B: 30 min (last B has no next)
    assert dict((k, s) for k, s, _ in rows) == {"RUA|A": 20 * 60, "RUA|B": 30 * 60}


def test_visits_without_a_street_name_are_ignored():
    rows, _ = derive_street_durations([(at(0), ""), (at(5), "  "), (at(10), "Rua A")])
    assert rows == []


# ------------------------------------------------------------------ con PostGIS
PG = os.environ.get("TEST_PG_URL")
UA, UB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
R1, R2, R3, RB = ("11111111-0000-0000-0000-00000000000%d" % i for i in range(1, 5))
DROP = "DROP TABLE IF EXISTS street_time_log, street_catalog, street_segments, visits CASCADE"


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
        c.execute(text(DROP))
        c.execute(text(STREETS_DDL))
        c.execute(text("CREATE TABLE visits (id SERIAL PRIMARY KEY, user_id UUID, route_id UUID, cnpj TEXT,"
                       " logradouro TEXT, visited_at TIMESTAMPTZ)"))
        for key, osm_key, n in (("RUA|CURTA", "RUA|CURTA", 5), ("RUA|DOUTOR JOAO", "RUA|DOUTOR JOAO", 4),
                                ("RUA|JOAO DOUTOR", "RUA|DOUTOR JOAO", 3)):
            c.execute(text("INSERT INTO street_catalog (municipio, street_key, osm_key, tipo, nombre, n_comercios_activos,"
                           " length_m, pareado_pct, estado) VALUES ('MARINGA', :k, :o, split_part(:k, '|', 1),"
                           " split_part(:k, '|', 2), :n, 300, 0, 'ok')"), {"k": key, "o": osm_key, "n": n})
    monkeypatch.setattr(street_time_routes, "db_engine", engine)
    yield engine
    with engine.begin() as c:
        c.execute(text(DROP))
    engine.dispose()


def _visits(engine, user, route, seq):
    with engine.begin() as c:
        for street, minutes in seq:
            c.execute(text("INSERT INTO visits (user_id, route_id, logradouro, visited_at) VALUES (:u, :r, :s, :t)"),
                      {"u": user, "r": route, "s": street, "t": at(minutes)})


def _logs(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT user_id::text, route_id::text, street_key, seconds, n_visitas FROM street_time_log"
                              " ORDER BY route_id, street_key")).fetchall()


def test_refresh_keeps_only_catalog_streets_and_is_idempotent_and_per_user(pg):
    _visits(pg, UA, R1, [("Rua Curta", 0), ("Rua Curta", 10), ("Rua Doutor João", 30), ("Rua Fora do Catalogo", 50), ("Rua Curta", 80)])
    _visits(pg, UB, RB, [("Rua Curta", 0), ("Rua Doutor João", 20), ("Rua Curta", 40)])
    with pg.begin() as c:
        stats = refresh_street_times(c, UA, R1)
    assert stats["registradas"] == 2 and stats["fuera_del_catalogo"] == 1
    expected = [(UA, R1, "RUA|CURTA", 1800, 2), (UA, R1, "RUA|DOUTOR JOAO", 1200, 1)]
    assert _logs(pg) == expected
    with pg.begin() as c:  # recomputing must not duplicate
        refresh_street_times(c, UA, R1)
    assert _logs(pg) == expected  # and never touches the other user's route


def _token(uid):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"}


def _calle(resp, name):
    return next(c for c in resp.json()["calles"] if c["calle"] == name)


def test_street_time_pools_spellings_and_switches_to_real_at_n_min(pg):
    client = TestClient(app)
    # two routes, one per spelling of the same OSM street: 20 min each
    for route, spelling in ((R1, "Rua Doutor João"), (R2, "Rua João Doutor")):
        _visits(pg, UA, route, [(spelling, 0), ("Rua Curta", 20), ("Rua Curta", 25)])
        with pg.begin() as c:
            refresh_street_times(c, UA, route)
    resp = client.get("/api/street-time", headers=_token(UA))
    assert resp.status_code == 200
    joao = _calle(resp, "RUA DOUTOR JOAO")
    assert joao["n_real"] == 2 and joao["tiempo_real_min"] == 20.0 and joao["tiempo_usado"] == "estimado"
    est = 300 / (4000 / 60) + 2 * 7  # 7 commerces = 4 + 3 merged
    assert joao["tiempo_estimado_min"] == pytest.approx(est, abs=0.1)
    assert joao["diferencia_min"] == pytest.approx(20.0 - est, abs=0.2)
    assert resp.json()["supuestos"]["estimado"] is True

    _visits(pg, UA, R3, [("Rua Doutor João", 0), ("Rua Curta", 10), ("Rua Curta", 12)])
    with pg.begin() as c:
        refresh_street_times(c, UA, R3)
    joao = _calle(client.get("/api/street-time", headers=_token(UA)), "RUA DOUTOR JOAO")
    assert joao["n_real"] == 3 and joao["tiempo_usado"] == "real"  # median of 20, 20, 10 minutes
    assert joao["tiempo_real_min"] == 20.0


def test_street_time_only_shows_the_callers_own_logs(pg):
    _visits(pg, UB, RB, [("Rua Curta", 0), ("Rua Doutor João", 20), ("Rua Curta", 40)])
    with pg.begin() as c:
        refresh_street_times(c, UB, RB)
    assert _logs(pg)  # exists for B
    assert TestClient(app).get("/api/street-time", headers=_token(UA)).json()["calles"] == []
    assert len(TestClient(app).get("/api/street-time", headers=_token(UB)).json()["calles"]) == 2


def test_estimate_constants_are_the_documented_defaults():
    assert (T.WALK_SPEED_KMH, T.MIN_PER_LOCAL, T.N_MIN_REAL) == (4.0, 2.0, 3)
