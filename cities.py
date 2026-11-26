"""Única definición de las ciudades que cargan/geocodifican enriquecer_lojas.py y load_filtered_cnpj.py.

receita_code: código de municipio de la Receita (columna 21 del ESTABELE; NO es IBGE).
name: grafía tal como se guarda en estabelecimentos.municipio.
"""
import unicodedata
from math import asin, cos, radians, sin, sqrt
from typing import NamedTuple, Optional


class City(NamedTuple):
    name: str
    receita_code: Optional[str]
    lat: float
    lon: float


CITIES = (
    City("Maringá", "7691", -23.4205, -51.9330),
    City("Apucarana", "7425", -23.5521, -51.4614),
    City("Arapongas", "7427", -23.4194, -51.4244),
    # Marialva 7687: "verificado por CEP" según scripts/descargar_maringa.py.
    City("Marialva", "7687", -23.4855, -51.7927),
    # TODO: código Receita de Mandaguari sin confirmar (no está en el repo); hasta tenerlo
    # el loader rechaza sus filas como municipio_desconocido. Confirmar por CEP en un volcado real.
    City("Mandaguari", None, -23.5478, -51.6708),
    # TODO: código Receita de Jandaia do Sul sin confirmar. TODO: verificar el centro (sale de CITY_CENTERS
    # en el historial); no usar lat -23.2003 de la tabla cities de la base, parece mal.
    City("Jandaia do Sul", None, -23.6064, -51.6447),
)
# TODO: confirmar contra la base de producción que municipio se guarda exactamente con
# estas grafías (p. ej. "Maringá" con tilde, no "MARINGA"); el filtro del geocodificador depende de ello.


def _plain(name: Optional[str]) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(text.split()).casefold()


_BY_PLAIN = {_plain(c.name): c for c in CITIES}


def canonical_city(name: Optional[str]) -> Optional[str]:
    """"Maringa", "MARINGÁ" -> "Maringá"; None si no es una ciudad de CITIES."""
    city = _BY_PLAIN.get(_plain(name))
    return city.name if city else None


def city_km(a: str, b: str) -> float:
    """Distancia en línea recta entre los centros de dos ciudades (nombres canónicos)."""
    ca, cb = _BY_PLAIN[_plain(a)], _BY_PLAIN[_plain(b)]
    return _km(ca.lat, ca.lon, cb.lat, cb.lon)


def nearest_city(lat: float, lon: float, max_km: float = 40.0) -> Optional[str]:
    """Ciudad de CITIES con el centro más cercano, o None si ninguna está a menos de max_km."""
    km, city = min((_km(lat, lon, c.lat, c.lon), c.name) for c in CITIES)
    return city if km <= max_km else None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Haversine; local para que cities.py no importe la app (lo usan scripts sueltos)
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))
