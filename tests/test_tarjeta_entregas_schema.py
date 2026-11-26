"""Tabla tarjeta_entregas: la migración 009 y el bloque de bootstrap son el mismo DDL (sin base de datos real)."""

from contextlib import contextmanager
from pathlib import Path

from app.db import bootstrap

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "009_tarjeta_entregas.sql"


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_migration_and_bootstrap_ddl_are_identical():
    lines = MIGRATION.read_text(encoding="utf-8").splitlines()
    body = " ".join(l for l in lines if not l.startswith("--"))
    assert _norm(body) == _norm(bootstrap.TARJETA_ENTREGAS_DDL)


def test_ddl_is_idempotent_and_has_the_requested_constraints():
    ddl = _norm(bootstrap.TARJETA_ENTREGAS_DDL)
    assert "CREATE TABLE IF NOT EXISTS tarjeta_entregas" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_tarjeta_entregas_user_cnpj_fecha ON tarjeta_entregas(user_id, cnpj_completo, fecha)" in ddl
    assert "IN ('tarjeta_entregada', 'cerrado', 'rechazo', 'interesado', 'no_encontrado')" in ddl
    assert "nota VARCHAR(500)" in ddl and "REFERENCES users(id)" in ddl


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


def test_ensure_tarjeta_entregas_schema_runs_the_ddl_and_tolerates_no_engine(monkeypatch):
    monkeypatch.setattr(bootstrap, "db_engine", None)
    bootstrap._ensure_tarjeta_entregas_schema()  # no engine: no-op
    engine = _Engine()
    monkeypatch.setattr(bootstrap, "db_engine", engine)
    bootstrap._ensure_tarjeta_entregas_schema()
    assert engine.sql == [bootstrap.TARJETA_ENTREGAS_DDL]
