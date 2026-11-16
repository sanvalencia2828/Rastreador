"""GET /api/clientes: solo filas del usuario autenticado y límite acotado (sin base de datos real)."""

from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_jwt_token
from app.main import app
from app.routes import clientes

USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
client = TestClient(app)


def _row(owner, n):
    return {"id": f"{n:08d}-0000-0000-0000-000000000000", "external_id": str(n), "nombre_cliente": f"c-{owner[0]}{n}",
            "nombre_negocio": "n", "direccion": "d", "bairro": "b", "municipio": "m", "cep": None,
            "lat": Decimal("-23.4000000"), "lon": None, "geocode_status": "ok", "geocode_source": "usuario", "nota": None}


class FakeEngine:
    """Devuelve las filas del dueño indicado en el parámetro user_id, como haría el WHERE."""

    def __init__(self):
        self.calls = []
        self.data = {USER_A: [_row(USER_A, 1), _row(USER_A, 2)], USER_B: [_row(USER_B, 3)]}

    @contextmanager
    def connect(self):
        engine = self

        class Conn:
            def execute(self, statement, params):
                engine.calls.append((str(statement), dict(params)))

                class Result:
                    def fetchall(_):
                        return [type("R", (), {"_mapping": r})() for r in engine.data.get(params["user_id"], [])][: params["limit"]]

                return Result()

        yield Conn()


def bearer(user_id):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': user_id})}"}


@pytest.fixture(autouse=True)
def production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


def test_requires_token():
    assert client.get("/api/clientes").status_code == 401
    assert client.get("/api/clientes", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_users_only_see_their_own_clientes(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(clientes, "db_engine", engine)
    a = client.get("/api/clientes", headers=bearer(USER_A))
    b = client.get("/api/clientes", headers=bearer(USER_B))
    assert [c["external_id"] for c in a.json()] == ["1", "2"]
    assert [c["external_id"] for c in b.json()] == ["3"]
    assert a.headers["cache-control"] == "no-store"
    assert a.json()[0]["lat"] == -23.4 and a.json()[0]["lon"] is None and "user_id" not in a.json()[0]
    for sql, params in engine.calls:
        assert "WHERE user_id = :user_id" in sql and "IS NULL" not in sql.upper().split("WHERE")[1].split("ORDER")[0]
    assert [p["user_id"] for _, p in engine.calls] == [USER_A, USER_B]


def test_limit_is_bounded_and_forwarded(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(clientes, "db_engine", engine)
    assert client.get("/api/clientes?limit=1", headers=bearer(USER_A)).json()[0]["external_id"] == "1"
    assert engine.calls[-1][1]["limit"] == 1
    assert client.get("/api/clientes", headers=bearer(USER_A)).status_code == 200
    assert engine.calls[-1][1]["limit"] == 100
    for bad in ("0", "501", "x"):
        assert client.get(f"/api/clientes?limit={bad}", headers=bearer(USER_A)).status_code == 422


def test_db_failures_use_fixed_messages(monkeypatch):
    monkeypatch.setattr(clientes, "db_engine", None)
    assert client.get("/api/clientes", headers=bearer(USER_A)).status_code == 500

    class Boom:
        def connect(self):
            raise RuntimeError("SECRETO-NOMBRE param")

    monkeypatch.setattr(clientes, "db_engine", Boom())
    r = client.get("/api/clientes", headers=bearer(USER_A))
    assert r.status_code == 500 and "SECRETO" not in r.text


class InsertEngine:
    def __init__(self):
        self.params = None

    @contextmanager
    def begin(self):
        engine = self

        class Conn:
            def execute(self, statement, params):
                engine.params = dict(params)

                class Result:
                    def fetchone(_):
                        row = {**_row(USER_A, 9), "lat": None, "lon": None, "geocode_status": params["geocode_status"],
                               "geocode_source": params["geocode_source"], "nombre_negocio": params["nombre_negocio"]}
                        return type("R", (), {"_mapping": row})()

                return Result()

        yield Conn()


def test_create_requires_token():
    assert client.post("/api/clientes", json={"nombre_negocio": "x"}).status_code == 401


def test_create_with_gps_is_located_and_owned_by_token_user(monkeypatch):
    engine = InsertEngine()
    monkeypatch.setattr(clientes, "db_engine", engine)
    r = client.post("/api/clientes", json={"nombre_negocio": "  Padaria  ", "lat": -23.42, "lon": -51.93, "user_id": USER_B},
                    headers=bearer(USER_A))
    assert r.status_code == 201 and r.json()["nombre_negocio"] == "Padaria"
    p = engine.params
    assert p["user_id"] == USER_A and p["geocode_status"] == "ok" and p["geocode_source"] == "manual"
    assert p["lat"] == -23.42 and len(p["external_id"]) == 36


def test_create_without_coords_is_pending(monkeypatch):
    engine = InsertEngine()
    monkeypatch.setattr(clientes, "db_engine", engine)
    r = client.post("/api/clientes", json={"nombre_negocio": "Loja", "direccion": "Av. Brasil 1"}, headers=bearer(USER_A))
    assert r.status_code == 201
    assert engine.params["geocode_status"] == "pendiente" and engine.params["geocode_source"] is None


@pytest.mark.parametrize("body", [
    {}, {"nombre_negocio": "   "}, {"nombre_negocio": "x", "lat": -23.4},
    {"nombre_negocio": "x", "lat": 91, "lon": 0}, {"nombre_negocio": "x", "lat": 0, "lon": 181},
])
def test_create_validates(body, monkeypatch):
    monkeypatch.setattr(clientes, "db_engine", InsertEngine())
    assert client.post("/api/clientes", json=body, headers=bearer(USER_A)).status_code == 422
