"""GET /api/clientes/streets-nearby contra PostGIS real (se omite sin TEST_PG_URL con PostGIS) + piezas puras."""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.security import create_jwt_token
from app.db.bootstrap import CLIENTES_DDL, STREETS_DDL
from app.main import app
from app.routes import streets as streets_routes
from app.services import street_time as T

ROOT = Path(__file__).resolve().parent.parent


def _norm(sql):
    return re.sub(r"\s+", " ", sql).strip()


def test_streets_ddl_is_identical_in_bootstrap_and_migration():
    migration = (ROOT / "migrations" / "006_street_catalog.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    body = migration.split("\n", 2)[2]
    assert _norm(body) == _norm(STREETS_DDL)


# ------------------------------------------------------------------ piezas puras
def _row(**kw):
    base = {"id": 1, "street_key": "RUA|X", "osm_key": "RUA|X", "tipo": "RUA", "nombre": "X", "n_comercios_activos": 5,
            "numero_min": 10, "numero_max": 90, "ceps": ["87000000"], "length_m": 300.0, "pareado_pct": 0,
            "estado": "ok", "dist_m": 104.0}
    return {**base, **kw}


def test_estimate_formula_and_supuestos_are_marked():
    assert T.estimate_minutes(300, 5, 4, 2) == pytest.approx(300 / (4000 / 60) + 10)
    assert T.supuestos(4, 2) == {"velocidad_kmh": 4, "min_por_local": 2, "origen": "default", "estimado": True}
    assert T.supuestos(5, 2)["origen"] == "usuario"


def test_few_commerces_are_hidden_and_not_estimated():
    v = T.street_view(T.merge_catalog_rows([_row(n_comercios_activos=2)])[0], 4, 2)
    assert v["comercios_activos"] == "<3" and v["numero_min"] is None and v["tiempo_min"] is None
    assert v["en_plan_automatico"] is False


@pytest.mark.parametrize(
    "kw,fragment",
    [({"estado": "calle_larga"}, "calle larga"), ({"estado": "ambigua"}, "ambigua"),
     ({"pareado_pct": 50}, "calzada doble"), ({"estado": "sin_geometria"}, "sin_geometria")],
)
def test_unreliable_streets_have_a_reason_and_no_estimate(kw, fragment):
    v = T.street_view(T.merge_catalog_rows([_row(**kw)])[0], 4, 2)
    assert v["tiempo_estimado_min"] is None and fragment in v["tiempo_motivo"] and v["en_plan_automatico"] is False


def test_real_median_replaces_estimate_only_from_n_min():
    m = T.merge_catalog_rows([_row()])[0]
    few = T.street_view(m, 4, 2, {"RUA|X": (T.N_MIN_REAL - 1, 600.0)})
    assert few["tiempo_usado"] == "estimado" and few["tiempo_real_min"] == 10.0 and few["n_real"] == T.N_MIN_REAL - 1
    enough = T.street_view(m, 4, 2, {"RUA|X": (T.N_MIN_REAL, 600.0)})
    assert enough["tiempo_usado"] == "real" and enough["tiempo_min"] == 10.0 and enough["tiempo_estimado_min"] is not None


def test_rows_sharing_an_osm_street_are_merged():
    merged = T.merge_catalog_rows([
        _row(id=1, street_key="RUA|DOUTOR JOAO", osm_key="RUA|DOUTOR JOAO", n_comercios_activos=4, numero_min=20, numero_max=80),
        _row(id=2, street_key="RUA|JOAO DOUTOR", osm_key="RUA|DOUTOR JOAO", n_comercios_activos=3, numero_min=5,
             numero_max=300, dist_m=50.0),
    ])
    assert len(merged) == 1
    m = merged[0]
    assert (m["n_comercios_activos"], m["numero_min"], m["numero_max"], m["dist_m"]) == (7, 5, 300, 50.0)
    assert m["street_keys"] == ["RUA|DOUTOR JOAO", "RUA|JOAO DOUTOR"]


# ------------------------------------------------------------------ endpoint con PostGIS
PG = os.environ.get("TEST_PG_URL")
UA, UB = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
P_LAT, P_LON = -23.4205, -51.9331
DROP = "DROP TABLE IF EXISTS street_time_log, street_catalog, street_segments, clientes, users CASCADE"

# key, osm_key, n comercios, length_m, pareado_pct, estado, longitud (0.001 deg lon ~ 102 m del cliente)
CATALOG = [
    ("RUA|CURTA", "RUA|CURTA", 5, 300, 0, "ok", -51.9321),
    ("RUA|DOUTOR JOAO", "RUA|DOUTOR JOAO", 4, 200, 0, "ok", -51.9316),
    ("RUA|JOAO DOUTOR", "RUA|DOUTOR JOAO", 3, 200, 0, "ok", None),
    ("RUA|POUCOS", "RUA|POUCOS", 2, 100, 0, "ok", -51.9311),
    ("AVENIDA|LARGA", "AVENIDA|LARGA", 150, 4000, 0, "calle_larga", -51.9306),
    ("AVENIDA|DUPLA", "AVENIDA|DUPLA", 10, 800, 50, "ok", -51.9303),
    ("RUA|LEJOS", "RUA|LEJOS", 9, 200, 0, "ok", -51.9271),
]
CLIENTES = [
    {"u": UA, "e": "mga", "m": "Maringá", "la": P_LAT, "lo": P_LON, "s": "ok"},
    {"u": UA, "e": "mand", "m": "Mandaguari", "la": -23.54, "lo": -51.70, "s": "ok"},
    {"u": UA, "e": "sincoords", "m": "Maringa", "la": None, "lo": None, "s": "pendiente"},
    {"u": UB, "e": "ajeno", "m": "Maringa", "la": P_LAT, "lo": P_LON, "s": "ok"},
]


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
        c.execute(text("CREATE TABLE users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), username TEXT,"
                       " password_hash TEXT DEFAULT 'x')"))
        c.execute(text(CLIENTES_DDL))
        c.execute(text(STREETS_DDL))
        for uid, name in ((UA, "a"), (UB, "b")):
            c.execute(text("INSERT INTO users (id, username) VALUES (:i, :n)"), {"i": uid, "n": name})
        for key, osm_key, n, length, par, estado, lon in CATALOG:
            c.execute(text(
                "INSERT INTO street_catalog (municipio, street_key, osm_key, tipo, nombre, n_comercios_activos,"
                " numero_min, numero_max, ceps, length_m, pareado_pct, estado) VALUES ('MARINGA', :k, :o,"
                " split_part(:k, '|', 1), split_part(:k, '|', 2), :n, 10, 90, ARRAY['87000000'], :l, :p, :e)"),
                {"k": key, "o": osm_key, "n": n, "l": length, "p": par, "e": estado})
            if lon is not None:
                wkt = f"LINESTRING({lon} -23.4205, {lon} -23.4195)"
                c.execute(text("INSERT INTO street_segments (municipio, street_key, name, geom, length_m) VALUES"
                               " ('MARINGA', :o, :o, ST_GeomFromText(:w, 4326), :l)"), {"o": osm_key, "w": wkt, "l": length})
        for args in CLIENTES:
            c.execute(text("INSERT INTO clientes (user_id, external_id, nombre_negocio, municipio, lat, lon, geocode_status)"
                           " VALUES (:u, :e, 'SECRETO NEGOCIO', :m, :la, :lo, :s)"), args)
    monkeypatch.setattr(streets_routes, "db_engine", engine)
    yield engine
    with engine.begin() as c:
        c.execute(text(DROP))
    engine.dispose()


def _get(query="", uid=UA):
    token = create_jwt_token({"user_id": uid})
    return TestClient(app).get(f"/api/clientes/streets-nearby{query}", headers={"Authorization": f"Bearer {token}"})


def _by_ext(resp):
    return {c["external_id"]: c for c in resp.json()["clientes"]}


def test_nearby_streets_estimates_merge_and_reasons(pg):
    resp = _get("?radio_m=300")
    assert resp.status_code == 200
    body = resp.json()
    assert body["supuestos"] == {"velocidad_kmh": 4.0, "min_por_local": 2.0, "origen": "default", "estimado": True}
    calles = {c["calle"]: c for c in _by_ext(resp)["mga"]["calles"]}
    assert "RUA LEJOS" not in calles  # fuera del radio
    assert calles["RUA CURTA"]["tiempo_estimado_min"] == pytest.approx(300 / (4000 / 60) + 10, abs=0.1)
    assert calles["RUA CURTA"]["en_plan_automatico"] is True
    assert calles["RUA DOUTOR JOAO"]["comercios_activos"] == 7  # dos grafías fusionadas
    assert calles["RUA POUCOS"]["comercios_activos"] == "<3" and calles["RUA POUCOS"]["numero_min"] is None
    assert "calle larga" in calles["AVENIDA LARGA"]["tiempo_motivo"]
    assert calles["AVENIDA LARGA"]["en_plan_automatico"] is False
    assert "calzada doble" in calles["AVENIDA DUPLA"]["tiempo_motivo"]
    assert body["calles_unicas"] == 5


def test_clients_without_street_data_say_so_explicitly(pg):
    by = _by_ext(_get())
    assert by["mand"]["calles"] is None and by["mand"]["calles_estado"] == "sin_datos_de_calles"
    assert "Mandaguari" in by["mand"]["calles_motivo"]
    assert by["sincoords"]["calles"] is None and by["sincoords"]["calles_estado"] == "sin_coordenadas"


def test_radius_overrides_and_isolation(pg):
    near = {c["calle"] for c in _by_ext(_get("?radio_m=120"))["mga"]["calles"]}
    assert near == {"RUA CURTA"}
    resp = _get("?radio_m=300&velocidad_kmh=5&min_por_local=3")
    assert resp.json()["supuestos"]["origen"] == "usuario"
    assert set(_by_ext(resp)) == {"mga", "mand", "sincoords"}  # nunca el cliente de otro usuario
    assert set(_by_ext(_get(uid=UB))) == {"ajeno"}


def test_response_has_no_business_names_contact_or_coordinates(pg):
    body = _get().text
    for forbidden in ("SECRETO", "nombre_negocio", "telefone", "correo", "email", str(P_LAT), str(P_LON)):
        assert forbidden not in body
    assert "OpenStreetMap" in json.loads(body)["atribucion"]
