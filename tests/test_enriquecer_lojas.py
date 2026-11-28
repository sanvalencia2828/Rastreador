"""Lógica del geocodificador sin red ni base: Nominatim y la conexión son simulados."""
import pytest

import enriquecer_lojas as el


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.executed = rows, []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows):
        self.cur, self.commits = FakeCursor(rows), 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def pending(n):
    return [(i, f"{i:014d}", "Rua A", str(i), "Centro", "Maringá", "tech") for i in range(1, n + 1)]


@pytest.fixture(autouse=True)
def no_sleep_no_ddl(monkeypatch):
    monkeypatch.setattr(el.time, "sleep", lambda s: None)
    monkeypatch.setattr(el, "ensure_geom_column", lambda c: None)


def script(monkeypatch, outcomes):
    it = iter(outcomes)

    def fake(addr):
        o = next(it)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(el, "geocode_address", fake)


def updates(conn, needle):
    return [e for e in conn.cur.executed if e[0].startswith("UPDATE") and needle in e[0]]


def test_not_found_counts_attempt_and_writes_no_coords(monkeypatch):
    conn = FakeConn(pending(1))
    script(monkeypatch, [None])
    assert el.geocode_all_pending(conn) == (0, 1, 0)
    assert len(updates(conn, "geocode_attempts")) == 1
    assert not updates(conn, "latitude")


def test_network_error_is_not_not_found_and_uses_no_attempt(monkeypatch):
    conn = FakeConn(pending(2))
    script(monkeypatch, [ConnectionError("boom"), (-23.4, -51.9)])
    assert el.geocode_all_pending(conn) == (1, 0, 1)
    assert not updates(conn, "geocode_attempts")


def test_same_address_is_requested_once(monkeypatch):
    rows = [(i, f"{i:014d}", "Rua A", "1", "Centro", "Maringá", "tech") for i in (1, 2)]
    conn = FakeConn(rows)
    script(monkeypatch, [(-23.4, -51.9)])  # una sola respuesta: una segunda petición haría StopIteration
    assert el.geocode_all_pending(conn) == (2, 0, 0)


def test_five_consecutive_errors_abort(monkeypatch):
    conn = FakeConn(pending(8))
    script(monkeypatch, [ConnectionError("x")] * 8)
    with pytest.raises(el.GeocodingAborted):
        el.geocode_all_pending(conn)
    assert conn.commits >= 1


def test_a_success_resets_the_consecutive_error_counter(monkeypatch):
    conn = FakeConn(pending(9))
    script(monkeypatch, [ConnectionError("x")] * 4 + [(-23.4, -51.9)] + [ConnectionError("x")] * 4)
    assert el.geocode_all_pending(conn) == (1, 0, 8)


def test_query_skips_rows_over_attempt_cap_and_filters_cities(monkeypatch):
    conn = FakeConn([])
    el.geocode_all_pending(conn)
    sql, params = conn.cur.executed[0]
    assert "geocode_attempts" in sql and "municipio = ANY" in sql
    assert params == (list(el.GEOCODE_MUNICIPIOS), el.MAX_GEOCODE_ATTEMPTS)
    assert el.MAX_GEOCODE_ATTEMPTS == 3
