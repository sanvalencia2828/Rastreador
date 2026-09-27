"""Nominatim geocode, previously a Next.js route. Same-origin /api/geocode."""

from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["geocode"])
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Rastreador/1.0 (contacto@ejemplo.com)"
_last_call = 0.0


class GeocodeIn(BaseModel):
    address: str


@router.post("/api/geocode")
def geocode(body: GeocodeIn):
    raw = (body.address or "").strip()
    if len(raw) < 5:
        raise HTTPException(status_code=400, detail="La dirección debe tener al menos 5 caracteres.")
    try:
        results = _search(raw)
    except requests.Timeout as exc:
        raise HTTPException(status_code=504, detail="El servicio de mapas tardó demasiado. Intentá de nuevo.") from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="No se pudo consultar el geocodificador.") from exc
    if not results:
        raise HTTPException(status_code=404, detail="No se encontró la dirección. Verificá el nombre o agregá más detalles.")
    best = results[0]
    address = best.get("address") or {}
    cep = address.get("postcode") or address.get("postal_code")
    return {
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "display_name": best.get("display_name"),
        "cep": cep,
    }


def _search(query: str) -> list:
    global _last_call
    wait = 1.1 - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()
    params = urlencode(
        {
            "q": query,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "br",
        }
    )
    response = requests.get(
        f"{NOMINATIM}?{params}",
        headers={"User-Agent": USER_AGENT},
        timeout=8,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []
