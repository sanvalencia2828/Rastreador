from __future__ import annotations

from typing import Any

TRACKING_POINTS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "label": "Entry", "lat": -23.3100, "lon": -51.1600},
    2: {"id": 2, "label": "Stop 2", "lat": -23.3180, "lon": -51.1700},
    3: {"id": 3, "label": "Stop 3", "lat": -23.3220, "lon": -51.1800},
    4: {"id": 4, "label": "Stop 4", "lat": -23.3280, "lon": -51.1500},
    5: {"id": 5, "label": "Exit", "lat": -23.3350, "lon": -51.1400},
}


def get_tracking_point(point_id: int) -> dict[str, Any] | None:
    return TRACKING_POINTS.get(point_id)
