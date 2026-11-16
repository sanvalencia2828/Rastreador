"""/api/heatmap: solo coordenadas reales por defecto; las inventadas solo con ALLOW_SYNTHETIC_COORDS=1 en desarrollo."""

import pytest
from fastapi.testclient import TestClient

from app.core.cache import clear_response_cache
from app.main import app
from app.routes import geo

client = TestClient(app)

REAL = {"cnpj_basico": 1, "cnpj_ordem": 1, "cnpj_dv": 1, "latitude": -23.31, "longitude": -51.16, "municipio": "Londrina"}
NO_COORDS = {"cnpj_basico": 2, "cnpj_ordem": 1, "cnpj_dv": 1, "municipio": "Londrina"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    clear_response_cache()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ALLOW_SYNTHETIC_COORDS", raising=False)
    yield
    clear_response_cache()


def heatmap(monkeypatch, businesses):
    monkeypatch.setattr(geo, "load_businesses", lambda: businesses)
    return client.get("/api/heatmap").json()


def test_default_skips_businesses_without_real_coordinates(monkeypatch):
    body = heatmap(monkeypatch, [REAL, NO_COORDS])
    assert len(body["features"]) == 1
    assert body["features"][0]["geometry"]["coordinates"] == [-51.16, -23.31]
    assert body["features"][0]["properties"]["synthetic"] is False
    assert body["omitted_no_coords"] == 1
    assert body["synthetic_allowed"] is False
    assert "note" not in body


def test_all_omitted_explains_why_the_map_is_empty(monkeypatch):
    body = heatmap(monkeypatch, [NO_COORDS, NO_COORDS])
    assert body["features"] == []
    assert body["omitted_no_coords"] == 2
    assert "none has real coordinates" in body["note"]


def test_synthetic_mode_marks_invented_points(monkeypatch):
    monkeypatch.setenv("ALLOW_SYNTHETIC_COORDS", "1")
    body = heatmap(monkeypatch, [REAL, NO_COORDS])
    flags = [f["properties"]["synthetic"] for f in body["features"]]
    assert flags == [False, True]
    assert body["omitted_no_coords"] == 0
    assert body["synthetic_allowed"] is True


def test_synthetic_flag_is_ignored_in_production(monkeypatch):
    monkeypatch.setenv("ALLOW_SYNTHETIC_COORDS", "1")
    monkeypatch.setenv("APP_ENV", "production")
    body = heatmap(monkeypatch, [NO_COORDS])
    assert body["features"] == []
    assert body["synthetic_allowed"] is False


def test_cache_does_not_mix_the_two_modes(monkeypatch):
    heatmap(monkeypatch, [NO_COORDS])  # modo real, queda en caché
    monkeypatch.setenv("ALLOW_SYNTHETIC_COORDS", "1")
    assert len(client.get("/api/heatmap").json()["features"]) == 1


def test_populate_coords_refuses_without_the_opt_in(monkeypatch):
    import populate_coords

    with pytest.raises(SystemExit):
        populate_coords.main()  # sin ALLOW_SYNTHETIC_COORDS
    monkeypatch.setenv("ALLOW_SYNTHETIC_COORDS", "1")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit):
        populate_coords.main()  # la bandera no vale en producción
