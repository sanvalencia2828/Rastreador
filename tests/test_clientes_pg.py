"""clientes contra Postgres real: DDL, seed y GET /api/clientes con dos usuarios.

Se omite sin TEST_PG_URL (el job de CI no tiene servicio Postgres). Ejemplo local:

    docker run -d --rm --name scratch_pg -e POSTGRES_PASSWORD=x -e POSTGRES_DB=test_rastreador -p 55432:5432 postgis/postgis:15-3.4
    TEST_PG_URL=postgresql://postgres:x@localhost:55432/test_rastreador pytest tests/test_clientes_pg.py

Estos tests hacen DROP TABLE clientes: la base debe llamarse test*; nunca apuntes a la de desarrollo.
"""

import importlib.util
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.core.security import create_jwt_token
from app.db.bootstrap import CLIENTES_DDL
from app.main import app
from app.routes import clientes

PG = os.environ.get("TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG, reason="TEST_PG_URL no definido (Postgres desechable)")

spec = importlib.util.spec_from_file_location(
    "seed_clientes", Path(__file__).resolve().parent.parent / "scripts" / "seed_clientes.py"
)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

USERS_DDL = """CREATE TABLE IF NOT EXISTS users (id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL DEFAULT 'x')"""


@pytest.fixture
def pg():
    assert make_url(PG).database.startswith("test"), "TEST_PG_URL debe apuntar a una base cuyo nombre empiece por 'test'"
    engine = create_engine(PG)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS clientes"))
        c.execute(text(USERS_DDL))
        c.execute(text("DELETE FROM users"))
        c.execute(text(CLIENTES_DDL))
    yield engine
    engine.dispose()


def _user(engine, name):
    with engine.begin() as c:
        return str(c.execute(text("INSERT INTO users(username) VALUES (:n) RETURNING id"), {"n": name}).scalar())


def _csv(tmp_path, *lines):
    p = tmp_path / "c.csv"
    p.write_text("\n".join([",".join(seed.HEADER), *lines]) + "\n", encoding="utf-8")
    rows, errors = seed.parse_rows(p)
    assert errors == []
    return rows


def _upsert(engine, uid, rows):
    with engine.begin() as c:
        c.execute(seed.UPSERT, [{**r, "user_id": uid} for r in rows])


def _state(engine, uid):
    with engine.begin() as c:
        got = c.execute(text("SELECT external_id, nombre_negocio, geocode_status, geocode_source, lat FROM clientes "
                             "WHERE user_id = :u ORDER BY 1"), {"u": uid}).fetchall()
    return [(g[0], g[1], g[2], g[3], float(g[4]) if g[4] is not None else None) for g in got]


def test_ddl_checks_reject_bad_rows_and_ddl_is_idempotent(pg):
    uid = _user(pg, "u")
    with pg.begin() as c:
        c.execute(text(CLIENTES_DDL))  # segunda ejecución: sin error
    bad = [
        ("ok", None, None, None),  # ok sin coords
        ("pendiente", 95, -51, None),  # lat fuera de rango
        ("pendiente", -23, -181, None),  # lon fuera de rango
        ("pendiente", -23, None, None),  # lat sin lon
        ("pendiente", None, -51, None),  # lon sin lat
        ("pendiente", None, None, "otro"),  # fuente desconocida
    ]
    for status, lat, lon, src in bad:
        with pytest.raises(IntegrityError):
            with pg.begin() as c:
                c.execute(text("INSERT INTO clientes(user_id, external_id, geocode_status, lat, lon, geocode_source) "
                               "VALUES (:u, 'x', :s, :la, :lo, :src)"), {"u": uid, "s": status, "la": lat, "lo": lon, "src": src})
    with pg.begin() as c:
        for i, src in enumerate(("usuario", "nominatim", "manual")):
            c.execute(text("INSERT INTO clientes(user_id, external_id, geocode_status, lat, lon, geocode_source) "
                           "VALUES (:u, :e, 'ok', -23, -51, :src)"), {"u": uid, "e": str(i), "src": src})


def test_ddl_upgrades_a_table_created_by_the_first_draft(pg):
    with pg.begin() as c:  # forma del primer borrador: sin coords_pair y sin 'manual'
        c.execute(text("DROP TABLE clientes"))
        c.execute(text("""CREATE TABLE clientes (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL,
            external_id VARCHAR(64) NOT NULL, nombre_negocio TEXT, lat NUMERIC(10,7), lon NUMERIC(10,7),
            geocode_status VARCHAR(20) NOT NULL DEFAULT 'pendiente', geocode_source VARCHAR(20),
            CONSTRAINT clientes_geocode_source_check CHECK (geocode_source IS NULL OR geocode_source IN ('usuario', 'nominatim')))"""))
        c.execute(text("ALTER TABLE clientes ADD COLUMN nombre_cliente TEXT, ADD COLUMN direccion TEXT, ADD COLUMN bairro TEXT, "
                       "ADD COLUMN municipio TEXT, ADD COLUMN cep VARCHAR(10), ADD COLUMN nota TEXT, "
                       "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"))
    for _ in range(2):
        with pg.begin() as c:
            c.execute(text(CLIENTES_DDL))
    uid = _user(pg, "u")
    with pytest.raises(IntegrityError):
        with pg.begin() as c:
            c.execute(text("INSERT INTO clientes(user_id, external_id, lat) VALUES (:u, 'a', -23)"), {"u": uid})
    with pg.begin() as c:
        c.execute(text("INSERT INTO clientes(user_id, external_id, geocode_source) VALUES (:u, 'b', 'manual')"), {"u": uid})


def test_reseed_is_idempotent_keeps_resolved_coords_and_never_touches_manual_rows(pg, tmp_path):
    uid = _user(pg, "u")
    ok = "coords_del_enlace"
    _upsert(pg, uid, _csv(tmp_path, f"1,a,n1,d,b,m,c,-23.4,-51.9,{ok},", "2,a,n2,d,b,m,c,,,pendiente_geocodificar,"))
    _upsert(pg, uid, _csv(tmp_path, f"1,a,n1,d,b,m,c,-23.4,-51.9,{ok},", "2,a,n2,d,b,m,c,,,pendiente_geocodificar,"))
    assert _state(pg, uid) == [("1", "n1", "ok", "usuario", -23.4), ("2", "n2", "pendiente", None, None)]
    # una fila pendiente del CSV no borra coordenadas ya resueltas (fila 1) …
    _upsert(pg, uid, _csv(tmp_path, "1,a,n1,d,b,m,c,,,pendiente_geocodificar,"))
    assert _state(pg, uid)[0] == ("1", "n1", "ok", "usuario", -23.4)
    # … el CSV sí sobrescribe 'nominatim' …
    with pg.begin() as c:
        c.execute(text("UPDATE clientes SET geocode_source='nominatim', lat=-1, lon=-1 WHERE user_id=:u AND external_id='1'"), {"u": uid})
    _upsert(pg, uid, _csv(tmp_path, f"1,a,n1,d,b,m,c,-23.4,-51.9,{ok},"))
    assert _state(pg, uid)[0] == ("1", "n1", "ok", "usuario", -23.4)
    # … y nunca toca 'manual', ni con coords ni con otro nombre
    with pg.begin() as c:
        c.execute(text("UPDATE clientes SET geocode_source='manual', lat=-9, lon=-9, geocode_status='ok' WHERE user_id=:u AND external_id='1'"), {"u": uid})
    _upsert(pg, uid, _csv(tmp_path, f"1,a,CAMBIO,d,b,m,c,-23.4,-51.9,{ok},"))
    assert _state(pg, uid)[0] == ("1", "n1", "ok", "manual", -9.0)


def test_seed_main_apply_end_to_end_reports_skipped_manual_rows(pg, tmp_path, monkeypatch, capsys):
    import app.core.database as database
    import app.db.bootstrap as bootstrap

    uid = _user(pg, "dueno")
    monkeypatch.setattr(database, "db_engine", pg)
    monkeypatch.setattr(bootstrap, "db_engine", pg)
    monkeypatch.setenv("APP_ENV", "development")
    p = tmp_path / "c.csv"
    p.write_text("\n".join([",".join(seed.HEADER), "1,a,n,d,b,m,c,-23.4,-51.9,coords_del_enlace,",
                            "2,a,n,d,b,m,c,,,pendiente_geocodificar,"]) + "\n", encoding="utf-8")
    assert seed.main(["--csv", str(p), "--user", "dueno", "--apply"]) == 0
    with pg.begin() as c:
        c.execute(text("UPDATE clientes SET geocode_source='manual' WHERE user_id=:u AND external_id='1'"), {"u": uid})
    capsys.readouterr()
    assert seed.main(["--csv", str(p), "--user", "dueno", "--apply"]) == 0
    assert "Cargadas 1 filas; 1 omitidas" in capsys.readouterr().out
    assert seed.main(["--csv", str(p), "--user", "nadie", "--apply"]) == 1


def test_get_clientes_isolates_two_users_on_real_postgres(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(clientes, "db_engine", pg)
    a, b, c_ = _user(pg, "a"), _user(pg, "b"), _user(pg, "sin_filas")
    ok = "coords_del_enlace"
    _upsert(pg, a, _csv(tmp_path, f"1,x,Zeta,d,b,m,c,-23.4,-51.9,{ok},", "2,x,Alfa,d,b,m,c,,,pendiente_geocodificar,"))
    _upsert(pg, b, _csv(tmp_path, f"1,y,Solo de B,d,b,m,c,-23.5,-51.8,{ok},"))  # mismo external_id que A: no choca
    client = TestClient(app)

    def get(uid, query=""):
        return client.get(f"/api/clientes{query}", headers={"Authorization": f"Bearer {create_jwt_token({'user_id': uid})}"})

    ra, rb, rc = get(a), get(b), get(c_)
    assert [r["nombre_negocio"] for r in ra.json()] == ["Alfa", "Zeta"]  # orden por nombre_negocio
    assert [r["nombre_negocio"] for r in rb.json()] == ["Solo de B"]
    assert rc.status_code == 200 and rc.json() == []
    assert "Solo de B" not in ra.text and "Alfa" not in rb.text and "Zeta" not in rb.text
    assert ra.json()[1]["lat"] == -23.4 and ra.json()[0]["lat"] is None
    assert [r["nombre_negocio"] for r in get(a, "?limit=1").json()] == ["Alfa"]
    assert get(a, "?limit=501").status_code == 422
