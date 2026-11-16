"""Calles de Maringá: normalización de nombres, índice desde el volcado de la Receita y cruce con OSM.

Solo se trabaja POR CALLE (el volcado no trae coordenadas). Del volcado se leen únicamente tipo, nombre y
número de la calle, bairro, CEP y situación cadastral: ni nombre fantasía, ni teléfonos, ni correo.
"""

import csv
import json
import math
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

# Distritos de Maringá: sus comercios se cuentan aparte y no entran en el plan (decisión del usuario)
DISTRITOS = ("FLORIANO", "IGUATEMI")
# Casco urbano: el trazado OSM de cada calle se limita a este radio (SUPUESTOS, configurables)
CENTRO_MARINGA = (-23.4205, -51.9331)  # Catedral Basílica Menor (lugar público)
RADIO_CASCO_M = float(os.getenv("RASTREADOR_RADIO_CASCO_M", "10000"))
DISPERSION_MAX_M = float(os.getenv("RASTREADOR_DISPERSION_MAX_M", "8000"))

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


def build_dump_index(
    estabele_path: str, municipio_rfb: str = MARINGA_RFB, distritos: Optional[Counter] = None
) -> Dict[str, Dict[str, Any]]:
    """Agrega el volcado por calle. Solo contadores: no se guarda ningún dato de negocios.

    Los comercios activos con bairro de un distrito (Floriano, Iguatemi) van a `n_distrito` y no a `n_ativos`;
    `distritos` (si se pasa) recoge cuántos por bairro, para revisar la clasificación.
    """
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
                {"tipo": tipo, "nome": nome, "n_total": 0, "n_ativos": 0, "n_distrito": 0, "bairros": Counter(),
                 "ceps": set(), "numeros": [], "sem_numero": 0},
            )
            s["n_total"] += 1
            if row[COL_SITUACAO] not in SITUACAO_ATIVA:
                continue
            bairro = _plain(row[COL_BAIRRO])
            if any(d in bairro for d in DISTRITOS):
                s["n_distrito"] += 1
                if distritos is not None:
                    distritos[bairro] += 1
                continue
            s["n_ativos"] += 1
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


class _IncompleteOverpass(Exception):
    """200 OK but unusable: runtime-error remark, empty body or not JSON. Worth retrying, never caching."""


def _usable(data: Any) -> bool:
    return isinstance(data, dict) and not data.get("remark") and bool(data.get("elements"))


def fetch_osm_streets(
    cache_dir: str, ibge: str = MARINGA_IBGE, refresh: bool = False, attempts: int = 4, wait_s: float = 30
) -> Dict[str, Any]:
    """Descarga (o lee de caché) las vías OSM del municipio. La petición solo lleva el código IBGE.

    Solo se cachea un resultado completo; una caché ilegible o vacía se ignora y se vuelve a descargar.
    """
    if ibge != MARINGA_IBGE:
        raise ValueError(f"solo se cargan calles de Maringá (IBGE {MARINGA_IBGE}), no {ibge!r}")
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if not refresh:
        for cached in sorted(folder.glob(f"{ibge}_*.json"), reverse=True):
            try:
                data = json.loads(cached.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _usable(data):
                return data
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):  # Overpass answers 429/5xx or a 200 with a "remark" when busy
        try:
            response = requests.post(
                _OVERPASS_URL,
                data={"data": overpass_query(ibge)},
                headers={"User-Agent": "rastreador-streets/0.1", "Accept": "application/json"},
                timeout=300,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise _IncompleteOverpass(f"HTTP {response.status_code}")
            response.raise_for_status()  # other 4xx (bad query): not retried
            try:
                data = response.json()
            except ValueError:
                raise _IncompleteOverpass("not JSON")
            if not _usable(data):
                raise _IncompleteOverpass("empty or remark")
            break
        except (requests.ConnectionError, requests.Timeout, _IncompleteOverpass):
            if attempt == attempts:
                raise
            time.sleep(wait_s * attempt)
    target = folder / f"{ibge}_{date.today().isoformat()}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, target)  # atomic: an interrupted write never leaves a truncated cache
    return data


def _way_length_m(geometry: Iterable[Dict[str, float]]) -> float:
    pts = [(p["lat"], p["lon"]) for p in geometry]
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:]))


def _bearing(geometry: list) -> float:
    a, b = geometry[0], geometry[-1]
    return math.atan2(b["lon"] - a["lon"], b["lat"] - a["lat"])


def _paired_oneway_m(oneways: list) -> float:
    """Longitud de tramos de sentido único con otro tramo opuesto (mismo nombre) a <80 m: calzada doble."""
    paired = 0.0
    for i, (mid, brg, length) in enumerate(oneways):
        for j, (mid2, brg2, _) in enumerate(oneways):
            if (
                i != j
                and abs((brg - brg2 + math.pi) % (2 * math.pi) - math.pi) > 2.4
                and haversine_m(mid["lat"], mid["lon"], mid2["lat"], mid2["lon"]) < 80
            ):
                paired += length
                break
    return paired


def _ref_keys(ref: str) -> list:
    return [f"REF|{_plain(r).replace(' ', '')}" for r in (ref or "").split(";") if _plain(r)]


def index_osm_ways(
    osm: Dict[str, Any], centro: Tuple[float, float] = CENTRO_MARINGA, radio_m: float = RADIO_CASCO_M
) -> Dict[str, Dict[str, Any]]:
    """Une los tramos OSM de una misma calle por clave normalizada.

    Solo cuenta los tramos cuyo punto medio cae a <= radio_m del casco; los demás suman a `n_fuera`.
    Calcula longitud, dispersión (diagonal de la caja) y `pareado_m` (calzadas dobles contadas dos veces).
    Además crea entradas "REF|PR317" por la etiqueta `ref`, que solo se usan si se pide el cruce por ref.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for el in osm.get("elements", []):
        geometry = el.get("geometry") or []
        tags = el.get("tags") or {}
        name = tags.get("name")
        if el.get("type") != "way" or not name or len(geometry) < 2:
            continue
        tipo, nome = normalize_street(name)
        if not nome:
            continue
        first, last = geometry[0], geometry[-1]
        mid = {"lat": (first["lat"] + last["lat"]) / 2, "lon": (first["lon"] + last["lon"]) / 2}
        inside = haversine_m(centro[0], centro[1], mid["lat"], mid["lon"]) <= radio_m
        length = _way_length_m(geometry)
        keys = [(street_key(tipo, nome), name)] + [(k, tags["ref"]) for k in _ref_keys(tags.get("ref", ""))]
        for key, shown in keys:
            e = out.setdefault(
                key, {"name": shown, "length_m": 0.0, "n_ways": 0, "n_fuera": 0, "lat": [], "lon": [], "oneways": []}
            )
            if not inside:
                e["n_fuera"] += 1
                continue
            e["length_m"] += length
            e["n_ways"] += 1
            e["lat"] += [p["lat"] for p in geometry]
            e["lon"] += [p["lon"] for p in geometry]
            if tags.get("oneway") in ("yes", "1", "true", "-1") and not key.startswith("REF|"):
                e["oneways"].append((mid, _bearing(geometry) + (math.pi if tags["oneway"] == "-1" else 0.0), length))
    for e in out.values():
        lats, lons, oneways = e.pop("lat"), e.pop("lon"), e.pop("oneways")
        e["spread_m"] = haversine_m(min(lats), min(lons), max(lats), max(lons)) if lats else 0.0
        e["pareado_m"] = _paired_oneway_m(oneways)
    return out



def osm_segments(
    osm: Dict[str, Any], needed_keys: set, centro: Tuple[float, float] = CENTRO_MARINGA, radio_m: float = RADIO_CASCO_M
) -> list:
    """(osm_id, clave, nombre, [(lon, lat)...], longitud_m) de los tramos del casco de las claves pedidas.

    Misma regla de clave y de radio que index_osm_ways, para que el catálogo y la geometría coincidan.
    """
    out = []
    for el in osm.get("elements", []):
        geometry = el.get("geometry") or []
        tags = el.get("tags") or {}
        name = tags.get("name")
        if el.get("type") != "way" or not name or len(geometry) < 2:
            continue
        tipo, nome = normalize_street(name)
        keys = {street_key(tipo, nome), *_ref_keys(tags.get("ref", ""))} & needed_keys
        if not keys:
            continue
        first, last = geometry[0], geometry[-1]
        if haversine_m(centro[0], centro[1], (first["lat"] + last["lat"]) / 2, (first["lon"] + last["lon"]) / 2) > radio_m:
            continue
        points = [(p["lon"], p["lat"]) for p in geometry]
        for key in sorted(keys):
            out.append((el.get("id"), key, name, points, _way_length_m(geometry)))
    return out

# ---------------------------------------------------------------------------------------------
# Cruces OPCIONALES (no se usan en producción salvo que se pidan): cada uno devuelve
# {clave_volcado: (clave_osm, match_type)} solo con candidato único, y se evalúa aparte.
# ---------------------------------------------------------------------------------------------
_ABREVIATURAS = {
    "DR": "DOUTOR", "DRA": "DOUTORA", "PROF": "PROFESSOR", "PROFA": "PROFESSORA", "PREF": "PREFEITO",
    "GOV": "GOVERNADOR", "VER": "VEREADOR", "PRES": "PRESIDENTE", "ENG": "ENGENHEIRO", "CEL": "CORONEL",
    "MAL": "MARECHAL", "CAP": "CAPITAO", "DEP": "DEPUTADO", "SEN": "SENADOR", "MONS": "MONSENHOR",
    "STO": "SANTO", "STA": "SANTA",
}
_PREPOSICIONES = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def _bag(tipo: Optional[str], nome: str) -> Tuple[Optional[str], frozenset]:
    """Conjunto de palabras sin orden ni preposiciones, con abreviaturas de título expandidas.
    Los títulos se CONSERVAN: "RUA JOAO" y "RUA DOUTOR JOAO" siguen siendo calles distintas."""
    return tipo, frozenset(_ABREVIATURAS.get(w, w) for w in nome.split() if w not in _PREPOSICIONES)


def _name_keys(osm_ways: Dict[str, Dict[str, Any]]) -> list:
    return [k for k in osm_ways if not k.startswith("REF|") and osm_ways[k]["n_ways"] > 0]


def _is_exact(key: str, osm_ways: Dict[str, Dict[str, Any]]) -> bool:
    return key in osm_ways and osm_ways[key]["n_ways"] > 0


def flexible_aliases(dump: Dict[str, Dict[str, Any]], osm_ways: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    by_bag: Dict[Any, list] = {}
    for k in _name_keys(osm_ways):
        tipo, nome = k.split("|", 1)
        by_bag.setdefault(_bag(tipo or None, nome), []).append(k)
    out = {}
    for k, s in dump.items():
        if s["n_ativos"] and not _is_exact(k, osm_ways):
            cands = by_bag.get(_bag(s["tipo"], s["nome"]), [])
            if len(cands) == 1:
                out[k] = (cands[0], "flexible")
    return out


def _within_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _vowel_flip(a: str, b: str) -> bool:
    """Same word except the final vowel (MARIA/MARIO, ROBERTO/ROBERTA): different people, never a typo."""
    return len(a) == len(b) and a[:-1] == b[:-1] and a[-1] in "AOE" and b[-1] in "AOE"


def tolerance_aliases(dump: Dict[str, Dict[str, Any]], osm_ways: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    """Mismo tipo y nº de palabras; cada palabra igual o a 1 letra (palabras de >=5 letras). Candidato único."""
    buckets: Dict[Any, list] = {}
    for k in _name_keys(osm_ways):
        tipo, nome = k.split("|", 1)
        buckets.setdefault((tipo or None, len(nome.split())), []).append((k, nome.split()))
    out = {}
    for k, s in dump.items():
        if not s["n_ativos"] or _is_exact(k, osm_ways):
            continue
        words = s["nome"].split()
        cands = [
            ok for ok, ow in buckets.get((s["tipo"], len(words)), [])
            if all(_within_one(x, y) for x, y in zip(words, ow))
            and sum(x != y for x, y in zip(words, ow)) == 1
            and not any(x != y and _vowel_flip(x, y) for x, y in zip(words, ow))
        ]
        if len(cands) == 1:
            out[k] = (cands[0], "tolerancia")
    return out


def ref_aliases(dump: Dict[str, Dict[str, Any]], osm_ways: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    """Rodovias del volcado ("PR 317 ...", "BR 376") contra la etiqueta `ref` de OSM (PR-317)."""
    out = {}
    for k, s in dump.items():
        if not s["n_ativos"] or _is_exact(k, osm_ways):
            continue
        m = re.match(r"^(PR|BR) ?(\d{2,3})\b", s["nome"])
        if m and _is_exact(f"REF|{m.group(1)}{m.group(2)}", osm_ways):
            out[k] = (f"REF|{m.group(1)}{m.group(2)}", "ref")
    return out


def match_streets(
    dump: Dict[str, Dict[str, Any]],
    osm_ways: Dict[str, Dict[str, Any]],
    aliases: Optional[Dict[str, Tuple[str, str]]] = None,
    larga_m: float = CALLE_LARGA_M,
    larga_comercios: int = CALLE_LARGA_COMERCIOS,
    dispersion_max_m: float = DISPERSION_MAX_M,
    distritos: Optional[Counter] = None,
    radio_casco_m: float = RADIO_CASCO_M,
) -> Dict[str, Any]:
    """Cruza por clave exacta (tipo, nombre) y, solo si se pasan `aliases`, por los cruces opcionales.

    Lo que no cruza queda sin geometría: no se interpola. Estado de cada calle:
    ok | calle_larga | ambigua (dispersión > dispersion_max_m) | sin_geometria; solo 'ok' entra en el plan.
    """
    aliases = aliases or {}
    streets, unmatched = [], []
    for key, s in dump.items():
        if s["n_ativos"] == 0:
            continue
        osm_key = None
        if _is_exact(key, osm_ways):
            way, match_type, osm_key = osm_ways[key], "exacto", key
        elif key in aliases:
            way, match_type, osm_key = osm_ways[aliases[key][0]], aliases[key][1], aliases[key][0]
        else:
            way, match_type = None, None
        numeros = s["numeros"]
        row = {
            "tipo": s["tipo"], "nome": s["nome"], "n_comercios_ativos": s["n_ativos"],
            "numero_min": min(numeros) if numeros else None, "numero_max": max(numeros) if numeros else None,
            "sem_numero": s["sem_numero"], "bairros": sorted(s["bairros"]), "ceps": sorted(s["ceps"]),
            "osm": way is not None, "match_type": match_type, "street_key": key, "osm_key": osm_key,
        }
        if way is None:
            row.update(
                length_m=None, spread_m=None, pareado_pct=None, estado="sin_geometria",
                calle_larga=s["n_ativos"] > larga_comercios,
            )
            unmatched.append(row)
        else:
            larga = way["length_m"] > larga_m or s["n_ativos"] > larga_comercios
            estado = "ambigua" if way["spread_m"] > dispersion_max_m else "calle_larga" if larga else "ok"
            row.update(
                length_m=round(way["length_m"]), n_ways=way["n_ways"], spread_m=round(way["spread_m"]),
                pareado_pct=round(100 * way["pareado_m"] / way["length_m"]) if way["length_m"] else 0,
                calle_larga=larga, estado=estado, osm_nombre=way["name"],
            )
        row["en_plan_automatico"] = row["estado"] == "ok"
        streets.append(row)
    matched = [r for r in streets if r["osm"]]
    com_ativos = sum(r["n_comercios_ativos"] for r in streets)
    com_cruzados = sum(r["n_comercios_ativos"] for r in matched)
    return {
        "municipio_ibge": MARINGA_IBGE,
        "resumen": {
            "calles_con_comercios_activos": len(streets),
            "cruzadas": len(matched),
            "por_match_type": dict(Counter(r["match_type"] for r in matched)),
            "sin_cruzar": len(unmatched),
            "pct_calles_cruzadas": round(100 * len(matched) / len(streets), 1) if streets else 0.0,
            "comercios_activos": com_ativos,
            "comercios_en_calles_cruzadas": com_cruzados,
            "pct_comercios_en_calles_cruzadas": round(100 * com_cruzados / com_ativos, 1) if com_ativos else 0.0,
            "por_estado": dict(Counter(r["estado"] for r in streets)),
            "calles_largas": sum(r["calle_larga"] for r in streets),
            "comercios_distrito": sum(s["n_distrito"] for s in dump.values()),
            "comercios_en_plan_automatico": sum(r["n_comercios_ativos"] for r in streets if r["en_plan_automatico"]),
            "supuestos": {
                "calle_larga_m": larga_m, "calle_larga_comercios": larga_comercios,
                "dispersion_max_m": dispersion_max_m, "radio_casco_m": radio_casco_m,
            },
        },
        "distritos": dict(distritos or {}),
        "calles": streets,
        "sin_cruzar": sorted(unmatched, key=lambda r: -r["n_comercios_ativos"]),
    }
