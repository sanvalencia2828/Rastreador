"""Columnas geocode_attempts: la migración 008 y el bloque de bootstrap son el mismo DDL (sin base de datos real)."""

from contextlib import contextmanager
from pathlib import Path

from app.db import bootstrap

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "008_geocode_attempts.sql"


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_migration_and_bootstrap_ddl_are_identical():
    body = MIGRATION.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n", 2)[2]  # sin las 2 líneas de comentario
    assert _norm(body) == _norm(bootstrap.GEOCODE_ATTEMPTS_DDL)


def test_ddl_is_idempotent():
    assert _norm(bootstrap.GEOCODE_ATTEMPTS_DDL).count("ADD COLUMN IF NOT EXISTS") == 2


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


def test_ensure_geocode_attempts_schema_runs_the_ddl_and_tolerates_no_engine(monkeypatch):
    monkeypatch.setattr(bootstrap, "db_engine", None)
    bootstrap._ensure_geocode_attempts_schema()  # no engine: no-op
    engine = _Engine()
    monkeypatch.setattr(bootstrap, "db_engine", engine)
    bootstrap._ensure_geocode_attempts_schema()
    assert engine.sql == [bootstrap.GEOCODE_ATTEMPTS_DDL]
