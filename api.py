#!/usr/bin/env python3
"""
FastAPI Backend Server for Rastreador CNPJ ETL
Provides GeoJSON endpoints for MapLibre/react-map-gl integrations.

Author: Antigravity DevOps Assistant
Date: 2026-05-24
"""

import os
import time
import json
import hashlib
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text


# ==============================================================================
# ENVIRONMENT VARIABLE LOADER (ZERO-DEPENDENCY)
# ==============================================================================
def load_env_file(dotenv_path: str = ".env") -> None:
    """Loads environment variables from a .env file if it exists."""
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            print(f"Loaded environment variables from {dotenv_path}")
        except Exception as e:
            print(f"Warning: Could not read {dotenv_path}: {e}")


def load_environment_files() -> None:
    """Loads environment files in a predictable precedence order."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    env_files = [".env"]
    if app_env:
        env_files.append(f".env.{app_env}")
    env_files.append(".env.local")

    for env_file in env_files:
        load_env_file(env_file)


load_environment_files()


# ==============================================================================
# APP INSTANCE & CORS
# ==============================================================================
app = FastAPI(
    title="Londrina Radar Comercial API",
    description="Plataforma analítica geoespacial para rastreo de comercios en Londrina, PR",
    version="1.0.0",
)

cors_origins_raw = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:8000",
)
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# IN-MEMORY RESPONSE CACHE
# ==============================================================================
_RESPONSE_CACHE: Dict[str, Any] = {}


def get_cached_response(key: str) -> Optional[Any]:
    """Gets a cached response if it exists and has not expired."""
    if key in _RESPONSE_CACHE:
        val, expiry = _RESPONSE_CACHE[key]
        if time.time() < expiry:
            return val
        else:
            del _RESPONSE_CACHE[key]
    return None


def set_cached_response(key: str, value: Any, ttl: int = 300) -> None:
    """Sets a cached response with an expiration time."""
    _RESPONSE_CACHE[key] = (value, time.time() + ttl)


def clear_response_cache() -> None:
    """Clears the entire response cache."""
    _RESPONSE_CACHE.clear()


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


# ==============================================================================
# DATA MODELS
# ==============================================================================
class ClusterPoint(BaseModel):
    type: str = "Point"
    coordinates: List[float]  # [lng, lat]


class Cluster(BaseModel):
    cluster_id: int
    total_lojas: int
    center_geom: ClusterPoint


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


class RubroDistribucion(BaseModel):
    categoria: str
    cantidad: int


class StreetAnalytics(BaseModel):
    logradouro: str
    total_negocios: int
    distribucion_rubros: List[RubroDistribucion]
    predominancia: str


# ==============================================================================
# DATABASE OR LOCAL JSON LOADER
# ==============================================================================
def load_businesses() -> List[Dict[str, Any]]:
    """
    Loads businesses from PostgreSQL database if configured,
    otherwise falls back to reading the local JSON file.

    Priority:
    1. Table `estabelecimentos` (yield actual data, with stored lat/lon if geocoded)
    2. Table `londrina_businesses` (legacy)
    3. JSON files (fallback)
    """
    conn_str = os.environ.get("DATABASE_URL")
    db_host = "Database URL"

    if not conn_str:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            conn_str = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )
        else:
            db_host = None

    if conn_str:
        # Try estabelecimentos first (the new canonical table)
        for table_name in ["estabelecimentos", "londrina_businesses"]:
            try:
                engine = create_engine(conn_str)
                with engine.connect() as conn:
                    result = conn.execute(text(f"SELECT * FROM {table_name}"))
                    businesses = [dict(row._mapping) for row in result]
                    print(
                        f"Loaded {len(businesses)} businesses from PostgreSQL table '{table_name}'."
                    )
                    if len(businesses) > 0:
                        return businesses
            except Exception as e:
                print(f"PostgreSQL table '{table_name}' failed: {e}.")

    # Fallback to local JSON file
    json_paths = ["londrina_businesses.json", "londrina_businesses_polars.json"]
    for path in json_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    print(f"Loaded {len(data)} businesses from JSON file: {path}")
                    return data
            except Exception as e:
                print(f"Failed to read JSON at {path}: {e}")

    # If no data found, return empty list
    print("WARNING: No data source found! Please run the ETL script first.")
    return []


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
# API ENDPOINTS
# ==============================================================================
@app.get("/health")
def health_check():
    """Health check endpoint for Docker container checks"""
    return {"status": "ok", "message": "Rastreador CNPJ backend is running"}


@app.get("/api/heatmap")
def get_heatmap_geojson():
    """
    Returns a GeoJSON FeatureCollection of all businesses.
    This endpoint is used by the frontend to render the beautiful MapLibre Heatmap layer.
    """
    cache_key = "heatmap_geojson"
    cached = get_cached_response(cache_key)
    if cached is not None:
        print("Returning cached heatmap GeoJSON.")
        return cached

    businesses = load_businesses()

    # If empty, try to generate sample data and run polars ETL to auto-populate!
    if len(businesses) == 0:
        print("No businesses detected! Attempting to auto-generate sample data...")
        try:
            # We run generate_sample_data and then etl polars
            import generate_sample_data
            import cnpj_etl_polars

            generate_sample_data.main()

            # Create a mock CSV if we don't have it
            if os.path.exists("sample_estabelecimentos.csv"):
                cnpj_etl_polars.main("sample_estabelecimentos.csv")
                businesses = load_businesses()
        except Exception as e:
            print(f"Failed to auto-generate data: {e}")

    features = []
    for biz in businesses:
        cnpj = format_cnpj(biz)
        biz_type = biz.get("business_type", "retail")
        municipio = biz.get("municipio")

        # Use stored real coordinates if geocoded, otherwise fallback to deterministic
        lat = biz.get("latitude")
        lon = biz.get("longitude")
        if lat is not None and lon is not None:
            coords = [float(lon), float(lat)]
        else:
            coords = assign_geographic_coords(cnpj, biz_type, municipio)

        porte_val = biz.get("porte_empresa")
        porte_desc = "Otros"
        if porte_val in [1, "1", "01"]:
            porte_desc = "ME (Microempresa)"
        elif porte_val in [3, "3", "03"]:
            porte_desc = "EPP (Empresa de Pequeno Porte)"
        elif porte_val in [5, "5", "05"]:
            porte_desc = "Grande/Otros (Demais)"

        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coords},
            "properties": {
                "cnpj": cnpj,
                "nome_fantasia": biz.get("nome_fantasia", "Comercio"),
                "business_type": biz_type,
                "cnae": biz.get("cnae_fiscal", biz.get("cnae_fiscal_principal", "")),
                "cnae_desc": biz.get("cnae_fiscal_descricao", ""),
                "bairro": biz.get("bairro", "Centro"),
                "logradouro": biz.get("logradouro", ""),
                "numero": biz.get("numero", ""),
                "cep": biz.get("cep", ""),
                "telefone_1": biz.get("telefone_1", ""),
                "porte_empresa": str(porte_val or ""),
                "porte_desc": porte_desc,
                "municipio": municipio or "Londrina",
            },
        }
        features.append(feature)

    print(f"Returning {len(features)} points as GeoJSON.")
    result = {"type": "FeatureCollection", "features": features}
    set_cached_response(cache_key, result, ttl=300)
    return result


@app.get("/api/clusters/emergentes", response_model=List[Cluster])
def get_emergent_clusters():
    """
    Aggregates businesses into commercial clusters using PostGIS ST_ClusterDBSCAN
    when real coordinates are available, falling back to the 5 known Londrina hubs.
    Returns ranked clusters by density.
    """
    cache_key = "emergent_clusters"
    cached = get_cached_response(cache_key)
    if cached is not None:
        print("Returning cached emergent clusters.")
        return cached

    # Try PostGIS clustering first if coordinates exist
    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            conn_str = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )

    if conn_str:
        try:
            engine = create_engine(conn_str)
            with engine.connect() as conn:
                query = text("""
                    SELECT
                        cluster_id,
                        COUNT(*)::int as total_lojas,
                        ST_AsGeoJSON(ST_Centroid(ST_Collect(geom)))::json->'coordinates' as center_coords
                    FROM (
                        SELECT
                            ST_ClusterDBSCAN(geom, 0.003, 1) OVER () as cluster_id,
                            geom
                        FROM estabelecimentos
                        WHERE situacao_cadastral = 2
                          AND geom IS NOT NULL
                          AND business_type IN ('tech', 'repairs')
                    ) sub
                    WHERE cluster_id IS NOT NULL
                    GROUP BY cluster_id
                    ORDER BY total_lojas DESC
                """)
                result = conn.execute(query)
                clusters = []
                for row in result:
                    row_dict = dict(row._mapping)
                    coords = row_dict["center_coords"]
                    clusters.append(
                        Cluster(
                            cluster_id=int(row_dict["cluster_id"]) + 100,
                            total_lojas=row_dict["total_lojas"],
                            center_geom=ClusterPoint(coordinates=coords),
                        )
                    )
                if clusters:
                    print(f"Returning {len(clusters)} PostGIS clusters.")
                    set_cached_response(cache_key, clusters, ttl=300)
                    return clusters
        except Exception as e:
            print(f"PostGIS clustering failed: {e}. Falling back to hub method.")

    # Fallback: deterministic hub assignment (backward compatible)
    businesses = load_businesses()
    if len(businesses) == 0:
        return []

    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for biz in businesses:
        cnpj = (
            str(biz.get("cnpj_basico", "00000000"))
            + str(biz.get("cnpj_ordem", "0000"))
            + str(biz.get("cnpj_dv", "00"))
        )
        biz_type = biz.get("business_type", "retail")
        h = hashlib.md5(cnpj.encode("utf-8")).hexdigest()
        hash_val = int(h, 16)
        if biz_type == "gastronomy":
            hub_idx = [2, 3, 5, 1, 4][hash_val % 5]
        elif biz_type == "tech":
            hub_idx = [3, 2, 1, 5, 4][hash_val % 5]
        else:
            hub_idx = [1, 4, 2, 3, 5][hash_val % 5]
        counts[hub_idx] += 1

    clusters = []
    for hub_id, count in counts.items():
        coords = HUBS[hub_id]["coords"]
        clusters.append(
            Cluster(
                cluster_id=hub_id,
                total_lojas=count,
                center_geom=ClusterPoint(coordinates=coords),
            )
        )
    clusters.sort(key=lambda c: c.total_lojas, reverse=True)
    set_cached_response(cache_key, clusters, ttl=300)
    return clusters


@app.get("/api/analytics/streets", response_model=List[StreetAnalytics])
def get_commercial_streets_analytics():
    """
    Returns the top 15 commercial streets in Londrina.
    Each street includes total business count, distribution by category (rubro),
    and the predominant category. Uses PostgreSQL when available, JSON fallback otherwise.
    """
    conn_str = os.environ.get("DATABASE_URL")

    if not conn_str:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            conn_str = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )

    raw_rows: List[Dict[str, Any]] = []

    if conn_str:
        for table_name in ["estabelecimentos", "londrina_businesses"]:
            try:
                engine = create_engine(conn_str)
                with engine.connect() as conn:
                    query = text(f"""
                        SELECT logradouro, cnae_fiscal, porte_empresa
                        FROM {table_name}
                        WHERE logradouro IS NOT NULL AND logradouro != ''
                          AND porte_empresa IN ('01', '03')
                    """)
                    result = conn.execute(query)
                    for row in result:
                        raw_rows.append(
                            dict(row._mapping)
                            if hasattr(row, "_mapping")
                            else {
                                "logradouro": row[0],
                                "cnae_fiscal_principal": row[1],
                                "porte_empresa": row[2],
                            }
                        )
                    if raw_rows:
                        print(
                            f"Loaded {len(raw_rows)} rows from table '{table_name}' for street analytics."
                        )
                        break
            except Exception as e:
                print(f"Table '{table_name}' query failed: {e}.")

    # Fallback to local JSON
    if not raw_rows:
        raw_rows = load_businesses()

    if not raw_rows:
        return []

    # -------------------------------------------------------------------------
    # Aggregate: street → { total, {category → count} }
    # -------------------------------------------------------------------------
    street_data: Dict[str, Dict[str, Any]] = {}

    for biz in raw_rows:
        logradouro = (biz.get("logradouro") or "").strip()
        if not logradouro:
            continue

        porte = biz.get("porte_empresa")
        # Filter: only micro/small businesses size '01' or '03' (or 1 or 3)
        porte_str = str(porte).zfill(2) if porte is not None else ""
        if porte_str not in ["01", "03"]:
            continue

        categoria = cnae_to_category(biz.get("cnae_fiscal_principal"))

        if logradouro not in street_data:
            street_data[logradouro] = {"total": 0, "rubros": {}}

        street_data[logradouro]["total"] += 1
        rubros = street_data[logradouro]["rubros"]
        rubros[categoria] = rubros.get(categoria, 0) + 1

    # Sort streets by total descending, take top 15
    sorted_streets = sorted(
        street_data.items(), key=lambda x: x[1]["total"], reverse=True
    )[:15]

    result_list: List[StreetAnalytics] = []
    for street_name, data in sorted_streets:
        rubros_sorted = sorted(data["rubros"].items(), key=lambda x: x[1], reverse=True)
        predominancia = rubros_sorted[0][0] if rubros_sorted else "Otros"
        distribucion = [
            RubroDistribucion(categoria=cat, cantidad=cnt) for cat, cnt in rubros_sorted
        ]
        result_list.append(
            StreetAnalytics(
                logradouro=street_name,
                total_negocios=data["total"],
                distribucion_rubros=distribucion,
                predominancia=predominancia,
            )
        )

    print(f"Returning analytics for {len(result_list)} streets.")
    return result_list


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


@app.get("/api/corridor/br369")
def get_br369_corridor():
    """
    Intelligent BR-369 commercial corridor analysis.
    Returns GeoJSON with:
      - Route line (LineString through all cities)
      - City point features with business stats per municipio
      - Route metadata (total km, total businesses, density)
    """
    cache_key = "br369_corridor"
    cached = get_cached_response(cache_key)
    if cached is not None:
        print("Returning cached BR-369 corridor.")
        return cached

    businesses = load_businesses()

    # Count businesses per municipio + tech/repairs breakdown
    city_stats = {}
    for c in BR369_CITIES:
        city_stats[c["name"]] = {"total": 0, "tech": 0, "repairs": 0}

    for biz in businesses:
        mun = (biz.get("municipio") or "").strip()
        btype = biz.get("business_type", "")
        for c in BR369_CITIES:
            if mun.lower() == c["name"].lower() or mun.lower().startswith(c["name"].lower()[:5]):
                city_stats[c["name"]]["total"] += 1
                if btype == "tech":
                    city_stats[c["name"]]["tech"] += 1
                elif btype == "repairs":
                    city_stats[c["name"]]["repairs"] += 1
                break

    total_businesses = sum(s["total"] for s in city_stats.values())
    total_tech = sum(s["tech"] for s in city_stats.values())
    total_repairs = sum(s["repairs"] for s in city_stats.values())

    # Route line through all city centers
    route_coords = [[c["lng"], c["lat"]] for c in BR369_CITIES]

    # City point features
    features = []
    for c in BR369_CITIES:
        stats = city_stats[c["name"]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["lng"], c["lat"]]},
            "properties": {
                "name": c["name"],
                "total_businesses": stats["total"],
                "tech_businesses": stats["tech"],
                "repairs_businesses": stats["repairs"],
                "type": "city",
            },
        })

    # Route line feature
    features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": route_coords},
        "properties": {
            "name": "BR-369 Corridor",
            "type": "route",
            "total_cities": len(BR369_CITIES),
            "total_businesses": total_businesses,
            "total_tech": total_tech,
            "total_repairs": total_repairs,
        },
    })

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "corridor": "BR-369",
            "cities": [c["name"] for c in BR369_CITIES],
            "total_businesses": total_businesses,
            "total_tech": total_tech,
            "total_repairs": total_repairs,
            "tech_pct": round(total_tech / total_businesses * 100, 1) if total_businesses else 0,
        },
    }

    set_cached_response(cache_key, result, ttl=300)
    print(f"Returning BR-369 corridor with {total_businesses} businesses across {len(BR369_CITIES)} cities.")
    return result


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


class TechBusiness(BaseModel):
    cnpj: str
    nome_fantasia: str
    cnae: str
    cnae_label: str
    cnae_icon: str
    bairro: str
    logradouro: str
    municipio: str
    business_type: str


class TechBusinessesResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: List[TechBusiness]


@app.get("/api/businesses/tech", response_model=TechBusinessesResponse)
def get_tech_businesses(limit: int = 50, offset: int = 0, search: str = ""):
    """
    Returns paginated tech businesses with enriched CNAE subcategory data.
    Supports full-text search by name, CNAE or neighborhood.
    - limit: max items per page (default 50)
    - offset: pagination offset (default 0)
    - search: filter by nome_fantasia, cnae or bairro (case-insensitive)
    """
    businesses = load_businesses()

    # Filter only tech businesses
    tech_businesses = [b for b in businesses if b.get("business_type") == "tech"]

    # Apply search filter
    search_lower = search.strip().lower()
    if search_lower:
        tech_businesses = [
            b
            for b in tech_businesses
            if search_lower in (b.get("nome_fantasia") or "").lower()
            or search_lower
            in str(b.get("cnae_fiscal") or b.get("cnae_fiscal_principal") or "").lower()
            or search_lower in (b.get("bairro") or "").lower()
            or search_lower in (b.get("logradouro") or "").lower()
        ]

    total = len(tech_businesses)

    # Paginate
    paginated = tech_businesses[offset : offset + limit]

    items = []
    for biz in paginated:
        cnpj = format_cnpj(biz)
        cnae_raw = str(biz.get("cnae_fiscal") or biz.get("cnae_fiscal_principal") or "")
        prefix = cnae_raw[:2]
        sub = TECH_CNAE_SUBCATEGORY.get(prefix, {"label": "Tecnología", "icon": "💡"})

        items.append(
            TechBusiness(
                cnpj=cnpj,
                nome_fantasia=biz.get("nome_fantasia") or f"Empresa Tech {cnpj[:8]}",
                cnae=cnae_raw,
                cnae_label=sub["label"],
                cnae_icon=sub["icon"],
                bairro=biz.get("bairro") or "Centro",
                logradouro=biz.get("logradouro") or "",
                municipio=biz.get("municipio") or "Londrina",
                business_type="tech",
            )
        )

    print(
        f"Returning {len(items)} tech businesses (total={total}, offset={offset}, search='{search}')."
    )
    return TechBusinessesResponse(total=total, offset=offset, limit=limit, items=items)


# ==============================================================================
# NEARBY BUSINESSES (PostGIS spatial search)
# ==============================================================================
from math import radians, sin, cos, asin, sqrt


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r"""Great-circle distance in meters between two coordinate pairs."""
    r = 6371000
    la1, lo1, la2, lo2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    return int(2 * r * asin(sqrt(a)))


def fix_encoding(text):
    r"""Repair double-encoded UTF-8 mojibake (e.g. 'InformaÃ§Ã£o' -> 'Informação')."""
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


@app.get("/api/businesses/near")
def get_businesses_near(lat: float, lon: float, radius: int = 500):
    """
    Returns businesses within `radius` meters of (lat, lon).
    Uses PostGIS ST_DWithin on the geography column for accurate meter-based search.
    Fallback to load_businesses() + haversine if geom column is unavailable.
    """
    if radius > 2000:
        radius = 2000
    if radius < 1:
        radius = 500

    cache_key = f"near_{lat}_{lon}_{radius}"
    cached = get_cached_response(cache_key)
    if cached is not None:
        return cached

    conn_str = os.environ.get("DATABASE_URL")
    if not conn_str:
        db_user = os.environ.get("DB_USER")
        db_password = os.environ.get("DB_PASSWORD")
        db_host = os.environ.get("DB_HOST")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME")
        if all([db_user, db_password, db_host, db_name]):
            conn_str = (
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )

    if conn_str:
        try:
            engine = create_engine(conn_str)
            with engine.connect() as conn:
                query = text("""
                    SELECT
                        cnpj_completo,
                        nome_fantasia,
                        business_type,
                        cnae_fiscal,
                        logradouro,
                        numero,
                        bairro,
                        municipio,
                        porte_empresa,
                        latitude,
                        longitude,
                        ST_Distance(
                            geom::geography,
                            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                        )::int as distance_m
                    FROM estabelecimentos
                    WHERE ST_DWithin(
                        geom::geography,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                        :radius
                    )
                      AND situacao_cadastral = 2
                      AND geom IS NOT NULL
                    ORDER BY distance_m ASC
                    LIMIT 200
                """)
                result = conn.execute(query, {"lat": lat, "lon": lon, "radius": radius})
                items = []
                for row in result:
                    r = dict(row._mapping)
                    items.append({
                        "cnpj": r.get("cnpj_completo", ""),
                        "nome_fantasia": fix_encoding(r.get("nome_fantasia") or ""),
                        "business_type": r.get("business_type") or "",
                        "cnae": str(r.get("cnae_fiscal") or ""),
                        "logradouro": fix_encoding(r.get("logradouro") or ""),
                        "numero": r.get("numero") or "",
                        "bairro": fix_encoding(r.get("bairro") or ""),
                        "municipio": fix_encoding(r.get("municipio") or ""),
                        "lat": float(r["latitude"]) if r.get("latitude") else 0,
                        "lon": float(r["longitude"]) if r.get("longitude") else 0,
                        "distance_m": r.get("distance_m", 0),
                        "cnae_label": cnae_to_category(r.get("cnae_fiscal")),
                        "cnae_icon": "",
                        "porte_empresa": str(r.get("porte_empresa") or ""),
                    })
                response = {"items": items, "total": len(items), "radius": radius}
                set_cached_response(cache_key, response, ttl=120)
                return response
        except Exception as e:
            print(f"PostGIS /businesses/near failed: {e}. Falling back to haversine.")

    # Fallback: load all businesses and filter by haversine
    businesses = load_businesses()
    items = []
    for biz in businesses:
        biz_lat = biz.get("latitude")
        biz_lon = biz.get("longitude")
        if biz_lat is None or biz_lon is None:
            continue
        dist = haversine_m(lat, lon, float(biz_lat), float(biz_lon))
        if dist <= radius:
            cnpj = format_cnpj(biz)
            cnae_raw = str(
                biz.get("cnae_fiscal") or biz.get("cnae_fiscal_principal") or ""
            )
            items.append({
                "cnpj": cnpj,
                "nome_fantasia": fix_encoding(biz.get("nome_fantasia") or ""),
                "business_type": biz.get("business_type") or "",
                "cnae": cnae_raw,
                "logradouro": fix_encoding(biz.get("logradouro") or ""),
                "numero": biz.get("numero") or "",
                "bairro": fix_encoding(biz.get("bairro") or ""),
                "municipio": fix_encoding(biz.get("municipio") or ""),
                "lat": float(biz_lat),
                "lon": float(biz_lon),
                "distance_m": dist,
                "cnae_label": cnae_to_category(cnae_raw),
                "cnae_icon": "",
                "porte_empresa": str(biz.get("porte_empresa") or ""),
            })
    items.sort(key=lambda x: x["distance_m"])
    items = items[:200]
    response = {"items": items, "total": len(items), "radius": radius}
    set_cached_response(cache_key, response, ttl=120)
    return response


# ==============================================================================
# MAIN METHOD
# ==============================================================================
# ==============================================================================
# STREET SEGMENTS, VISITS AND OFFLINE SYNC - EXTRA MODELS & ENDPOINTS
# ==============================================================================
import hmac
import base64
from datetime import datetime
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

security = HTTPBearer(auto_error=False)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secret_key_londrina_radar_2026")
SECRET_KEY = JWT_SECRET_KEY


# ------------------------------------------------------------------------------
# 0-DEPENDENCY JWT & CRYPTO UTILITIES
# ------------------------------------------------------------------------------
def base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("utf-8")


def base64url_decode(payload: str) -> bytes:
    padding = "=" * (4 - (len(payload) % 4))
    return base64.urlsafe_b64decode(payload + padding)


def create_jwt_token(data: dict, expires_in: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = data.copy()
    payload["exp"] = int(time.time()) + expires_in
    header_json = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    unsigned_token = (
        base64url_encode(header_json) + "." + base64url_encode(payload_json)
    )
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), unsigned_token.encode("utf-8"), hashlib.sha256
    ).digest()
    return unsigned_token + "." + base64url_encode(signature)


def decode_jwt_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        header_segment, payload_segment, signature_segment = parts
        unsigned_token = header_segment + "." + payload_segment
        expected_signature = hmac.new(
            SECRET_KEY.encode("utf-8"), unsigned_token.encode("utf-8"), hashlib.sha256
        ).digest()
        actual_signature = base64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return {}
        payload = json.loads(base64url_decode(payload_segment).decode("utf-8"))
        if payload.get("exp", 0) < time.time():
            return {}
        return payload
    except Exception:
        return {}


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------
# PYDANTIC SCHEMAS
# ------------------------------------------------------------------------------
class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class VisitCreate(BaseModel):
    cnpj: Optional[str] = None
    lat: float
    lon: float
    logradouro: str
    bairro: Optional[str] = None
    route_id: Optional[str] = None
    notes: Optional[str] = None
    visited_at: Optional[str] = None


class VisitSyncItem(BaseModel):
    cnpj: Optional[str] = None
    lat: float
    lon: float
    logradouro: str
    bairro: Optional[str] = None
    route_id: Optional[str] = None
    notes: Optional[str] = None
    visited_at: str


class RouteStopCreate(BaseModel):
    address: str
    lat: float
    lon: float
    cep: Optional[str] = None
    display_name: Optional[str] = None


class RouteStopResponse(BaseModel):
    id: str
    stop_order: int
    address: str
    lat: float
    lon: float
    cep: Optional[str]
    display_name: Optional[str]


class RouteCreate(BaseModel):
    name: str
    city_id: int
    stops: List[RouteStopCreate] = []


class RouteResponse(BaseModel):
    id: str
    name: str
    city_id: int
    created_at: str
    stops: List[RouteStopResponse] = []


class DailyRouteCreate(BaseModel):
    name: str
    day_of_week: Optional[str] = None
    streets: List[str] = []


class DailyRouteUpdate(BaseModel):
    name: Optional[str] = None
    day_of_week: Optional[str] = None
    streets: Optional[List[str]] = None


# ------------------------------------------------------------------------------
# DB SETUP & GLOBAL ENGINE
# ------------------------------------------------------------------------------
conn_str = os.environ.get("DATABASE_URL")
if not conn_str:
    db_user = os.environ.get("DB_USER")
    db_password = os.environ.get("DB_PASSWORD")
    db_host = os.environ.get("DB_HOST", "db")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "londrina_comercio")
    if all([db_user, db_password, db_host, db_name]):
        conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

db_engine = create_engine(conn_str) if conn_str else None

# Initialize User Table
if db_engine:
    try:
        with db_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    username VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            print("Successfully initialized users table in DB.")
    except Exception as e:
        print(f"Error initializing users table: {e}")

if db_engine:
    try:
        with db_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS daily_routes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id),
                    name VARCHAR(255) NOT NULL,
                    day_of_week VARCHAR(20),
                    streets TEXT[] DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            print("Successfully initialized daily_routes table in DB.")
    except Exception as e:
        print(f"Error initializing daily_routes table: {e}")

if db_engine:
    try:
        with db_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS routes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL,
                    city_id INTEGER REFERENCES cities(id),
                    name VARCHAR(255) NOT NULL,
                    geom GEOMETRY(LineString, 4326),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """))
            conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS route_stops (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    route_id UUID REFERENCES routes(id) ON DELETE CASCADE,
                    stop_order INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    lat NUMERIC(10,7) NOT NULL,
                    lon NUMERIC(10,7) NOT NULL,
                    cep VARCHAR(10),
                    display_name TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stops_route ON route_stops(route_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_routes_city_id ON routes(city_id);"))
            conn.commit()
            print("Successfully initialized routes tables in DB.")
    except Exception as e:
        print(f"Error initializing routes tables: {e}")


# ------------------------------------------------------------------------------
# DEPENDENCY FOR AUTHENTICATION
# ------------------------------------------------------------------------------
def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token missing")
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]


def get_optional_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    if not credentials:
        return None
    token = credentials.credentials
    payload = decode_jwt_token(token)
    return payload.get("user_id") if payload else None


def get_effective_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if credentials:
        token = credentials.credentials
        payload = decode_jwt_token(token)
        if payload and "user_id" in payload:
            return payload["user_id"]
    return os.getenv("DEV_USER_ID", "00000000-0000-0000-0000-000000000001")


# ------------------------------------------------------------------------------
# AUTH ENDPOINTS
# ------------------------------------------------------------------------------
@app.post("/auth/register")
def register_user(user: UserRegister):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        pw_hash = hash_password(user.password)
        with db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO users (username, password_hash) VALUES (:username, :pw_hash) RETURNING id"
                ),
                {"username": user.username, "pw_hash": pw_hash},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="User creation failed")
            user_id = row[0]
            conn.commit()
            token = create_jwt_token(
                {"user_id": str(user_id), "username": user.username}
            )
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Username already registered")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@app.post("/auth/login")
def login_user(user: UserLogin):
    if not db_engine:
        return {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "username": user.username,
            "token": "dummy_dev_token",
        }
    try:
        pw_hash = hash_password(user.password)
        with db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, password_hash FROM users WHERE username = :username"),
                {"username": user.username},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=400, detail="Invalid username or password"
                )
            user_id, db_pw_hash = row
            if db_pw_hash != pw_hash:
                raise HTTPException(
                    status_code=400, detail="Invalid username or password"
                )

            token = create_jwt_token(
                {"user_id": str(user_id), "username": user.username}
            )
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


# ------------------------------------------------------------------------------
# TRACKING ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/api/segments")
def get_street_segments(
    bbox: str, user_id: Optional[str] = Depends(get_optional_user_id)
):
    """
    Returns GeoJSON FeatureCollection of street segments within the specified bbox.
    Format: bbox=lng1,lat1,lng2,lat2
    Includes 'visited_by_user' boolean if a valid JWT token is provided.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="Bbox must have exactly 4 coordinates: lng1,lat1,lng2,lat2",
            )
        lng1, lat1, lng2, lat2 = map(float, parts)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Bbox coordinates must be valid numbers"
        )

    try:
        with db_engine.connect() as conn:
            if user_id:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           EXISTS(
                               SELECT 1 FROM visits v
                               WHERE v.logradouro = s.name AND v.user_id = :user_id
                           ) as visited_by_user,
                           (SELECT MAX(v.visited_at) FROM visits v
                              WHERE v.logradouro = s.name AND v.user_id = :user_id) as last_visited
                    FROM street_segments s
                    WHERE ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))
                """)
                params = {
                    "lng1": lng1,
                    "lat1": lat1,
                    "lng2": lng2,
                    "lat2": lat2,
                    "user_id": user_id,
                }
            else:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           FALSE as visited_by_user, NULL as last_visited
                    FROM street_segments s
                    WHERE ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))
                """)
                params = {"lng1": lng1, "lat1": lat1, "lng2": lng2, "lat2": lat2}

            result = conn.execute(query, params)
            features = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"])
                feature = {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "id": row_dict["id"],
                        "osm_id": row_dict["osm_id"],
                        "name": row_dict["name"] or "Calle sin nombre",
                        "length_m": (
                            float(row_dict["length_m"]) if row_dict["length_m"] else 0.0
                        ),
                        "visited_by_user": row_dict["visited_by_user"],
                        "notes": None,
                        "visited_at": (
                            row_dict["last_visited"].isoformat()
                            if row_dict["last_visited"]
                            else None
                        ),
                    },
                }
                features.append(feature)

            return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")


@app.get("/api/visits")
def get_user_visits(
    user_id: Optional[str] = None,
    bbox: Optional[str] = None,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Returns the authenticated user's business-level visits (history).
    Optional bbox filter restricts results to a geographic envelope.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    target_user_id = user_id if user_id else current_user_id

    query_str = """
        SELECT v.id, v.cnpj, v.lat, v.lon, v.logradouro, v.bairro,
               v.notes, v.route_id, v.visited_at,
               ST_AsGeoJSON(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)) as geom_geojson
        FROM visits v
        WHERE v.user_id = :user_id
    """
    params: Dict[str, Any] = {"user_id": target_user_id}

    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) == 4:
                lng1, lat1, lng2, lat2 = map(float, parts)
                query_str += (
                    " AND ST_Intersects("
                    "ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326), "
                    "ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))"
                )
                params.update({"lng1": lng1, "lat1": lat1, "lng2": lng2, "lat2": lat2})
        except ValueError:
            pass

    try:
        with db_engine.connect() as conn:
            result = conn.execute(text(query_str), params)
            visits = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"])
                visits.append(
                    {
                        "id": row_dict["id"],
                        "cnpj": row_dict["cnpj"],
                        "lat": float(row_dict["lat"]),
                        "lon": float(row_dict["lon"]),
                        "logradouro": row_dict["logradouro"],
                        "bairro": row_dict["bairro"],
                        "notes": row_dict["notes"],
                        "route_id": str(row_dict["route_id"]) if row_dict["route_id"] else None,
                        "visited_at": row_dict["visited_at"].isoformat(),
                        "street_name": row_dict["logradouro"],
                        "geometry": geom,
                    }
                )
            return visits
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")


@app.post("/api/visits")
def create_visit(visit: VisitCreate, user_id: str = Depends(get_current_user_id)):
    """
    Record a new business/street visit. `visited_at` defaults to server NOW()
    if omitted. `street_coverage` is updated automatically via DB trigger.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    visited_at = None
    if visit.visited_at:
        try:
            visited_at = datetime.fromisoformat(visit.visited_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid visited_at timestamp format"
            )

    try:
        with db_engine.connect() as conn:
            query = text("""
                INSERT INTO visits (user_id, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
                VALUES (:user_id, :route_id, :cnpj, :lat, :lon, :logradouro, :bairro, :notes,
                        COALESCE(:visited_at, NOW()))
                RETURNING id
            """)
            result = conn.execute(
                query,
                {
                    "user_id": user_id,
                    "route_id": visit.route_id,
                    "cnpj": visit.cnpj,
                    "lat": visit.lat,
                    "lon": visit.lon,
                    "logradouro": visit.logradouro,
                    "bairro": visit.bairro,
                    "notes": visit.notes,
                    "visited_at": visited_at,
                },
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(
                    status_code=500, detail="Database did not return the visit ID"
                )
            visit_id = row[0]
            conn.commit()
            return {"status": "success", "visit_id": visit_id, "synced": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database insert failed: {e}"
        )


@app.post("/api/sync/visits")
def sync_visits(
    visits: List[VisitSyncItem], user_id: str = Depends(get_current_user_id)
):
    """
    Sync offline visits in batch. Each item becomes a new visit row (the new
    visits table records history rather than upserts). Exact-duplicate detection
    by (user_id, logradouro, lat, lon, visited_at) prevents repeat-sync issues.
    Returns the number of visits actually inserted.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    inserted_count = 0
    skipped_count = 0

    try:
        with db_engine.connect() as conn:
            for item in visits:
                try:
                    client_time = datetime.fromisoformat(
                        item.visited_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    skipped_count += 1
                    continue

                # Skip if an identical visit already exists (idempotent re-sync)
                dup_check = text("""
                    SELECT 1 FROM visits
                     WHERE user_id = :user_id
                       AND logradouro = :logradouro
                       AND lat = :lat
                       AND lon = :lon
                       AND visited_at = :visited_at
                    LIMIT 1
                """)
                existing = conn.execute(
                    dup_check,
                    {
                        "user_id": user_id,
                        "logradouro": item.logradouro,
                        "lat": item.lat,
                        "lon": item.lon,
                        "visited_at": client_time,
                    },
                ).fetchone()
                if existing:
                    skipped_count += 1
                    continue

                insert_query = text("""
                    INSERT INTO visits
                        (user_id, route_id, cnpj, lat, lon, logradouro, bairro, notes, visited_at)
                    VALUES
                        (:user_id, :route_id, :cnpj, :lat, :lon, :logradouro, :bairro, :notes, :visited_at)
                """)
                conn.execute(
                    insert_query,
                    {
                        "user_id": user_id,
                        "route_id": item.route_id,
                        "cnpj": item.cnpj,
                        "lat": item.lat,
                        "lon": item.lon,
                        "logradouro": item.logradouro,
                        "bairro": item.bairro,
                        "notes": item.notes,
                        "visited_at": client_time,
                    },
                )
                inserted_count += 1

            conn.commit()
            return {"synced": inserted_count, "skipped": skipped_count, "conflicts": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync process failed: {e}")


@app.post("/api/routes")
def create_route(route: RouteCreate, user_id: str = Depends(get_current_user_id)):
    """
    Creates a route by collecting the geometries of multiple street segments
    and merging them into a single track using PostGIS ST_LineMerge.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    if not route.segment_ids:
        raise HTTPException(
            status_code=400, detail="A route must contain at least one segment"
        )

    try:
        with db_engine.connect() as conn:
            # First collect the geometries of the segments and merge them
            from sqlalchemy import bindparam

            merge_query = text("""
                INSERT INTO routes (user_id, name, geom)
                VALUES (
                    :user_id, 
                    :name, 
                    (
                        SELECT ST_LineMerge(ST_Collect(geom))
                        FROM street_segments
                        WHERE id IN :segment_ids
                    )
                )
                RETURNING id, ST_AsGeoJSON(geom) as geom_geojson
            """).bindparams(bindparam("segment_ids", expanding=True))

            result = conn.execute(
                merge_query,
                {
                    "user_id": user_id,
                    "name": route.name,
                    "segment_ids": route.segment_ids,
                },
            )

            row = result.fetchone()
            if not row or not row[1]:
                raise HTTPException(
                    status_code=400,
                    detail="Could not construct route geometry. Make sure segment IDs exist.",
                )

            route_id, geom_json = row
            conn.commit()
            return {
                "status": "success",
                "route_id": str(route_id),
                "name": route.name,
                "geometry": json.loads(geom_json),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {e}")


# ==============================================================================
# STREET COVERAGE — aggregated per-street visit stats
# ==============================================================================
@app.get("/api/street-coverage")
def get_street_coverage(
    municipio: Optional[str] = None,
    only_unvisited: bool = False,
    limit: int = 200,
):
    """
    Returns aggregated street coverage rows ordered by least-recently-visited
    first (so the worker can pick the next street to walk).

    - `municipio` filters by municipality (default: all).
    - `only_unvisited=true` returns only streets with `last_visited IS NULL`.
    - `limit` caps the number of rows returned (default 200).
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    query_str = """
        SELECT id, logradouro, bairro, municipio, state, last_visited,
               visit_count, total_businesses, covered_businesses,
               ST_AsGeoJSON(geom) as geom_geojson, updated_at
        FROM street_coverage
        WHERE 1=1
    """
    params: Dict[str, Any] = {}
    if municipio:
        query_str += " AND municipio = :municipio"
        params["municipio"] = municipio
    if only_unvisited:
        query_str += " AND last_visited IS NULL"
    query_str += " ORDER BY last_visited ASC NULLS FIRST, covered_businesses ASC LIMIT :limit"
    params["limit"] = limit

    try:
        with db_engine.connect() as conn:
            result = conn.execute(text(query_str), params)
            rows = []
            for row in result:
                row_dict = dict(row._mapping)
                geom = json.loads(row_dict["geom_geojson"]) if row_dict["geom_geojson"] else None
                rows.append(
                    {
                        "id": row_dict["id"],
                        "logradouro": row_dict["logradouro"],
                        "bairro": row_dict["bairro"],
                        "municipio": row_dict["municipio"],
                        "state": row_dict["state"],
                        "last_visited": (
                            row_dict["last_visited"].isoformat()
                            if row_dict["last_visited"]
                            else None
                        ),
                        "visit_count": row_dict["visit_count"],
                        "total_businesses": row_dict["total_businesses"],
                        "covered_businesses": row_dict["covered_businesses"],
                        "geometry": geom,
                        "updated_at": (
                            row_dict["updated_at"].isoformat()
                            if row_dict["updated_at"]
                            else None
                        ),
                    }
                )
            return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Coverage query failed: {e}")


# ==============================================================================
# DAILY ROUTES - CRUD + BUSINESSES NEARBY
# ==============================================================================


@app.get("/api/daily-routes")
def list_daily_routes(user_id: str = Depends(get_current_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, day_of_week, streets,
                           created_at, updated_at
                    FROM daily_routes
                    WHERE user_id = :user_id
                    ORDER BY day_of_week NULLS LAST, created_at
                """),
                {"user_id": user_id},
            )
            routes = []
            for row in result:
                row_dict = dict(row._mapping)
                routes.append({
                    "id": str(row_dict["id"]),
                    "name": row_dict["name"],
                    "day_of_week": row_dict["day_of_week"],
                    "streets": row_dict["streets"] or [],
                    "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                    "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
                })
            return routes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list routes: {e}")


@app.post("/api/daily-routes")
def create_daily_route(
    route: DailyRouteCreate, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO daily_routes (user_id, name, day_of_week, streets)
                    VALUES (:user_id, :name, :day_of_week, :streets)
                    RETURNING id, name, day_of_week, streets, created_at
                """),
                {
                    "user_id": user_id,
                    "name": route.name.strip(),
                    "day_of_week": route.day_of_week or None,
                    "streets": route.streets,
                },
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Route creation failed")
            row_dict = dict(row._mapping)
            conn.commit()
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {e}")


@app.get("/api/daily-routes/{route_id}")
def get_daily_route(
    route_id: str, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, day_of_week, streets, created_at, updated_at
                    FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"route_id": route_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            row_dict = dict(row._mapping)
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get route: {e}")


@app.put("/api/daily-routes/{route_id}")
def update_daily_route(
    route_id: str,
    update: DailyRouteUpdate,
    user_id: str = Depends(get_current_user_id),
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            # Build dynamic SET clause
            set_parts = []
            params: Dict[str, Any] = {"route_id": route_id, "user_id": user_id}

            if update.name is not None:
                set_parts.append("name = :name")
                params["name"] = update.name.strip()
            if update.day_of_week is not None:
                set_parts.append("day_of_week = :day_of_week")
                params["day_of_week"] = update.day_of_week or None
            if update.streets is not None:
                set_parts.append("streets = :streets")
                params["streets"] = update.streets

            if not set_parts:
                raise HTTPException(status_code=400, detail="No fields to update")

            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            set_clause = ", ".join(set_parts)

            result = conn.execute(
                text(f"""
                    UPDATE daily_routes
                    SET {set_clause}
                    WHERE id = :route_id AND user_id = :user_id
                    RETURNING id, name, day_of_week, streets, updated_at
                """),
                params,
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            row_dict = dict(row._mapping)
            conn.commit()
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "day_of_week": row_dict["day_of_week"],
                "streets": row_dict["streets"] or [],
                "updated_at": row_dict["updated_at"].isoformat() if row_dict["updated_at"] else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update route: {e}")


@app.delete("/api/daily-routes/{route_id}")
def delete_daily_route(
    route_id: str, user_id: str = Depends(get_current_user_id)
):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    DELETE FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                    RETURNING id
                """),
                {"route_id": route_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            conn.commit()
            return {"status": "deleted", "route_id": route_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete route: {e}")


@app.get("/api/daily-routes/{route_id}/businesses")
def get_route_businesses(
    route_id: str,
    user_id: str = Depends(get_current_user_id),
    radius: int = 0,
    limit: int = 200,
):
    """
    Returns businesses (from estabelecimentos) whose logradouro matches
    any street in the route. If radius > 0 and street_segments have PostGIS
    geometries, also returns businesses within radius meters of the route.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    # 1. Fetch the route's streets
    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT streets FROM daily_routes
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"route_id": route_id, "user_id": user_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            streets = row[0] or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch route: {e}")

    if not streets:
        return {
            "type": "FeatureCollection",
            "features": [],
            "metadata": {"route_id": route_id, "total": 0},
        }

    # 2. Search estabelecimentos by street name
    features = []
    try:
        with db_engine.connect() as conn:
            # Build ILIKE conditions for each street
            conditions = " OR ".join(
                f"logradouro ILIKE :street_{i}" for i in range(len(streets))
            )
            params = {}
            for i, s in enumerate(streets):
                params[f"street_{i}"] = f"%{s.strip()}%"

            query = text(f"""
                SELECT
                    cnpj_completo, nome_fantasia, business_type,
                    cnae_fiscal, logradouro, numero, bairro, municipio,
                    latitude, longitude, porte_empresa
                FROM estabelecimentos
                WHERE ({conditions})
                  AND situacao_cadastral = 2
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY nome_fantasia
                LIMIT :limit
            """)
            params["limit"] = limit

            result = conn.execute(query, params)
            for row in result:
                row_dict = dict(row._mapping)
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [
                            float(row_dict["longitude"]),
                            float(row_dict["latitude"]),
                        ],
                    },
                    "properties": {
                        "cnpj": row_dict["cnpj_completo"],
                        "nome_fantasia": row_dict["nome_fantasia"] or "",
                        "business_type": row_dict["business_type"] or "",
                        "cnae": str(row_dict["cnae_fiscal"] or ""),
                        "logradouro": row_dict["logradouro"] or "",
                        "numero": row_dict["numero"] or "",
                        "bairro": row_dict["bairro"] or "",
                        "municipio": row_dict["municipio"] or "",
                        "porte_empresa": str(row_dict["porte_empresa"] or ""),
                    },
                })
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search businesses: {e}"
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "route_id": route_id,
            "routes": streets,
            "total": len(features),
        },
    }


# ── CITIES ENDPOINTS ──────────────────────────────────────

class City(BaseModel):
    id: int
    name: str
    state: str
    lat: float | None
    lon: float | None

class CityStats(BaseModel):
    id: int
    name: str
    state: str
    lat: float | None
    lon: float | None
    total_businesses: int


# ── INTELLIGENT ROUTE GENERATION MODELS ────────────────────
class RouteGenerateRequest(BaseModel):
    city_id: int
    max_lojas: int = 80
    min_days_without_visit: int = 30


class GeneratedStop(BaseModel):
    cnpj: str
    nome_fantasia: str
    cnae_label: str
    bairro: str
    logradouro: str
    lat: float
    lon: float
    days_since_visit: int
    priority: int


class RouteGenerateResponse(BaseModel):
    city: str
    total_candidates: int
    selected: int
    stops: list[GeneratedStop]


class RouteOptimizeRequest(BaseModel):
    stops: list[dict]


@app.get("/api/cities")
def get_cities():
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(text("SELECT id, name, state, lat, lon FROM cities ORDER BY id")).fetchall()
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch cities: {e}")

@app.get("/api/cities/{city_id}/stats")
def get_city_stats(city_id: int):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, name, state, lat, lon FROM cities WHERE id = :city_id"),
                {"city_id": city_id},
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="City not found")
            city = dict(row._mapping)
            count = conn.execute(
                text("SELECT COUNT(*) FROM estabelecimentos WHERE UPPER(municipio) = UPPER(:city_name) AND situacao_cadastral = 2 AND geom IS NOT NULL"),
                {"city_name": city["name"]},
            ).scalar()
            city["total_businesses"] = count
            return city
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch city stats: {e}")


# ==============================================================================
# CITY ROUTES CRUD
# ==============================================================================

@app.get("/api/cities/{city_id}/routes")
def list_city_routes(city_id: int, user_id: str = Depends(get_effective_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, city_id, created_at
                    FROM routes
                    WHERE city_id = :city_id AND user_id = :user_id
                    ORDER BY created_at DESC, name
                """),
                {"city_id": city_id, "user_id": user_id},
            )
            routes = []
            for row in result:
                row_dict = dict(row._mapping)
                stops_result = conn.execute(
                    text("""
                        SELECT id, stop_order, address, lat, lon, cep, display_name
                        FROM route_stops
                        WHERE route_id = :route_id
                        ORDER BY stop_order
                    """),
                    {"route_id": row_dict["id"]},
                )
                stops = [
                    {
                        "id": str(stop_row[0]),
                        "stop_order": stop_row[1],
                        "address": stop_row[2],
                        "lat": float(stop_row[3]),
                        "lon": float(stop_row[4]),
                        "cep": stop_row[5],
                        "display_name": stop_row[6],
                    }
                    for stop_row in stops_result
                ]
                routes.append(
                    {
                        "id": str(row_dict["id"]),
                        "name": row_dict["name"],
                        "city_id": row_dict["city_id"],
                        "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                        "stops": stops,
                    }
                )
            return routes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list city routes: {e}")


@app.post("/api/cities/{city_id}/routes")
def create_city_route(city_id: int, route: RouteCreate, user_id: str = Depends(get_effective_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    if route.city_id != city_id:
        raise HTTPException(status_code=400, detail="City mismatch")
    if not route.stops:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    try:
        with db_engine.connect() as conn:
            route_result = conn.execute(
                text("""
                    INSERT INTO routes (user_id, city_id, name)
                    VALUES (:user_id, :city_id, :name)
                    RETURNING id, created_at
                """),
                {"user_id": user_id, "city_id": city_id, "name": route.name.strip()},
            )
            created_row = route_result.fetchone()
            if not created_row:
                raise HTTPException(status_code=500, detail="Route creation failed")
            route_id = created_row[0]
            for index, stop in enumerate(route.stops, start=1):
                conn.execute(
                    text("""
                        INSERT INTO route_stops (route_id, stop_order, address, lat, lon, cep, display_name)
                        VALUES (:route_id, :stop_order, :address, :lat, :lon, :cep, :display_name)
                    """),
                    {
                        "route_id": route_id,
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    },
                )
            conn.commit()
            return {
                "id": str(route_id),
                "name": route.name.strip(),
                "city_id": city_id,
                "created_at": created_row[1].isoformat() if created_row[1] else None,
                "stops": [
                    {
                        "id": str(route_id),
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    }
                    for index, stop in enumerate(route.stops, start=1)
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create city route: {e}")


@app.get("/api/routes/{route_id}")
def get_route(route_id: str, user_id: str = Depends(get_effective_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT id, name, city_id, created_at
                    FROM routes
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"route_id": route_id, "user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Route not found")
            row_dict = dict(row._mapping)
            stops_result = conn.execute(
                text("""
                    SELECT id, stop_order, address, lat, lon, cep, display_name
                    FROM route_stops
                    WHERE route_id = :route_id
                    ORDER BY stop_order
                """),
                {"route_id": row_dict["id"]},
            )
            stops = [
                {
                    "id": str(stop_row[0]),
                    "stop_order": stop_row[1],
                    "address": stop_row[2],
                    "lat": float(stop_row[3]),
                    "lon": float(stop_row[4]),
                    "cep": stop_row[5],
                    "display_name": stop_row[6],
                }
                for stop_row in stops_result
            ]
            return {
                "id": str(row_dict["id"]),
                "name": row_dict["name"],
                "city_id": row_dict["city_id"],
                "created_at": row_dict["created_at"].isoformat() if row_dict["created_at"] else None,
                "stops": stops,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch route: {e}")


@app.put("/api/routes/{route_id}")
def update_route(route_id: str, route: RouteCreate, user_id: str = Depends(get_effective_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    if not route.name.strip():
        raise HTTPException(status_code=400, detail="Route name is required")
    if not route.stops:
        raise HTTPException(status_code=400, detail="At least one stop is required")

    try:
        with db_engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM routes WHERE id = :route_id AND user_id = :user_id"),
                {"route_id": route_id, "user_id": user_id},
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Route not found")
            conn.execute(
                text("""
                    UPDATE routes
                    SET name = :name, city_id = :city_id
                    WHERE id = :route_id AND user_id = :user_id
                """),
                {"name": route.name.strip(), "city_id": route.city_id, "route_id": route_id, "user_id": user_id},
            )
            conn.execute(text("DELETE FROM route_stops WHERE route_id = :route_id"), {"route_id": route_id})
            for index, stop in enumerate(route.stops, start=1):
                conn.execute(
                    text("""
                        INSERT INTO route_stops (route_id, stop_order, address, lat, lon, cep, display_name)
                        VALUES (:route_id, :stop_order, :address, :lat, :lon, :cep, :display_name)
                    """),
                    {
                        "route_id": route_id,
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    },
                )
            conn.commit()
            return {
                "id": route_id,
                "name": route.name.strip(),
                "city_id": route.city_id,
                "created_at": None,
                "stops": [
                    {
                        "id": str(route_id),
                        "stop_order": index,
                        "address": stop.address,
                        "lat": stop.lat,
                        "lon": stop.lon,
                        "cep": stop.cep,
                        "display_name": stop.display_name,
                    }
                    for index, stop in enumerate(route.stops, start=1)
                ],
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update route: {e}")


@app.delete("/api/routes/{route_id}")
def delete_route(route_id: str, user_id: str = Depends(get_effective_user_id)):
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM routes WHERE id = :route_id AND user_id = :user_id RETURNING id"),
                {"route_id": route_id, "user_id": user_id},
            )
            conn.commit()
            if result.fetchone() is None:
                raise HTTPException(status_code=404, detail="Route not found")
            return {"status": "deleted", "route_id": route_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete route: {e}")


# ==============================================================================
# BUSINESS STATUS (global per-loja flag: visited / client)
# ==============================================================================
class BusinessStatusUpdate(BaseModel):
    status: str  # "visited" o "client"


@app.patch("/api/businesses/{cnpj}/status")
def update_business_status(cnpj: str, body: BusinessStatusUpdate):
    if body.status not in ("visited", "client"):
        raise HTTPException(status_code=400, detail="Status must be 'visited' or 'client'")
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            # Verificar que la loja existe (el CNPJ se almacena en cnpj_completo)
            exists = conn.execute(
                text("SELECT cnpj_completo FROM estabelecimentos WHERE cnpj_completo = :cnpj"),
                {"cnpj": cnpj},
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Business not found")

            # Upsert en business_status (sin route_id por ahora, status global)
            conn.execute(
                text("""
                    INSERT INTO business_status (cnpj, status, updated_at)
                    VALUES (:cnpj, :status, NOW())
                    ON CONFLICT (cnpj) DO UPDATE SET status = :status, updated_at = NOW()
                """),
                {"cnpj": cnpj, "status": body.status},
            )
            conn.commit()
            return {"cnpj": cnpj, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update status: {e}")


@app.get("/api/businesses/status")
def get_businesses_status(cnpjs: str):
    """Get status for a comma-separated list of CNPJs."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    cnpj_list = [c.strip() for c in cnpjs.split(",") if c.strip()]
    if not cnpj_list:
        return []
    try:
        with db_engine.connect() as conn:
            placeholders = ", ".join(f":cnpj_{i}" for i in range(len(cnpj_list)))
            params = {f"cnpj_{i}": c for i, c in enumerate(cnpj_list)}
            rows = conn.execute(
                text(f"SELECT cnpj, status FROM business_status WHERE cnpj IN ({placeholders})"),
                params,
            ).fetchall()
            return {r[0]: r[1] for r in rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch statuses: {e}")


# ==============================================================================
# INTELLIGENT ROUTE GENERATION
# ==============================================================================
@app.post("/api/routes/generate", response_model=RouteGenerateResponse)
def generate_route(body: RouteGenerateRequest):
    """
    Generates an intelligent visiting route for a given city.

    Selects businesses that have not been visited in `min_days_without_visit`
    days (or never visited), orders them by days-since-visit descending, then
    applies a Python-side diversity filter so no more than 3 stops share the
    same street (logradouro), until `max_lojas` stops are selected.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    # 1. Resolve city name (404 if it doesn't exist)
    try:
        with db_engine.connect() as conn:
            city_row = conn.execute(
                text("SELECT name FROM cities WHERE id = :city_id"),
                {"city_id": body.city_id},
            ).fetchone()
            if not city_row:
                raise HTTPException(status_code=404, detail="City not found")
            city_name = city_row[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resolve city: {e}")

    # 2. Candidate businesses with days since last visit (fetch 2x for diversity)
    max_limit = body.max_lojas * 2
    select_query = text("""
        WITH candidate_businesses AS (
            SELECT
                e.cnpj_completo as cnpj,
                e.nome_fantasia,
                e.cnae_fiscal,
                e.bairro,
                e.logradouro,
                e.municipio,
                ST_Y(e.geom::geometry) as lat,
                ST_X(e.geom::geometry) as lon,
                COALESCE(
                    EXTRACT(DAY FROM NOW() - MAX(v.visited_at))::INTEGER,
                    999999
                ) as days_since_visit
            FROM estabelecimentos e
            LEFT JOIN visits v ON v.cnpj = e.cnpj_completo
            WHERE e.situacao_cadastral = 2
              AND e.geom IS NOT NULL
              AND e.municipio = :city_name
            GROUP BY e.cnpj_completo, e.nome_fantasia, e.cnae_fiscal,
                     e.bairro, e.logradouro, e.municipio, e.geom
            HAVING COALESCE(
                EXTRACT(DAY FROM NOW() - MAX(v.visited_at))::INTEGER,
                999999
            ) >= :min_days
        )
        SELECT * FROM candidate_businesses
        ORDER BY days_since_visit DESC
        LIMIT :max_limit
    """)

    try:
        with db_engine.connect() as conn:
            result = conn.execute(
                select_query,
                {
                    "city_name": city_name,
                    "min_days": body.min_days_without_visit,
                    "max_limit": max_limit,
                },
            )
            candidates = []
            for row in result:
                row_dict = dict(row._mapping)
                candidates.append(row_dict)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch candidate businesses: {e}"
        )

    total_candidates = len(candidates)

    # 3. Diversity filter: no more than 3 stops per logradouro (street coverage)
    street_counts: Dict[str, int] = {}
    stops: List[GeneratedStop] = []

    for row in candidates:
        if len(stops) >= body.max_lojas:
            break

        logradouro = (row.get("logradouro") or "").strip()
        # Apply per-street cap; empty logradouro is treated as its own bucket
        key = logradouro if logradouro else "<sem logradouro>"
        if street_counts.get(key, 0) >= 3:
            continue
        street_counts[key] = street_counts.get(key, 0) + 1

        days_since = int(row.get("days_since_visit") or 0)

        stops.append(
            GeneratedStop(
                cnpj=str(row.get("cnpj") or ""),
                nome_fantasia=fix_encoding(str(row.get("nome_fantasia") or "")),
                cnae_label=fix_encoding(cnae_to_category(row.get("cnae_fiscal"))),
                bairro=fix_encoding(str(row.get("bairro") or "")),
                logradouro=fix_encoding(logradouro),
                lat=float(row.get("lat") or 0.0),
                lon=float(row.get("lon") or 0.0),
                days_since_visit=days_since,
                # 4. priority = days_since_visit
                priority=days_since,
            )
        )

    print(
        f"Generated route for '{city_name}': {total_candidates} candidates, "
        f"{len(stops)} selected (max_lojas={body.max_lojas}, "
        f"min_days={body.min_days_without_visit})"
    )

    return RouteGenerateResponse(
        city=city_name,
        total_candidates=total_candidates,
        selected=len(stops),
        stops=stops,
    )


@app.get("/api/businesses/search")
def search_businesses(q: str, limit: int = 50):
    if len(q.strip()) < 3:
        raise HTTPException(status_code=400, detail="Mínimo 3 caracteres")
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT cnpj_completo, nome_fantasia, cnae_label, bairro,
                           logradouro, municipio,
                           ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
                    FROM estabelecimentos
                    WHERE situacao_cadastral = 2
                      AND geom IS NOT NULL
                      AND (
                        nome_fantasia ILIKE :q
                        OR cnpj_completo ILIKE :q
                        OR logradouro ILIKE :q
                      )
                    ORDER BY nome_fantasia
                    LIMIT :limit
                    """
                ),
                {"q": f"%{q.strip()}%", "limit": limit},
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "bairro": fix_encoding(r[3]),
                    "logradouro": fix_encoding(r[4]),
                    "municipio": fix_encoding(r[5]),
                    "lat": float(r[6]),
                    "lon": float(r[7]),
                }
                for r in rows
            ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


@app.get("/api/stats/summary")
def get_stats_summary():
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            total = conn.execute(
                text(
                    "SELECT COUNT(*) FROM estabelecimentos WHERE situacao_cadastral = 2 AND geom IS NOT NULL"
                )
            ).scalar() or 0
            visited = conn.execute(
                text("SELECT COUNT(DISTINCT cnpj) FROM visits")
            ).scalar() or 0
            clients = conn.execute(
                text("SELECT COUNT(*) FROM business_status WHERE status = 'client'")
            ).scalar() or 0

            city_rows = conn.execute(
                text(
                    """
                    SELECT c.id, c.name, c.state, c.lat, c.lon,
                        (SELECT COUNT(*) FROM estabelecimentos e
                         WHERE e.situacao_cadastral = 2 AND e.geom IS NOT NULL
                           AND e.municipio = c.name) as total,
                        (SELECT COUNT(DISTINCT v.cnpj) FROM visits v
                         JOIN estabelecimentos e ON e.cnpj_completo = v.cnpj
                         WHERE e.municipio = c.name) as visited
                    FROM cities c
                    ORDER BY c.name
                    """
                )
            ).fetchall()
            cities_stats = [
                {
                    "id": int(r[0]),
                    "name": r[1],
                    "state": r[2],
                    "lat": float(r[3]) if r[3] else 0,
                    "lon": float(r[4]) if r[4] else 0,
                    "total": int(r[5] or 0),
                    "visited": int(r[6] or 0),
                }
                for r in city_rows
            ]

            return {
                "total_businesses": int(total),
                "visited": int(visited),
                "clients": int(clients),
                "cities": cities_stats,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats failed: {e}")


@app.post("/api/routes/optimize")
def optimize_route(body: RouteOptimizeRequest):
    """Reordena stops por nearest neighbor para minimizar distancia."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    stops = body.stops
    if not stops:
        return {"stops": [], "total_distance_m": 0}

    ordered = [stops[0]]
    remaining = list(stops[1:])

    total_distance = 0
    while remaining:
        last = ordered[-1]
        best_idx = 0
        best_dist = float("inf")
        for i, s in enumerate(remaining):
            d = haversine_m(last["lat"], last["lon"], s["lat"], s["lon"])
            if d < best_dist:
                best_dist = d
                best_idx = i
        total_distance += best_dist
        ordered.append(remaining.pop(best_idx))

    if len(ordered) > 1:
        total_distance += haversine_m(
            ordered[-1]["lat"], ordered[-1]["lon"],
            ordered[0]["lat"], ordered[0]["lon"],
        )

    return {"stops": ordered, "total_distance_m": round(total_distance, 0)}


@app.get("/api/businesses/clients")
def get_clients(limit: int = 500):
    """Lista todos los clientes (business_status = 'client')."""
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT e.cnpj_completo, e.nome_fantasia, e.cnae_label, e.bairro,
                           e.logradouro, e.municipio,
                           ST_Y(e.geom::geometry) as lat, ST_X(e.geom::geometry) as lon
                    FROM business_status bs
                    JOIN estabelecimentos e ON e.cnpj_completo = bs.cnpj
                    WHERE bs.status = 'client'
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "bairro": fix_encoding(r[3]),
                    "logradouro": fix_encoding(r[4]),
                    "municipio": fix_encoding(r[5]),
                    "lat": float(r[6]),
                    "lon": float(r[7]),
                }
                for r in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed: {e}")


@app.get("/api/businesses/city-category")
def get_businesses_by_city_and_category(city: str, category: str = "pizza", limit: int = 50):
    """
    Busca establecimientos por ciudad (municipio) y categoría (ej. pizza/pizzería).
    Filtra los establecimientos activos (situacao_cadastral = 2).
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    try:
        with db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT cnpj_completo, nome_fantasia, cnae_label, cnae_fiscal_descricao,
                           bairro, logradouro, municipio,
                           ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
                    FROM estabelecimentos
                    WHERE situacao_cadastral = 2
                      AND geom IS NOT NULL
                      AND municipio ILIKE :city
                      AND (
                        nome_fantasia ILIKE :cat
                        OR cnae_fiscal_descricao ILIKE :cat
                        OR cnae_label ILIKE :cat
                      )
                    ORDER BY nome_fantasia
                    LIMIT :limit
                    """
                ),
                {
                    "city": f"%{city.strip()}%",
                    "cat": f"%{category.strip()}%",
                    "limit": limit
                },
            ).fetchall()
            return [
                {
                    "cnpj": r[0],
                    "nome_fantasia": fix_encoding(r[1]),
                    "cnae_label": fix_encoding(r[2]),
                    "cnae_fiscal_descricao": fix_encoding(r[3]),
                    "bairro": fix_encoding(r[4]),
                    "logradouro": fix_encoding(r[5]),
                    "municipio": fix_encoding(r[6]),
                    "lat": float(r[7]) if r[7] is not None else None,
                    "lon": float(r[8]) if r[8] is not None else None,
                }
                for r in rows
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query businesses: {e}")


# ==============================================================================
# MAIN METHOD
# ==============================================================================
if __name__ == "__main__":
    import uvicorn

    # Read config from environment variables
    port = int(os.environ.get("API_PORT", "8000"))
    host = os.environ.get("API_HOST", "0.0.0.0")
    print(f"Launching Rastreador CNPJ Backend API on http://{host}:{port}...")
    uvicorn.run("api:app", host=host, port=port, reload=True)
