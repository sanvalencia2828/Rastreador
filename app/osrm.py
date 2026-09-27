"""Optional road ETA. Used only when OSRM_URL is set by the operator."""

from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


def _allowed_osrm(base: str) -> bool:
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return True


def fill_osrm_legs(stops: list[dict]) -> None:
    base = os.getenv("OSRM_URL", "").strip().rstrip("/")
    if not base or not _allowed_osrm(base):
        return
    indexed = [
        (index, stop)
        for index, stop in enumerate(stops)
        if stop.get("lat") is not None and stop.get("lng") is not None
    ]
    if len(indexed) < 2:
        return
    coords = ";".join(f"{stop['lng']},{stop['lat']}" for _index, stop in indexed)
    url = f"{base}/route/v1/driving/{coords}?overview=false&steps=false"
    try:
        with urlopen(url, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, OSError):
        return
    legs = (payload.get("routes") or [{}])[0].get("legs") or []
    for leg_index, leg in enumerate(legs):
        if leg_index + 1 >= len(indexed):
            break
        _origin_index, dest = indexed[leg_index + 1]
        if leg.get("distance") is not None:
            dest["distance_m"] = int(leg["distance"])
        if leg.get("duration") is not None:
            dest["eta_s"] = int(leg["duration"])
        meta = dict(dest.get("meta") or {})
        meta["distance_source"] = "osrm"
        dest["meta"] = meta
