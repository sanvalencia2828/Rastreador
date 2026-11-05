"""Rutas protegidas: 401 sin token y sin exponer datos de otro usuario (sin base de datos real)."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_jwt_token
from app.main import app
from app.routes import businesses, planned_routes, visits

USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ROUTE = "11111111-1111-1111-1111-111111111111"

client = TestClient(app)

ROUTE_BODY = {"name": "r", "city_id": 1, "stops": [{"address": "a", "lat": -23.3, "lon": -51.1}]}

# (método, ruta, cuerpo) de cada endpoint que escribe o lee datos de un usuario
PROTECTED = [
    ("GET", "/api/routes", None),
    ("POST", "/api/routes", {"name": "r", "business_ids": [1], "start_lat": -23.3, "start_lng": -51.1}),
    ("GET", f"/api/routes/{ROUTE}", None),
    ("PATCH", f"/api/routes/{ROUTE}/status", {"status": "active"}),
    ("POST", f"/api/routes/{ROUTE}/complete", {"completed_date": "2020-01-01", "stops": []}),
    ("PUT", f"/api/routes/{ROUTE}", ROUTE_BODY),
    ("DELETE", f"/api/routes/{ROUTE}", None),
    ("GET", "/api/cities/1/routes", None),
    ("POST", "/api/cities/1/routes", ROUTE_BODY),
    ("POST", "/api/cities", {"name": "Londrina", "state": "PR", "lat": -23.3, "lon": -51.1}),
    ("PATCH", "/api/businesses/123/status", {"status": "visited"}),
    ("GET", "/api/daily-routes", None),
    ("GET", "/api/visits", None),
    ("GET", "/api/clientes", None),
    ("GET", "/api/street-coverage", None),
    ("GET", "/api/clientes/streets-nearby", None),
    ("POST", "/api/routes/generate", {}),
    ("POST", "/api/routes/optimize", {}),
    ("GET", "/api/v1/routes", None),
    ("POST", "/api/v1/routes", {}),
    ("GET", "/api/v1/routes/abc", None),
    ("POST", "/api/sync/visits", []),
]


def bearer(user_id):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': user_id})}"}


@pytest.fixture(autouse=True)
def production_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_route_requires_token(method, path, body):
    assert client.request(method, path, json=body).status_code == 401
    assert client.request(method, path, json=body, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_dev_fallback_only_with_app_env_development(monkeypatch):
    monkeypatch.setattr(planned_routes, "db_engine", None)  # tras autenticar, responde 500 (sin BD)
    monkeypatch.setenv("APP_ENV", "development")
    assert client.get("/api/routes").status_code == 500
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/api/routes").status_code == 401


class FakeEngine:
    """Registra el SQL y los parámetros de cada consulta; nunca devuelve filas."""

    def __init__(self):
        self.calls = []

    @contextmanager
    def _conn(self):
        engine = self

        class Conn:
            def execute(self, statement, params=None):
                engine.calls.append((str(statement), dict(params or {})))

                class Result:
                    rowcount = 0

                    def fetchone(self):
                        return None

                    def fetchall(self):
                        return []

                    def __iter__(self):
                        return iter([])

                return Result()

            def commit(self):
                pass

        yield Conn()

    connect = begin = _conn


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/routes", None),
        ("GET", f"/api/routes/{ROUTE}", None),
        ("PATCH", f"/api/routes/{ROUTE}/status", {"status": "active"}),
        ("DELETE", f"/api/routes/{ROUTE}", None),
    ],
)
def test_route_queries_only_see_the_callers_own_rows(monkeypatch, method, path, body):
    engine = FakeEngine()
    monkeypatch.setattr(planned_routes, "db_engine", engine)
    client.request(method, path, json=body, headers=bearer(USER_B))
    assert engine.calls, "el endpoint no consultó la base"
    for sql, params in engine.calls:
        if "routes" in sql.lower():
            assert params.get("user_id") == USER_B
            assert "IS NULL" not in sql.upper()


def test_visits_ignore_user_id_query_param(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(visits, "db_engine", engine)
    resp = client.get(f"/api/visits?user_id={USER_A}", headers=bearer(USER_B))
    assert resp.status_code == 200
    assert [params["user_id"] for _, params in engine.calls] == [USER_B]


@pytest.mark.parametrize(
    "module,path",
    [
        (businesses, "/api/businesses/search?q=abc&limit=100000"),
        (visits, "/api/street-coverage?limit=100000"),
    ],
)
def test_limit_is_capped_at_500(monkeypatch, module, path):
    engine = FakeEngine()
    monkeypatch.setattr(module, "db_engine", engine)
    assert client.get(path, headers=bearer(USER_A)).status_code == 200  # street-coverage requires login
    assert [params["limit"] for _, params in engine.calls] == [500]
