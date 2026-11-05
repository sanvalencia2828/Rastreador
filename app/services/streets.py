"""Calles de Maringá: normalización de nombres, índice desde el volcado de la Receita y cruce con OSM.

Solo se trabaja POR CALLE (el volcado no trae coordenadas). Del volcado se leen únicamente tipo, nombre y
número de la calle, bairro, CEP y situación cadastral: ni nombre fantasía, ni teléfonos, ni correo.
"""

import csv
import json
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import requests

from app.services.geo import haversine_m

# Código de municipio en el volcado de la Receita (NO es el IBGE) y código IBGE que usa OSM.
MARINGA_RFB = "7691"
MARINGA_IBGE = "4115200"

# Posiciones en el layout de ESTABELECIMENTOS de la Receita (30 columnas, sin cabecera)
COL_SITUACAO, COL_TIPO, COL_LOGRADOURO, COL_NUMERO, COL_BAIRRO, COL_CEP, COL_MUNICIPIO = 5, 13, 14, 15, 17, 18, 20
SITUACAO_ATIVA = {"2", "02"}

_TIPOS = {
    "R": "RUA", "RUA": "RUA",
    "AV": "AVENIDA", "AVE": "AVENIDA", "AVENIDA": "AVENIDA",
    "TRAV": "TRAVESSA", "TV": "TRAVESSA", "TRAVESSA": "TRAVESSA",
    "AL": "ALAMEDA", "ALAMEDA": "ALAMEDA",
    "PCA": "PRACA", "PC": "PRACA", "PRACA": "PRACA",
    "ROD": "RODOVIA", "RODOVIA": "RODOVIA",
    "EST": "ESTRADA", "ESTRADA": "ESTRADA",
    "BEC": "BECO", "BECO": "BECO",
    "LRG": "LARGO", "LARGO": "LARGO",
    "VIA": "VIA",
}

# Valores por defecto de "calle larga: estimación poco fiable" (SUPUESTOS, configurables)
CALLE_LARGA_M = float(os.getenv("RASTREADOR_CALLE_LARGA_M", "2000"))
CALLE_LARGA_COMERCIOS = int(os.getenv("RASTREADOR_CALLE_LARGA_COMERCIOS", "100"))

_EXCLUDED_HIGHWAYS = "motorway|motorway_link|construction|proposed|raceway|bus_guideway|platform|elevator"
_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _plain(text_: str) -> str:
    """Mayúsculas, sin acentos ni puntuación, espacios colapsados."""
    folded = unicodedata.normalize("NFKD", text_ or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", folded.upper())).strip()


def normalize_street(name: str, tipo: str = "") -> Tuple[Optional[str], str]:
    """(tipo canónico | None, nombre normalizado). Acepta "Av. Brasil" o tipo="AVENIDA", name="BRASIL".

    No expande títulos (DR/DOUTOR, PROF...): unir calles distintas es peor que no cruzarlas.
    """
    tokens = _plain(name).split()
    tipo_plain = _plain(tipo)
    tipo_canon = _TIPOS.get(tipo_plain) or (tipo_plain or None)
    if tokens and tokens[0] in _TIPOS and (tipo_canon is None or _TIPOS[tokens[0]] == tipo_canon):
        tipo_canon, tokens = _TIPOS[tokens[0]], tokens[1:]
    return tipo_canon, " ".join(tokens)


def street_key(tipo: Optional[str], nome: str) -> str:
    return f"{tipo or ''}|{nome}"


def build_dump_index(estabele_path: str, municipio_rfb: str = MARINGA_RFB) -> Dict[str, Dict[str, Any]]:
    """Agrega el volcado por calle. Solo contadores: no se guarda ningún dato de negocios."""
    streets: Dict[str, Dict[str, Any]] = {}
    with open(estabele_path, encoding="latin-1", newline="") as fh:
        for row in csv.reader(fh, delimiter=";", quotechar='"'):
            if len(row) <= COL_MUNICIPIO or row[COL_MUNICIPIO] != municipio_rfb:
                continue
            tipo, nome = normalize_street(row[COL_LOGRADOURO], row[COL_TIPO])
            if not nome:
                continue
            s = streets.setdefault(
                street_key(tipo, nome),
                {"tipo": tipo, "nome": nome, "n_total": 0, "n_ativos": 0, "bairros": Counter(), "ceps": set(),
                 "numeros": [], "sem_numero": 0},
            )
            s["n_total"] += 1
            if row[COL_SITUACAO] not in SITUACAO_ATIVA:
                continue
            s["n_ativos"] += 1
            bairro = _plain(row[COL_BAIRRO])
            if bairro:
                s["bairros"][bairro] += 1
            cep = re.sub(r"\D", "", row[COL_CEP])
            if len(cep) == 8:
                s["ceps"].add(cep)
            numero = row[COL_NUMERO].strip()
            if re.fullmatch(r"\d{1,6}", numero) and int(numero) > 0:
                s["numeros"].append(int(numero))
            else:
                s["sem_numero"] += 1
    return streets


def overpass_query(ibge: str = MARINGA_IBGE) -> str:
    """Vías con nombre DENTRO del área del límite administrativo con ese código IBGE (no por nombre)."""
    return (
        "[out:json][timeout:240];\n"
        f'area["boundary"="administrative"]["admin_level"="8"]["IBGE:GEOCODIGO"="{ibge}"]->.a;\n'
        f'way(area.a)["highway"]["name"]["highway"!~"^({_EXCLUDED_HIGHWAYS})$"];\n'
        "out geom tags;"
    )


def fetch_osm_streets(
    cache_dir: str, ibge: str = MARINGA_IBGE, refresh: bool = False, attempts: int = 4, wait_s: float = 30
) -> Dict[str, Any]:
    """Descarga (o lee de caché) las vías OSM del municipio. La petición solo lleva el código IBGE."""
    if ibge != MARINGA_IBGE:
        raise ValueError(f"solo se cargan calles de Maringá (IBGE {MARINGA_IBGE}), no {ibge!r}")
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    cached = sorted(folder.glob(f"{ibge}_*.json"))
    if cached and not refresh:
        return json.loads(cached[-1].read_text(encoding="utf-8"))
    data = None
    for attempt in range(1, attempts + 1):  # Overpass answers 429/502/504 when busy
        try:
            response = requests.post(
                _OVERPASS_URL,
                data={"data": overpass_query(ibge)},
                headers={"User-Agent": "rastreador-streets/0.1", "Accept": "application/json"},
                timeout=300,
            )
            if response.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {response.status_code}")
            response.raise_for_status()
            data = response.json()
            break
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if attempt == attempts:
                raise
            time.sleep(wait_s * attempt)
    (folder / f"{ibge}_{date.today().isoformat()}.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def _way_length_m(geometry: Iterable[Dict[str, float]]) -> float:
    pts = [(p["lat"], p["lon"]) for p in geometry]
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))


def index_osm_ways(osm: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Une los tramos OSM de una misma calle por clave normalizada: longitud total y caja envolvente."""
    out: Dict[str, Dict[str, Any]] = {}
    for el in osm.get("elements", []):
        geometry = el.get("geometry") or []
        name = (el.get("tags") or {}).get("name")
        if el.get("type") != "way" or not name or len(geometry) < 2:
            continue
        tipo, nome = normalize_street(name)
        if not nome:
            continue
        entry = out.setdefault(street_key(tipo, nome), {"length_m": 0.0, "n_ways": 0, "lat": [], "lon": []})
        entry["length_m"] += _way_length_m(geometry)
        entry["n_ways"] += 1
        entry["lat"] += [p["lat"] for p in geometry]
        entry["lon"] += [p["lon"] for p in geometry]
    for entry in out.values():
        lats, lons = entry.pop("lat"), entry.pop("lon")
        # diagonal of the bounding box: a huge spread under one name hints at homonymous streets
        entry["spread_m"] = haversine_m(min(lats), min(lons), max(lats), max(lons))
    return out


def match_streets(
    dump: Dict[str, Dict[str, Any]], osm_ways: Dict[str, Dict[str, Any]],
    larga_m: float = CALLE_LARGA_M, larga_comercios: int = CALLE_LARGA_COMERCIOS,
) -> Dict[str, Any]:
    """Cruza por clave exacta (tipo, nombre). Lo que no cruza queda sin geometría: no se interpola."""
    streets, unmatched = [], []
    for key, s in dump.items():
        if s["n_ativos"] == 0:
            continue
        way = osm_ways.get(key)
        numeros = s["numeros"]
        row = {
            "tipo": s["tipo"], "nome": s["nome"], "n_comercios_ativos": s["n_ativos"],
            "numero_min": min(numeros) if numeros else None, "numero_max": max(numeros) if numeros else None,
            "sem_numero": s["sem_numero"], "bairros": sorted(s["bairros"]), "ceps": sorted(s["ceps"]),
            "osm": way is not None,
        }
        if way is None:
            row.update(length_m=None, calle_larga=s["n_ativos"] > larga_comercios)
            unmatched.append(row)
        else:
            row.update(length_m=round(way["length_m"]), n_ways=way["n_ways"], spread_m=round(way["spread_m"]),
                       calle_larga=way["length_m"] > larga_m or s["n_ativos"] > larga_comercios)
        streets.append(row)
    matched = [r for r in streets if r["osm"]]
    com_ativos = sum(r["n_comercios_ativos"] for r in streets)
    com_cruzados = sum(r["n_comercios_ativos"] for r in matched)
    return {
        "municipio_ibge": MARINGA_IBGE,
        "resumen": {
            "calles_con_comercios_activos": len(streets),
            "cruzadas": len(matched),
            "sin_cruzar": len(unmatched),
            "pct_calles_cruzadas": round(100 * len(matched) / len(streets), 1) if streets else 0.0,
            "comercios_activos": com_ativos,
            "comercios_en_calles_cruzadas": com_cruzados,
            "pct_comercios_en_calles_cruzadas": round(100 * com_cruzados / com_ativos, 1) if com_ativos else 0.0,
            "calles_largas": sum(r["calle_larga"] for r in streets),
            "umbral_calle_larga": {"length_m": larga_m, "comercios": larga_comercios, "origen": "supuesto"},
        },
        "calles": streets,
        "sin_cruzar": sorted(unmatched, key=lambda r: -r["n_comercios_ativos"]),
    }
