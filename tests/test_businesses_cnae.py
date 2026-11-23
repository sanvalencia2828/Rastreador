"""cnae_label no es columna de estabelecimentos: las consultas seleccionan cnae_fiscal y el rótulo se calcula en Python.

Sin base: se captura el SQL enviado. Con TEST_PG_URL (base local test*): se ejecutan contra el esquema real.
"""

import os
import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.base_schema import BASE_DDL
from app.main import app
from app.routes import businesses

client = TestClient(app)
PG = os.environ.get("TEST_PG_URL")
URLS = ["/api/businesses/search?q=pizza", "/api/businesses/clients", "/api/businesses/city-category?city=Maringa"]
ROW = ("00000000000191", "Pizzaria", 5620104, "ZONA 7", "RUA X", "Maringá", -23.42, -51.93)
CITY_ROW = ROW[:3] + ("Restaurantes",) + ROW[3:]


class CaptureEngine:
    def __init__(self, fail=False):
        self.sql, self.fail = [], fail

    @contextmanager
    def connect(self):
        engine = self

        class Conn:
            def execute(self, statement, params):
                engine.sql.append(str(statement))
                if engine.fail:
                    raise RuntimeError('relation "secreta" column e.cnae_label does not exist')
                row = CITY_ROW if "cnae_fiscal_descricao" in str(statement).split("FROM")[0] else ROW
                return type("Res", (), {"fetchall": lambda _: [row]})()

        yield Conn()


@pytest.mark.parametrize("url", URLS)
def test_queries_do_not_select_cnae_label_and_compute_it(url, monkeypatch):
    eng = CaptureEngine()
    monkeypatch.setattr(businesses, "db_engine", eng)
    res = client.get(url)
    assert res.status_code == 200, res.text
    sql = re.sub(r"--[^\n]*", "", eng.sql[0])  # los comentarios SQL pueden nombrarla
    assert "cnae_label" not in sql
    assert "cnae_fiscal" in sql
    assert res.json()[0]["cnae_label"] == businesses.cnae_to_category(5620104)


@pytest.mark.parametrize("url", URLS)
def test_500_does_not_leak_db_text(url, monkeypatch):
    monkeypatch.setattr(businesses, "db_engine", CaptureEngine(fail=True))
    res = client.get(url)
    assert res.status_code == 500
    assert "cnae_label" not in res.text and "secreta" not in res.text


@pytest.mark.skipif(not PG, reason="TEST_PG_URL no definido (Postgres desechable)")
def test_queries_run_on_real_schema(monkeypatch):
    url = make_url(PG)
    if not (url.database or "").startswith("test") or url.host not in (None, "localhost", "127.0.0.1"):
        pytest.exit("TEST_PG_URL debe ser local y apuntar a una base cuyo nombre empiece por 'test'", returncode=2)
    engine = create_engine(PG)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS business_status, estabelecimentos CASCADE"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        # solo la tabla real de estabelecimentos: el resto del esquema base no hace falta aquí
        c.exec_driver_sql(BASE_DDL[BASE_DDL.index("CREATE TABLE IF NOT EXISTS estabelecimentos"):].split(");")[0] + ");")
        c.execute(text("CREATE TABLE business_status (cnpj VARCHAR(20) PRIMARY KEY, status VARCHAR(10) NOT NULL)"))
        c.execute(text("""INSERT INTO estabelecimentos (cnpj_completo, nome_fantasia, situacao_cadastral, cnae_fiscal,
                              cnae_fiscal_descricao, municipio, geom)
                          VALUES ('00000000000191', 'Pizzaria', 2, 5620104, 'Pizzaria e restaurante', 'Maringá',
                                  ST_SetSRID(ST_MakePoint(-51.93, -23.42), 4326))"""))
        c.execute(text("INSERT INTO business_status (cnpj, status) VALUES ('00000000000191', 'client')"))
    monkeypatch.setattr(businesses, "db_engine", engine)
    try:
        for u in URLS:
            res = client.get(u.replace("Maringa", "Maring") + ("&category=pizza" if "city" in u else ""))
            assert res.status_code == 200, (u, res.text)
            assert [r["cnpj"] for r in res.json()] == ["00000000000191"], u
    finally:
        with engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS business_status, estabelecimentos CASCADE"))
        engine.dispose()
