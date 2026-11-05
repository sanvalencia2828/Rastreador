"""Los errores de base de datos no deben filtrar valores enlazados ni mensajes del driver."""

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from app.db import bootstrap
from app.services import business_loader

ROOT = Path(__file__).resolve().parent.parent
SECRET = "ZZ-SECRETO host=db.interno user=admin"


def test_bootstrap_prints_only_the_exception_class(monkeypatch, capsys):
    class Boom:
        @contextmanager
        def begin(self):
            raise RuntimeError(SECRET)
            yield

        connect = begin

    monkeypatch.setattr(bootstrap, "db_engine", Boom())
    bootstrap.ensure_schema()
    out = capsys.readouterr().out
    assert "RuntimeError" in out and "ZZ-SECRETO" not in out and "db.interno" not in out


def test_global_engine_hides_parameters():
    code = "import sys; sys.path.insert(0, '.'); from app.core.database import db_engine; print(db_engine.hide_parameters)"
    env = {**os.environ, "DATABASE_URL": "postgresql://u:p@localhost/db", "APP_ENV": "development"}
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.stdout.strip().splitlines()[-1] == "True", out.stderr


def test_business_loader_engine_hides_parameters(monkeypatch):
    seen = []

    def fake_create_engine(url, **kwargs):
        seen.append(kwargs)
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(business_loader, "create_engine", fake_create_engine)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    business_loader.load_businesses()
    assert seen and all(kw.get("hide_parameters") is True for kw in seen)
