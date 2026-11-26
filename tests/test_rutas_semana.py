"""scripts/rutas_semana.py con el CSV de ejemplo (lugares publicos)."""

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("rutas_semana", ROOT / "scripts" / "rutas_semana.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

FIXTURE = ROOT / "tests" / "fixtures" / "clientes_ejemplo.csv"
EXTRA = [  # fuera de Maringa con coords, y uno sin coords
    "90,Cliente de ejemplo 90,Praca da Matriz,Rua X,Centro,Sarandi,87000-000,-23.4440,-51.8740,coords_del_enlace,",
    "91,Cliente de ejemplo 91,Sitio B,Rua Y,Centro,Maringa,87000-000,,,pendiente_geocodificar,",
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTREADOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ROUTE_DEPOT_LAT", raising=False)
    monkeypatch.delenv("ROUTE_DEPOT_LON", raising=False)
    csv = tmp_path / "clientes" / "c.csv"
    csv.parent.mkdir()
    csv.write_text(FIXTURE.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(EXTRA) + "\n", encoding="utf-8")
    return tmp_path, csv


def run(csv, *args):
    return rs.main(["--csv", str(csv), *args])


def test_output_goes_to_ignored_folder_and_sections(env, capsys):
    tmp, csv = env
    assert run(csv, "--dias", "2") == 0
    (md,) = (tmp / "rutas").glob("rutas_semana_*.md")
    text = md.read_text(encoding="utf-8")
    assert "Fuera de Maringa (viaje aparte)" in text and "Praca da Matriz" in text
    assert "Pendientes de ubicar" in text and "Sitio B" in text
    assert "linea recta" in text and "google.com/maps/dir" in text
    shown = capsys.readouterr()
    assert "Catedral" not in shown.out + shown.err and "-23.4" not in shown.out + shown.err
    # la carpeta real de salida (.data/rutas) esta ignorada por git
    assert subprocess.run(["git", "check-ignore", "-q", ".data/rutas/x.md"], cwd=ROOT).returncode == 0


def test_max_paradas_cap(env):
    tmp, csv = env
    assert run(csv, "--dias", "1", "--max-paradas", "2") == 0
    text = next((tmp / "rutas").glob("*.md")).read_text(encoding="utf-8")
    assert "## Dia 1 (2 paradas" in text and "Sin asignar" in text


def test_depot_starts_the_day(env, monkeypatch):
    tmp, csv = env
    monkeypatch.setenv("ROUTE_DEPOT_LAT", "-23.4118")
    monkeypatch.setenv("ROUTE_DEPOT_LON", "-51.9390")
    assert run(csv, "--dias", "1") == 0
    text = next((tmp / "rutas").glob("*.md")).read_text(encoding="utf-8")
    assert "origin=-23.4118,-51.939" in text
    assert re.search(r"1\. Teatro", text)  # el mas cercano al origen va primero


def test_many_stops_split_links():
    pts = [(-23.4 + i / 1000, -51.9) for i in range(15)]
    links = rs.maps_links(pts)
    assert len(links) == 2 and all(u.count("%7C") <= rs.MAX_WAYPOINTS - 1 for u in links)


def test_refuses_tracked_or_outside_csv(env, capsys):
    _, csv = env
    assert run(FIXTURE) == 1  # fuera de la carpeta de datos
    capsys.readouterr()
    # dentro de la carpeta de datos pero rastreado por git
    rs.data_dir = lambda: ROOT / "tests"
    assert run(FIXTURE) == 1
    assert "rastreado" in capsys.readouterr().err
