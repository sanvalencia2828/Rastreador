import pytest
from fastapi import HTTPException

from app.routes.routes import reorder_route, validate_route_status


@pytest.fixture
def sample_route():
    route = {
        "id": "route-1",
        "status": "draft",
        "entry_point_id": 1,
        "exit_point_id": 3,
        "stops": [
            {"id": 10, "point_id": 1, "seq": 1, "locked": True},
            {"id": 11, "point_id": 2, "seq": 2, "locked": False},
            {"id": 12, "point_id": 3, "seq": 3, "locked": True},
        ],
    }
    return route


def test_validate_route_status_done_rejected(sample_route):
    sample_route["status"] = "done"

    with pytest.raises(HTTPException):
        validate_route_status(sample_route)


def test_reorder_route_rejects_entry_moved(sample_route):
    ordered_stop_ids = [11, 10, 12]

    with pytest.raises(HTTPException):
        reorder_route(sample_route, ordered_stop_ids)


def test_reorder_route_accepts_valid_order(sample_route):
    ordered_stop_ids = [10, 11, 12]

    result = reorder_route(sample_route, ordered_stop_ids)

    assert result["status"] == "draft"
    assert result["stops"][0]["seq"] == 1
    assert result["stops"][-1]["seq"] == 3
