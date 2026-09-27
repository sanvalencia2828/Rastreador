"""Parse pasted Google Maps links into planner stops.

Short links (maps.app.goo.gl) are stored as maps_url and are not fetched, so the
server never follows a user-supplied redirect.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

MAPS_HOSTS = {
    "google.com",
    "www.google.com",
    "maps.google.com",
    "www.google.com.br",
    "google.com.br",
    "maps.app.goo.gl",
    "goo.gl",
}

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
AT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
D3_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
COORD_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$")
PLACE_RE = re.compile(r"/maps/place/([^/@?#]+)")


def today_in_app_tz() -> date:
    tz_name = os.getenv("APP_TIMEZONE", "America/Sao_Paulo")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Sao_Paulo")
    return datetime.now(tz).date()


def _is_maps_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in MAPS_HOSTS:
        return True
    return host.endswith(".google.com") or host.endswith(".google.com.br") or host == "goo.gl"


def _coords_from_text(value: str) -> Optional[tuple[float, float]]:
    cleaned = unquote(value).strip()
    match = COORD_RE.match(cleaned)
    if not match:
        return None
    lat = float(match.group(1))
    lng = float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _address_from_url(url: str) -> Optional[str]:
    match = PLACE_RE.search(urlparse(url).path)
    if not match:
        return None
    text = unquote(match.group(1)).replace("+", " ").strip()
    return text or None


def _points_from_url(url: str) -> list[tuple[Optional[float], Optional[float], Optional[str]]]:
    parsed = urlparse(url)
    points: list[tuple[Optional[float], Optional[float], Optional[str]]] = []

    for match in D3_RE.finditer(url):
        points.append((float(match.group(1)), float(match.group(2)), None))
    if points:
        return points

    at = AT_RE.search(url)
    if at:
        points.append((float(at.group(1)), float(at.group(2)), _address_from_url(url)))
        return points

    query = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "destination"):
        for raw in query.get(key, []):
            coords = _coords_from_text(raw)
            if coords:
                points.append((coords[0], coords[1], None))
            else:
                address = unquote(raw).replace("+", " ").strip()
                if address:
                    points.append((None, None, address))
        if points:
            return points

    path = unquote(parsed.path)
    if "/maps/dir/" in path or path.startswith("/dir/"):
        tail = path.split("/dir/", 1)[-1]
        for segment in tail.split("/"):
            segment = segment.strip()
            if not segment or segment.startswith("@") or segment in {"data", "am"}:
                continue
            coords = _coords_from_text(segment)
            if coords:
                points.append((coords[0], coords[1], None))
                continue
            if re.search(r"[A-Za-zÀ-ÿ]", segment) and not segment.startswith("@"):
                points.append((None, None, segment.replace("+", " ")))
        if points:
            return points

    address = _address_from_url(url)
    if address:
        return [(None, None, address)]
    return [(None, None, None)]


def parse_maps_text(text: str, source: str = "google_maps") -> list[dict]:
    """Return stop drafts. Coordinates are optional; visit_date is filled by the API."""
    blob = text or ""
    urls = [match.rstrip(").,;") for match in URL_RE.findall(blob)]
    stops: list[dict] = []
    seen: set[str] = set()
    for url in urls:
        if not _is_maps_url(url) or url in seen:
            continue
        seen.add(url)
        for lat, lng, address in _points_from_url(url):
            stops.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "address": address or url,
                    "maps_url": url,
                    "source": source,
                    "stop_ref": None,
                    "order_id": None,
                    "meta": {},
                }
            )
    return stops
