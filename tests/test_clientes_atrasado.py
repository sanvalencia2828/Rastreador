"""Columna clientes.atrasado: migración 011 = bootstrap, y el seed acepta la columna opcional "atrasado"."""

import importlib.util
from pathlib import Path

import pytest

from app.db import bootstrap

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("seed_clientes", ROOT / "scripts" / "seed_clientes.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def _csv(tmp_path, header, *lines):
    p = tmp_path / "c.csv"
    p.write_text("\n".join([",".join(header), *lines]) + "\n", encoding="utf-8")
    return p


def test_migration_011_and_bootstrap_ddl_are_identical():
    lines = (ROOT / "migrations" / "011_clientes_atrasado.sql").read_text(encoding="utf-8").splitlines()
    body = " ".join(line for line in lines if not line.startswith("--"))
    assert " ".join(body.split()) == " ".join(bootstrap.CLIENTES_ATRASADO_DDL.split())
    assert "ADD COLUMN IF NOT EXISTS atrasado BOOLEAN NOT NULL DEFAULT FALSE" in body


def test_seed_accepts_13_columns(tmp_path):
    lines = [f"{i},c,N,d,b,Maringa,,,,pendiente_geocodificar,,no,{v}" for i, v in enumerate(["si", "No", "1", "false"])]
    rows, errors = seed.parse_rows(_csv(tmp_path, seed.HEADER_ATRASADO, *lines))
    assert errors == [] and [r["atrasado"] for r in rows] == [True, False, True, False]


@pytest.mark.parametrize("header,line", [
    (seed.HEADER, "1,c,N,d,b,Maringa,,,,pendiente_geocodificar,"),
    (seed.HEADER_DIARIA, "1,c,N,d,b,Maringa,,,,pendiente_geocodificar,,si"),
])
def test_seed_without_atrasado_column_keeps_db_value(tmp_path, header, line):
    rows, errors = seed.parse_rows(_csv(tmp_path, header, line))
    assert errors == [] and rows[0]["atrasado"] is None  # NULL -> el UPSERT conserva lo de la base
    assert "atrasado = COALESCE(:atrasado, clientes.atrasado)" in str(seed.UPSERT)


def test_seed_rejects_bad_atrasado_without_echoing_it(tmp_path):
    rows, errors = seed.parse_rows(_csv(tmp_path, seed.HEADER_ATRASADO, "1,c,N,d,b,Maringa,,,,pendiente_geocodificar,,si,quizas"))
    assert rows == [] and errors == [(2, "atrasado", "invalido")]


def test_seed_counts_atrasados(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")  # dry-run, sin base
    p = _csv(tmp_path, seed.HEADER_ATRASADO, "1,ZZ-SECRETO,N,d,b,Maringa,,,,pendiente_geocodificar,,no,si")
    assert seed.main(["--csv", str(p), "--user", "u"]) == 0
    out = capsys.readouterr().out
    assert "ZZ-SECRETO" not in out and "1 atrasados" in out
