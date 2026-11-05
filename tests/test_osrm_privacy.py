"""OSRM solo si OSRM_URL esta definido y es un host privado: las coordenadas de clientes no salen a servidores publicos."""

import pytest

from app.routes import routes as R
from app.schemas.route import RouteCreateRequest, RouteStopCreateRequest
from app.services.geo import osrm_base_url


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "http://router.project-osrm.org", "https://osrm.example.com:5000", "http://8.8.8.8:5000", "ftp://osrm", "no es url"],
)
def test_public_or_invalid_osrm_url_is_ignored(monkeypatch, value):
    monkeypatch.delenv("OSRM_URL", raising=False)
    if value is not None:
        monkeypatch.setenv("OSRM_URL", value)
    assert osrm_base_url() is None


@pytest.mark.parametrize(
    "value",
    ["http://osrm:5000", "http://localhost:5000", "http://127.0.0.1:5000", "http://10.0.0.5:5000", "http://192.168.1.2", "http://osrm.internal:5000/"],
)
def test_private_osrm_url_is_used(monkeypatch, value):
    monkeypatch.setenv("OSRM_URL", value)
    assert osrm_base_url() == value.rstrip("/")


@pytest.mark.parametrize("value", [None, "https://router.project-osrm.org"])
def test_route_matrices_make_no_request_without_private_osrm(monkeypatch, value):
    monkeypatch.delenv("OSRM_URL", raising=False)
    if value:
        monkeypatch.setenv("OSRM_URL", value)

    def boom(*a, **k):
        raise AssertionError("no debe haber ninguna peticion de red")

    monkeypatch.setattr(R.requests, "get", boom)
    R.ROUTE_STORE.clear()
    route = R.create_route(RouteCreateRequest(name="t", entry_point_id=1, exit_point_id=5))
    R.add_stop(route.id, RouteStopCreateRequest(point_id=2))
    *_, source = R._route_matrices(R._read_route(route.id))
    assert source == "haversine"
