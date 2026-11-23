"""POST /api/routes/generate-week: misma reparticion que scripts/rutas_semana.py y que el endpoint de un dia."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user_id
from app.main import app
from app.routes import planned_routes as pr
from app.services.day_route import DIAS_SEMANA, cluster_days, order_day

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("rutas_semana", ROOT / "scripts" / "rutas_semana.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

# 23 clientes en Maringa (rejilla), 2 fuera, 2 sin ubicar. Datos sinteticos.
RAW = [(f"c{i:02d}", -23.40 - (i % 5) * 0.012, -51.95 + (i // 5) * 0.015, "Maringa") for i in range(23)]
RAW += [("c90", -23.44, -51.87, "Sarandi"), ("c91", -23.30, -51.17, "Londrina")]
RAW += [("c95", None, None, "Maringa"), ("c96", None, None, "Maringa")]
DEPOT = (-23.4118, -51.9390)


def rows_console():
    return [{"external_id": e, "nombre_negocio": f"N{e}", "nombre_cliente": "", "direccion": "d", "bairro": "b",
             "municipio": m, "lat": la, "lon": lo} for e, la, lo, m in RAW]


def rows_db():
    return [SimpleNamespace(id=e, nombre_negocio=f"N{e}", nombre_cliente="", direccion="d", bairro="b", municipio=m,
                            lat=la, lon=lo, geocode_status="ok" if la is not None else "pendiente", visita_diaria=False)
            for e, la, lo, m in RAW]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pr, "db_engine", object())
    monkeypatch.setattr(pr, "_load_clientes", lambda user_id: rows_db())
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def console_week(dias, cap, depot=None):
    inside, outside, pending = rs.split_rows(rows_console())
    days, overflow = rs.cluster_days(inside, dias, cap)
    return [
        [stops[i]["external_id"] for i in order_day([(r["lat"], r["lon"]) for r in stops], depot)] for stops in days
    ], overflow, outside, pending


@pytest.mark.parametrize("depot", [None, DEPOT])
@pytest.mark.parametrize("dias,cap", [(5, 10), (3, 4), (5, 3)])
def test_week_matches_console(client, dias, cap, depot):
    body = {"days": dias, "max_stops": cap}
    if depot:
        body.update(start_lat=depot[0], start_lon=depot[1])
    data = client.post("/api/routes/generate-week", json=body).json()
    days, overflow, outside, pending = console_week(dias, cap, depot)
    assert [[s["cliente_id"] for s in d["stops"]] for d in data["days"]] == days
    assert [c["nombre"] for c in data["sin_asignar"]] == [f"N{r['external_id']}" for r in overflow]
    assert len(data["fuera_de_maringa"]) == len(outside) and len(data["pendientes"]) == len(pending)


def test_one_day_equals_week_day(client):
    week = client.post("/api/routes/generate-week", json={}).json()["days"]
    for n in range(5):
        one = pr._generate_from_clientes("u1", "Maringá", 80, n)
        assert [s.cliente_id for s in one.stops] == [s["cliente_id"] for s in week[n]["stops"]]
        assert one.distance_km == week[n]["distance_km"] and one.maps_links == week[n]["maps_links"]


def test_one_day_response_unchanged(client):
    """Mismas claves y valores que la implementacion anterior (clustering + order_day directos)."""
    one = pr._generate_from_clientes("u1", "Maringá", 80, 1).model_dump()
    assert set(one) == {"city", "total_candidates", "selected", "stops", "distance_km", "distance_kind", "maps_links",
                        "fuera_de_maringa", "pendientes", "day", "day_label", "day_counts", "sin_asignar", "avisos"}
    inside = [r for r in rows_db() if r.lat is not None and r.municipio == "Maringa"]
    pts = [(float(r.lat), float(r.lon)) for r in inside]
    groups, overflow = cluster_days(pts, 5, 10)
    expect = [inside[groups[1][i]].id for i in order_day([pts[i] for i in groups[1]])]
    assert [s["cliente_id"] for s in one["stops"]] == expect
    assert (one["day"], one["day_label"], one["distance_kind"]) == (1, DIAS_SEMANA[1], "linea_recta")
    assert one["day_counts"] == [len(g) for g in groups] and one["sin_asignar"] == len(overflow)
    assert one["total_candidates"] == 23 and len(one["fuera_de_maringa"]) == 2 and len(one["pendientes"]) == 2


def test_nothing_is_lost(client):
    d = client.post("/api/routes/generate-week", json={"days": 3, "max_stops": 4}).json()
    assert d["sin_asignar"]  # el tope fuerza overflow
    assigned = sum(x["selected"] for x in d["days"])
    assert assigned + len(d["fuera_de_maringa"]) + len(d["pendientes"]) + len(d["sin_asignar"]) == d["total_clientes"] == len(RAW)
    assert all(x["distance_kind"] == "linea_recta" for x in d["days"])


def test_requires_auth_and_validates(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    app.dependency_overrides.clear()
    assert client.post("/api/routes/generate-week", json={}).status_code == 401
    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    assert client.post("/api/routes/generate-week", json={"days": 0}).status_code == 422
