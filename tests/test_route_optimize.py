"""Endpoint /routes/{id}/optimize sin OSRM (cae al respaldo Haversine)."""

import pytest

from app.routes import routes as R
from app.schemas.route import RouteCreateRequest, RouteOptimizeRequest, RouteStopCreateRequest, RouteStopPatchRequest
from app.services.geo import haversine_km


@pytest.fixture(autouse=True)
def offline_osrm(monkeypatch):
    monkeypatch.setenv("OSRM_URL", "http://127.0.0.1:9")  # puerto cerrado: fuerza el respaldo
    R.ROUTE_STORE.clear()


def _route_with_stops(point_ids):
    route = R.create_route(RouteCreateRequest(name="t", entry_point_id=1, exit_point_id=5))
    for pid in point_ids:
        R.add_stop(route.id, RouteStopCreateRequest(point_id=pid))
    return route.id


def _point_ids(route_id):
    return [stop.point_id for stop in R.get_route(route_id).stops]


def test_haversine_km_known_distance():
    # Londrina centro → Cambé centro ≈ 12,4 km en línea recta
    assert haversine_km(-23.3103, -51.1628, -23.2758, -51.2782) == pytest.approx(12.4, abs=0.4)


def test_add_stop_goes_before_exit():
    route_id = _route_with_stops([4, 2, 3])
    ids = _point_ids(route_id)
    assert ids[0] == 1 and ids[-1] == 5
    assert ids[1:-1] == [4, 2, 3]


def test_optimize_reorders_and_uses_haversine_totals():
    route_id = _route_with_stops([4, 2, 3])
    result = R.optimize_route(route_id, RouteOptimizeRequest())
    ordered = [stop.point_id for stop in result["stops"]]
    assert ordered == _point_ids(route_id)  # el orden optimizado queda guardado
    assert ordered[0] == 1 and ordered[-1] == 5
    assert ordered == [1, 2, 3, 4, 5]
    assert result["distance_source"] == "haversine"

    points = [R.get_tracking_point(pid) for pid in ordered]
    expected_km = sum(
        haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(points, points[1:])
    )
    assert result["total_km"] == pytest.approx(expected_km, abs=0.02)
    assert result["total_min"] == pytest.approx(expected_km / R.FALLBACK_SPEED_KMH * 60, abs=0.05)
    assert result["stops"][-1].distance_km is None


def test_locked_stop_keeps_seq_after_optimize():
    route_id = _route_with_stops([4, 2, 3])
    locked = next(stop for stop in R.get_route(route_id).stops if stop.point_id == 4)
    R.patch_stop(route_id, locked.id, RouteStopPatchRequest(locked=True))
    R.optimize_route(route_id, RouteOptimizeRequest())
    stops = R.get_route(route_id).stops
    assert [s.point_id for s in stops][locked.seq - 1] == 4


def test_patch_stop_moves_to_requested_seq():
    route_id = _route_with_stops([4, 2, 3])
    stop = next(s for s in R.get_route(route_id).stops if s.point_id == 3)
    R.patch_stop(route_id, stop.id, RouteStopPatchRequest(seq=2))
    assert _point_ids(route_id) == [1, 3, 4, 2, 5]
