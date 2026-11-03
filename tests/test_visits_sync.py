"""/api/sync/visits: validación por ítem y una sola sentencia por lote (sin base de datos real)."""

from contextlib import contextmanager
from decimal import Decimal

import pytest

from app.routes import visits as V
from app.schemas.visit import VisitSyncItem

USER = "00000000-0000-0000-0000-000000000001"
ROUTE = "11111111-1111-1111-1111-111111111111"


def _item(**overrides):
    data = dict(cnpj="222", lat=-23.31234567891, lon=-51.16, logradouro="RUA A", visited_at="2026-10-02T09:00:00Z")
    data.update(overrides)
    return VisitSyncItem(**data)


def test_parse_reports_invalid_items_and_keeps_the_rest():
    items = [
        _item(),
        _item(visited_at="ayer"),
        _item(lat=123.0),
        _item(logradouro="  "),
        _item(route_id="no-uuid"),
        _item(route_id=ROUTE, cnpj=""),
    ]
    columns, errors = V._parse_sync_batch(items)
    assert [e["index"] for e in errors] == [1, 2, 3, 4]
    assert columns["ords"] == [0, 5]
    assert columns["route_ids"] == [None, ROUTE]
    assert columns["cnpjs"] == ["222", None]
    assert columns["lats"][0] == Decimal("-23.31234567891")


def test_sql_dedupes_in_batch_and_against_rounded_numeric():
    sql = str(V.SYNC_VISITS_SQL)
    assert "DISTINCT ON (logradouro, lat, lon, visited_at)" in sql
    assert "ROUND(lat, 7)" in sql and "NOT EXISTS" in sql


class _FakeResult(list):
    def fetchall(self):
        return list(self)


class _FakeConn:
    def __init__(self, existing_routes, inserted_rows):
        self.calls = []
        self.existing_routes = existing_routes
        self.inserted_rows = inserted_rows

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        if "FROM routes" in str(statement):
            return _FakeResult([(r,) for r in self.existing_routes])
        return _FakeResult(self.inserted_rows)


class _FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def begin(self):
        yield self.conn


def test_sync_uses_one_insert_and_recalculates_once_per_cnpj(monkeypatch):
    conn = _FakeConn(existing_routes=[ROUTE], inserted_rows=[("222",), ("222",), (None,)])
    monkeypatch.setattr(V, "db_engine", _FakeEngine(conn))
    monkeypatch.setattr(V, "_business_id_for_cnpj", lambda c, cnpj: {"222": 7}.get(cnpj))
    recalculated = []
    monkeypatch.setattr(V, "recalculate_visit_interval", lambda c, business_id: recalculated.append(business_id))

    items = [
        _item(route_id=ROUTE),
        _item(visited_at="2026-10-03T09:00:00Z"),
        _item(cnpj=None, logradouro="RUA B", route_id="22222222-2222-2222-2222-222222222222"),
        _item(visited_at="mal"),
    ]
    response = V.sync_visits(items, user_id=USER)

    assert len(conn.calls) == 2  # rutas referenciadas + INSERT del lote
    insert_params = conn.calls[1][1]
    assert insert_params["user_id"] == USER
    assert insert_params["route_ids"] == [ROUTE, None, None]  # la ruta inexistente se guarda sin ruta
    assert recalculated == [7]
    assert response["received"] == 4
    assert response["synced"] == 3
    assert response["skipped"] == 1
    assert [e["index"] for e in response["errors"]] == [3]
    assert [w["index"] for w in response["warnings"]] == [2]


def test_sync_with_only_invalid_items_does_not_touch_the_db(monkeypatch):
    conn = _FakeConn(existing_routes=[], inserted_rows=[])
    monkeypatch.setattr(V, "db_engine", _FakeEngine(conn))
    response = V.sync_visits([_item(visited_at="x")], user_id=USER)
    assert conn.calls == []
    assert response["synced"] == 0 and response["skipped"] == 1
