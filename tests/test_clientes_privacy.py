"""Las listas reales de clientes no deben entrar en git; solo el fixture público."""

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = "tests/fixtures/clientes_ejemplo.csv"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def test_git_tracks_no_clientes_csv_except_the_fixture():
    out = _git("ls-files", "--", "clientes*.csv", "**/clientes*.csv")
    assert out.returncode == 0, "git no disponible"
    assert [p for p in out.stdout.split() if p != FIXTURE] == []


def test_gitignore_blocks_real_files_but_not_the_fixture():
    assert _git("check-ignore", "-q", "clientes_maringa.csv").returncode == 0
    assert _git("check-ignore", "-q", ".data/clientes/clientes_maringa.csv").returncode == 0
    assert _git("check-ignore", "-q", FIXTURE).returncode == 1


def test_fixture_is_valid_for_the_seed_script():
    spec = importlib.util.spec_from_file_location("seed_clientes", ROOT / "scripts" / "seed_clientes.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    rows, errors = seed.parse_rows(ROOT / FIXTURE)
    assert errors == [] and len(rows) == 4
    assert {r["geocode_status"] for r in rows} == {"ok", "pendiente"}
