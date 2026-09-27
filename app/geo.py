"""Small geospatial helpers. No live GPS and no tracking_points."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    radius = 6371000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return int(2 * radius * asin(sqrt(a)))


def fill_leg_distance(stops: list[dict]) -> None:
    """Straight-line leg distance when both stops have coordinates. Not a GPS trace."""
    previous = None
    for stop in stops:
        lat = stop.get("lat")
        lng = stop.get("lng")
        if previous and lat is not None and lng is not None:
            prev_lat = previous.get("lat")
            prev_lng = previous.get("lng")
            if prev_lat is not None and prev_lng is not None and stop.get("distance_m") is None:
                stop["distance_m"] = haversine_m(float(prev_lat), float(prev_lng), float(lat), float(lng))
                meta = dict(stop.get("meta") or {})
                meta.setdefault("distance_source", "haversine")
                stop["meta"] = meta
        if lat is not None and lng is not None:
            previous = stop
