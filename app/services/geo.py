"""Geographic constants, CNAE mappings and spatial helpers."""

import hashlib
import ipaddress
import os
from math import radians, sin, cos, asin, sqrt
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from app.core.security import is_dev_env


# ==============================================================================
# GEOGRAPHIC CONSTANTS - LONDRINA HOTSPOTS
# ==============================================================================
# 5 main commercial hubs in Londrina with coordinates [lng, lat]
HUBS = {
    1: {
        "name": "Centro (Calçadão)",
        "coords": [-51.1610, -23.3110],
        "desc": "Comercio minorista y gastronomía tradicional",
    },
    2: {
        "name": "Gleba Palhano (Av. Ayrton Senna)",
        "coords": [-51.1890, -23.3310],
        "desc": "Boutiques premium, cafeterías y restaurantes modernos",
    },
    3: {
        "name": "Jardim Guanabara (Av. Higienópolis)",
        "coords": [-51.1670, -23.3220],
        "desc": "Polo de gastronomía y servicios ejecutivos",
    },
    4: {
        "name": "Zona Norte (Av. Saul Elkind)",
        "coords": [-51.1480, -23.2720],
        "desc": "Gran concentración de tiendas de retail masivo",
    },
    5: {
        "name": "Zona Leste (Av. Bandeirantes)",
        "coords": [-51.1550, -23.3180],
        "desc": "Clúster médico y comercial gastronómico de paso",
    },
}


# CNAE code prefixes → human-readable categories
CNAE_CATEGORY_MAP: Dict[str, str] = {
    "47": "Comercio varejista",
    "56": "Alimentación",
    "62": "Tecnología",
    "86": "Saúde",
    "95": "Serviços",
}


def cnae_to_category(cnae) -> str:
    """Maps a CNAE code (int or str) to a human-readable category.
    Unmapped prefixes fall back to 'Outros'."""
    if cnae is None:
        return "Outros"
    prefix = str(cnae)[:2]
    return CNAE_CATEGORY_MAP.get(prefix, "Outros")


def format_cnpj(biz: Dict[str, Any]) -> str:
    """Format the CNPJ components from a business dictionary as a padded string."""
    try:
        basico = int(biz.get("cnpj_basico") or 0)
        cnpj_basico = f"{basico:08d}"
    except (ValueError, TypeError):
        cnpj_basico = str(biz.get("cnpj_basico", "00000000")).zfill(8)

    try:
        ordem = int(biz.get("cnpj_ordem") or 0)
        cnpj_ordem = f"{ordem:04d}"
    except (ValueError, TypeError):
        cnpj_ordem = str(biz.get("cnpj_ordem", "0000")).zfill(4)

    try:
        dv = int(biz.get("cnpj_dv") or 0)
        cnpj_dv = f"{dv:02d}"
    except (ValueError, TypeError):
        cnpj_dv = str(biz.get("cnpj_dv", "00")).zfill(2)

    return cnpj_basico + cnpj_ordem + cnpj_dv


# ==============================================================================
# SPATIAL ALGORITHMS
# ==============================================================================
def synthetic_coords_allowed() -> bool:
    """Invented (hash-based) coordinates only with ALLOW_SYNTHETIC_COORDS=1, never outside development."""
    return os.getenv("ALLOW_SYNTHETIC_COORDS") == "1" and is_dev_env()


def assign_geographic_coords(
    cnpj: str, business_type: str, municipio: Optional[str] = None
) -> List[float]:
    """
    Deterministically maps a CNPJ to geographical coordinates.
    If the business is in Londrina (or default), it maps it to one of the 5 hubs.
    If it is in a nearby city, it maps it around the city's centroid.
    """
    # Create a md5 hash of the CNPJ to have deterministic geographic placement
    h = hashlib.md5(str(cnpj).encode("utf-8")).hexdigest()
    hash_val = int(h, 16)

    city_key = municipio.strip().lower() if municipio else ""

    # Determine centroid based on prefix to prevent encoding conflicts (e.g. UTF-8 vs Latin1)
    center_lng, center_lat = None, None
    if city_key.startswith("cambir"):
        center_lng, center_lat = [-51.5778, -23.5828]  # Cambira
    elif city_key.startswith("camb"):
        center_lng, center_lat = [-51.2782, -23.2758]  # Cambé
    elif city_key.startswith("ibipor"):
        center_lng, center_lat = [-51.0478, -23.2694]  # Ibiporã
    elif city_key.startswith("roland"):
        center_lng, center_lat = [-51.3897, -23.3105]  # Rolândia
    elif city_key.startswith("arapong"):
        center_lng, center_lat = [-51.4244, -23.4194]  # Arapongas
    elif city_key.startswith("apucar") or "apucar" in city_key:
        center_lng, center_lat = [-51.4614, -23.5521]  # Apucarana
    elif "janda" in city_key or "jata" in city_key:
        center_lng, center_lat = [-51.6447, -23.6064]  # Jandaia do Sul
    elif city_key.startswith("maring"):
        center_lng, center_lat = [-51.9330, -23.4205]  # Maringá

    # If the business is in one of the other target cities, place it around its centroid
    if center_lng is not None and center_lat is not None:
        # Deterministic displacement within 2km radius
        lng_factor = ((hash_val % 1000) - 500) / 500.0
        lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0

        lng_offset = (lng_factor**3) * 0.015
        lat_offset = (lat_factor**3) * 0.015
        return [center_lng + lng_offset, center_lat + lat_offset]

    # Default: Londrina Hubs
    # Determine Hub index (1-5) based on hash and business type bias
    if business_type == "gastronomy":
        hub_idx = [2, 3, 5, 1, 4][hash_val % 5]
    elif business_type == "tech":
        hub_idx = [3, 2, 1, 5, 4][hash_val % 5]
    else:
        hub_idx = [1, 4, 2, 3, 5][hash_val % 5]

    hub = HUBS[hub_idx]
    center_lng, center_lat = hub["coords"]

    # Deterministic displacement (using different portions of the md5 hash)
    # Lng noise: maps hash bits to range [-0.006, +0.006] degrees (approx 600m)
    lng_factor = ((hash_val % 1000) - 500) / 500.0  # [-1.0, 1.0]
    lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0  # [-1.0, 1.0]

    # Add Gaussian weight (dense at center, scattered at edges)
    lng_offset = (lng_factor**3) * 0.0075
    lat_offset = (lat_factor**3) * 0.0075

    # Ensure coordinates are floats before addition
    center_lng = float(center_lng)
    center_lat = float(center_lat)

    return [center_lng + lng_offset, center_lat + lat_offset]


# ==============================================================================
# BR-369 INTELLIGENT CORRIDOR
# ==============================================================================

# BR-369 corridor: ordered list of cities from Londrina → Jandaia do Sul
BR369_CITIES = [
    {"name": "Londrina",      "lat": -23.3110, "lng": -51.1610},
    {"name": "Cambé",         "lat": -23.2758, "lng": -51.2782},
    {"name": "Rolândia",      "lat": -23.3105, "lng": -51.3897},
    {"name": "Arapongas",     "lat": -23.4194, "lng": -51.4244},
    {"name": "Apucarana",     "lat": -23.5521, "lng": -51.4614},
    {"name": "Cambira",       "lat": -23.5828, "lng": -51.5778},
    {"name": "Jandaia do Sul","lat": -23.6064, "lng": -51.6447},
]


# ==============================================================================
# TECH BUSINESSES ENDPOINT
# ==============================================================================

# CNAE prefix → tech subcategory mapping
TECH_CNAE_SUBCATEGORY: Dict[str, Dict[str, str]] = {
    "62": {"label": "Software & TI", "icon": "💻"},
    "63": {"label": "Data & Servicios Web", "icon": "🌐"},
    "26": {"label": "Electrónica", "icon": "🖥️"},
    "27": {"label": "Electrodomésticos", "icon": "⚡"},
    "61": {"label": "Telecomunicaciones", "icon": "📡"},
    "95": {"label": "Reparación TI", "icon": "🔧"},
    "46": {"label": "Comercio Mayorista TI", "icon": "📦"},
    "47": {"label": "Retail de Tecnología", "icon": "🏪"},
    "70": {"label": "Consultoría TI", "icon": "🤝"},
    "71": {"label": "Ingeniería & P&D", "icon": "🔬"},
    "72": {"label": "Investigación", "icon": "🔭"},
    "85": {"label": "Educación TI", "icon": "🎓"},
}


# ==============================================================================
# NEARBY BUSINESSES (PostGIS spatial search)
# ==============================================================================


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r"""Great-circle distance in meters between two coordinate pairs."""
    r = 6371000
    la1, lo1, la2, lo2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return int(2 * r * asin(sqrt(a)))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers (float, without rounding)."""
    r_km = 6371.0088
    la1, lo1, la2, lo2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return 2 * r_km * asin(min(1.0, sqrt(a)))


def fix_encoding(text):
    r"""Repair double-encoded UTF-8 mojibake (e.g. 'InformaÃ§Ã£o' -> 'Informação')."""
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".localhost")


def osrm_base_url() -> Optional[str]:
    """OSRM_URL only when set explicitly AND pointing at a private/self-hosted server.

    Route requests carry customer coordinates, so a public OSRM server must never get them:
    unset, empty, malformed or public hosts all return None (callers fall back to Haversine).
    shortcut: no DNS resolution, a public name hidden behind a one-label alias passes, when it matters resolve and check the IP.
    """
    raw = (os.getenv("OSRM_URL") or "").strip().rstrip("/")
    parsed = urlparse(raw)
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host:
        return None
    try:
        ip = ipaddress.ip_address(host)
        private = ip.is_private or ip.is_loopback
    except ValueError:
        private = "." not in host or host.endswith(_PRIVATE_HOST_SUFFIXES)
    return raw if private else None
