"""Tabla clientes: la migración 004 y el bloque de bootstrap son el mismo DDL (sin base de datos real)."""

from contextlib import contextmanager
from pathlib import Path

from app.db import bootstrap

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "004_clientes.sql"


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_migration_and_bootstrap_ddl_are_identical():
    assert _norm(MIGRATION.read_text(encoding="utf-8")) == _norm(bootstrap.CLIENTES_DDL)


def test_ddl_has_the_approved_constraints():
    ddl = _norm(bootstrap.CLIENTES_DDL)
    assert "CHECK (geocode_status <> 'ok' OR lat IS NOT NULL)" in ddl
    assert "geocode_source IN ('usuario'" in ddl
    assert "lat BETWEEN -90 AND 90" in ddl and "lon BETWEEN -180 AND 180" in ddl
    assert "CHECK ((lat IS NULL) = (lon IS NULL))" in ddl
    assert "IN ('usuario', 'nominatim', 'manual')" in ddl
    assert "UNIQUE (user_id, external_id)" in ddl and "REFERENCES users(id)" in ddl


class _Engine:
    def __init__(self):
        self.sql = []

    @contextmanager
    def begin(self):
        engine = self

        class Conn:
            def execute(self, statement, params=None):
                engine.sql.append(str(statement))

        yield Conn()


def test_ensure_clientes_schema_runs_the_ddl_and_tolerates_no_engine(monkeypatch):
    monkeypatch.setattr(bootstrap, "db_engine", None)
    bootstrap._ensure_clientes_schema()  # no engine: no-op
    engine = _Engine()
    monkeypatch.setattr(bootstrap, "db_engine", engine)
    bootstrap._ensure_clientes_schema()
    assert engine.sql == [bootstrap.CLIENTES_DDL]
