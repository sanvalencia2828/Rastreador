"""Ciudades, municipio/visita_diaria de clientes, generación con diarios, seed de 12 columnas y registro cerrado.

Sin base de datos real (los casos contra Postgres están en test_clientes_pg.py y test_generate_clientes_pg.py).
"""

import importlib.util
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import cities
from app.core.ratelimit import AttemptLimiter
from app.core.security import create_jwt_token
from app.db import bootstrap
from app.main import app
from app.routes import auth, clientes
from app.routes import planned_routes as pr

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(app)
UA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CID = "11111111-1111-1111-1111-111111111111"

spec = importlib.util.spec_from_file_location("seed_clientes", ROOT / "scripts" / "seed_clientes.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def h(uid=UA):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"}


@pytest.fixture(autouse=True)
def production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


# --- ciudades ---------------------------------------------------------------

@pytest.mark.parametrize("raw", ["Maringa", "MARINGÁ", "  maringá ", "MARINGA"])
def test_canonical_city(raw):
    assert cities.canonical_city(raw) == "Maringá"


def test_canonical_city_unknown_and_jandaia():
    assert cities.canonical_city("jandaia  do sul") == "Jandaia do Sul"
    assert cities.canonical_city("Londrina") is None and cities.canonical_city(None) is None


@pytest.mark.parametrize("lat,lon,city", [(-23.395231, -51.410862, "Arapongas"), (-23.6015504, -51.6378573, "Jandaia do Sul")])
def test_nearest_city(lat, lon, city):
    assert cities.nearest_city(lat, lon) == city


def test_nearest_city_far_away_is_none():
    assert cities.nearest_city(-25.43, -49.27) is None  # Curitiba


def test_frontend_city_list_matches_cities_py():
    ts = (ROOT / "frontend" / "src" / "app" / "lib" / "ciudades.ts").read_text(encoding="utf-8")
    front = [(n, float(a), float(o)) for n, a, o in re.findall(r'name: "([^"]+)", lat: ([-\d.]+), lon: ([-\d.]+)', ts)]
    assert front == [(c.name, c.lat, c.lon) for c in cities.CITIES]


def test_migration_010_and_bootstrap_ddl_are_identical():
    lines = (ROOT / "migrations" / "010_clientes_visita_diaria.sql").read_text(encoding="utf-8").splitlines()
    body = " ".join(line for line in lines if not line.startswith("--"))
    assert " ".join(body.split()) == " ".join(bootstrap.CLIENTES_VISITA_DIARIA_DDL.split())
    assert "ADD COLUMN IF NOT EXISTS visita_diaria BOOLEAN NOT NULL DEFAULT FALSE" in body


# --- POST / PATCH /api/clientes ---------------------------------------------

class Engine:
    """Guarda los parámetros; el UPDATE solo encuentra la fila si es del dueño (como el WHERE user_id)."""

    def __init__(self):
        self.params = None

    @contextmanager
    def begin(self):
        engine = self

        class Conn:
            def execute(self, statement, params):
                engine.params = dict(params)
                found = not str(statement).lstrip().startswith("UPDATE") or params["user_id"] == UA
                row = {"id": CID, "external_id": "x", "nombre_cliente": None, "nombre_negocio": "N", "direccion": None,
                       "bairro": None, "municipio": params.get("municipio") or "Maringá", "cep": None, "lat": None,
                       "lon": None, "geocode_status": "pendiente", "geocode_source": None, "nota": None,
                       "visita_diaria": bool(params.get("visita_diaria"))}
                return SimpleNamespace(fetchone=lambda: SimpleNamespace(_mapping=row) if found else None)

        yield Conn()


@pytest.fixture
def engine(monkeypatch):
    e = Engine()
    monkeypatch.setattr(clientes, "db_engine", e)
    return e


@pytest.mark.parametrize("body,city", [
    ({"lat": -23.395231, "lon": -51.410862}, "Arapongas"),
    ({"lat": -23.6015504, "lon": -51.6378573}, "Jandaia do Sul"),
    ({}, "Maringá"),  # sin coords
    ({"municipio": "APUCARANA", "lat": -23.395231, "lon": -51.410862}, "Apucarana"),  # explícito gana
])
def test_create_picks_municipio(engine, body, city):
    r = client.post("/api/clientes", headers=h(), json={"nombre_negocio": "N", **body})
    assert r.status_code == 201, r.text
    assert engine.params["municipio"] == city and engine.params["visita_diaria"] is False


def test_create_with_visita_diaria(engine):
    r = client.post("/api/clientes", headers=h(), json={"nombre_negocio": "N", "visita_diaria": True})
    assert r.status_code == 201 and engine.params["visita_diaria"] is True and r.json()["visita_diaria"] is True


@pytest.mark.parametrize("body", [{"municipio": "Londrina"}, {"lat": -25.43, "lon": -49.27}])
def test_create_unknown_or_far_city_is_422(engine, body):
    r = client.post("/api/clientes", headers=h(), json={"nombre_negocio": "N", **body})
    assert r.status_code == 422 and engine.params is None


def test_patch_own_cliente(engine):
    r = client.patch(f"/api/clientes/{CID}", headers=h(UA), json={"municipio": "arapongas", "visita_diaria": True})
    assert r.status_code == 200, r.text
    assert engine.params == {"municipio": "Arapongas", "visita_diaria": True, "atrasado": None, "nombre_negocio": None,
                             "nota": None, "set_nota": False, "lat": None, "lon": None, "id": CID, "user_id": UA}


def test_patch_other_users_cliente_is_404(engine):
    r = client.patch(f"/api/clientes/{CID}", headers=h(UB), json={"visita_diaria": True})
    assert r.status_code == 404 and engine.params["user_id"] == UB


@pytest.mark.parametrize("cid,body,code", [
    (CID, {}, 422),  # nada que cambiar
    (CID, {"municipio": "Londrina"}, 422),
    ("no-es-uuid", {"visita_diaria": True}, 422),
])
def test_patch_validates(engine, cid, body, code):
    assert client.patch(f"/api/clientes/{cid}", headers=h(), json=body).status_code == code
    assert engine.params is None


def test_patch_requires_login(engine):
    assert client.patch(f"/api/clientes/{CID}", json={"visita_diaria": True}).status_code == 401


# --- generación con diarios y varias ciudades -------------------------------

def _row(n, city, lat, lon, diaria=False):
    return SimpleNamespace(id=f"{n:08d}-0000-0000-0000-000000000000", nombre_negocio=f"N{n}", nombre_cliente="",
                           direccion="d", bairro="b", municipio=city, lat=lat, lon=lon, geocode_status="ok",
                           visita_diaria=diaria)


ARAPONGAS_DIARIO = _row(1, "Arapongas", -23.395, -51.411, diaria=True)
APUCARANA_DIARIO = _row(2, "APUCARANA", -23.552, -51.461, diaria=True)
NORMALES = [_row(10 + i, "Arapongas" if i % 2 else "Apucarana", -23.40 - i * 0.01, -51.42 - (i % 3) * 0.01) for i in range(12)]


@pytest.fixture
def rows(monkeypatch):
    data = []
    monkeypatch.setattr(pr, "db_engine", object())
    monkeypatch.setattr(pr, "_load_clientes", lambda uid: data)
    return data


def week(**body):
    return client.post("/api/routes/generate-week", headers=h(), json={"cities": ["Arapongas", "Apucarana"], **body})


def test_daily_clientes_appear_every_day(rows):
    rows += [ARAPONGAS_DIARIO, APUCARANA_DIARIO]
    r = week(days=5)
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    assert len(days) == 5
    for d in days:
        assert sorted(s["nome_fantasia"] for s in d["stops"]) == ["N1", "N2"]
        assert all(s["diario"] for s in d["stops"])


def test_non_daily_are_split_and_cap_counts_daily(rows):
    rows += [ARAPONGAS_DIARIO, APUCARANA_DIARIO, *NORMALES]
    r = week(days=5, max_stops=4)
    assert r.status_code == 200, r.text
    d = r.json()
    normal_seen = []
    for day in d["days"]:
        assert len(day["stops"]) <= 4  # tope incluye a los 2 diarios
        assert {"N1", "N2"} <= {s["nome_fantasia"] for s in day["stops"]}
        normal_seen += [s["nome_fantasia"] for s in day["stops"] if not s["diario"]]
    assert len(normal_seen) == len(set(normal_seen))  # cada no diario en un solo día
    assert len(normal_seen) + len(d["sin_asignar"]) == 12 and len(normal_seen) == 10  # 5 días x 2 lugares libres


def test_too_many_daily_for_the_cap_is_422(rows):
    rows += [ARAPONGAS_DIARIO, APUCARANA_DIARIO]
    r = week(max_stops=1)
    assert r.status_code == 422 and "2 clientes de visita diaria" in r.json()["detail"] and "tope es 1" in r.json()["detail"]


def test_one_day_generate_includes_daily_and_counts_them(rows, monkeypatch):
    rows += [ARAPONGAS_DIARIO, *NORMALES[:3]]

    class CityEngine:
        @contextmanager
        def connect(self):
            yield SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: ("Maringá",)))

    monkeypatch.setattr(pr, "db_engine", CityEngine())
    r = client.post("/api/routes/generate", headers=h(), json={"city_id": 1, "day": 4, "cities": ["Arapongas"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "N1" in [s["nome_fantasia"] for s in d["stops"] if s["diario"]]
    assert all(c >= 1 for c in d["day_counts"])  # el diario cuenta en todos los días


@pytest.mark.parametrize("cities_,msg", [(["Londrina"], "Ciudad desconocida"), ([], "al menos una ciudad")])
def test_bad_city_list_is_422(rows, cities_, msg):
    r = client.post("/api/routes/generate-week", headers=h(), json={"cities": cities_})
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_mix_over_60_km_is_422(rows, monkeypatch):
    # ninguna pareja real pasa de 60 km (la mayor es Maringá-Arapongas, ~52): se agrega una ciudad lejana de prueba
    monkeypatch.setitem(cities._BY_PLAIN, "curitiba", cities.City("Curitiba", None, -25.43, -49.27))
    r = client.post("/api/routes/generate-week", headers=h(), json={"cities": ["Maringá", "Curitiba"]})
    assert r.status_code == 422 and "más de 60 km" in r.json()["detail"]


def test_maringa_and_arapongas_allowed_with_warning(rows):
    r = client.post("/api/routes/generate-week", headers=h(), json={"cities": ["maringa", "Arapongas"]})
    assert r.status_code == 200 and len(r.json()["avisos"]) == 1 and "Maringá y Arapongas" in r.json()["avisos"][0]


def test_close_cities_have_no_warning(rows):
    assert week().json()["avisos"] == []


def test_default_cities_is_maringa(rows):
    rows += [_row(1, "Maringa", -23.42, -51.93), ARAPONGAS_DIARIO]
    d = client.post("/api/routes/generate-week", headers=h(), json={}).json()
    assert [s["nome_fantasia"] for day in d["days"] for s in day["stops"]] == ["N1"]
    assert [x["nombre"] for x in d["fuera_de_maringa"]] == ["N1"]  # el diario de Arapongas queda fuera


# --- seed -------------------------------------------------------------------

def _csv(tmp_path, header, *lines):
    p = tmp_path / "c.csv"
    p.write_text("\n".join([",".join(header), *lines]) + "\n", encoding="utf-8")
    return p


def test_seed_accepts_11_columns_and_normalizes_municipio(tmp_path):
    rows, errors = seed.parse_rows(_csv(tmp_path, seed.HEADER, "1,c,N,d,b,Maringa,,-23.4,-51.9,coords_del_enlace,"))
    assert errors == [] and rows[0]["municipio"] == "Maringá" and rows[0]["visita_diaria"] is None


def test_seed_accepts_12_columns(tmp_path):
    lines = [f"{i},c,N,d,b,{m},,,,pendiente_geocodificar,,{v}"
             for i, (m, v) in enumerate([("MARINGA", "si"), ("Arapongas", "No"), ("Jandaia do Sul", "1"),
                                         ("Mandaguari", "0"), ("x", "TRUE"), ("y", "false")])]
    rows, errors = seed.parse_rows(_csv(tmp_path, seed.HEADER_DIARIA, *lines))
    assert errors == []
    assert [r["visita_diaria"] for r in rows] == [True, False, True, False, True, False]
    assert [r["municipio"] for r in rows][:3] == ["Maringá", "Arapongas", "Jandaia do Sul"]


def test_seed_rejects_bad_visita_diaria_without_echoing_it(tmp_path):
    rows, errors = seed.parse_rows(_csv(tmp_path, seed.HEADER_DIARIA, "1,c,N,d,b,Maringa,,,,pendiente_geocodificar,,quizas"))
    assert rows == [] and errors == [(2, "visita_diaria", "invalido")]


def test_seed_rejects_other_headers(tmp_path):
    for header in (seed.HEADER + ["otra"], seed.HEADER_DIARIA[:-2] + ["visita_diaria"]):
        with pytest.raises(seed.SeedError):
            seed.parse_rows(_csv(tmp_path, header))


def test_seed_prints_only_counts(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")  # dry-run, sin base
    p =_csv(tmp_path, seed.HEADER_DIARIA, "1,ZZ-SECRETO,N,d,b,Maringa,,,,pendiente_geocodificar,,si")
    assert seed.main(["--csv", str(p), "--user", "u"]) == 0
    out = capsys.readouterr()
    assert "ZZ-SECRETO" not in out.out + out.err and "1 de visita diaria" in out.out


# --- registro ---------------------------------------------------------------

@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(auth, "db_engine", None)
    monkeypatch.setattr(auth, "register_limiter", AttemptLimiter(10, 3600))


@pytest.mark.parametrize("value", ["false", "FALSE", " False "])
def test_registration_closed(no_db, monkeypatch, value):
    monkeypatch.setenv("REGISTRATION_ENABLED", value)
    r = client.post("/auth/register", json={"username": "nuevo", "password": "una-clave-larga"})
    assert r.status_code == 403 and r.json()["detail"] == "Registro cerrado"


@pytest.mark.parametrize("value", [None, "true", ""])
def test_registration_open_by_default(no_db, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("REGISTRATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("REGISTRATION_ENABLED", value)
    r = client.post("/auth/register", json={"username": "nuevo", "password": "una-clave-larga"})
    assert r.status_code == 503  # pasó la compuerta; sin base responde 503
