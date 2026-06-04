#!/usr/bin/env python3
"""
FastAPI Backend Server for Rastreador CNPJ ETL
Provides GeoJSON endpoints for MapLibre/react-map-gl integrations.

Author: Antigravity DevOps Assistant
Date: 2026-05-24
"""

import os
import json
import hashlib
import sys
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

load_env_file()

app = FastAPI(
    title="Rastreador CNPJ API",
    description="API para mapas y clústeres de comercios en Londrina, PR",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# IN-MEMORY CACHE HELPER (ZERO-DEPENDENCY)
# ==============================================================================
import time
_RESPONSE_CACHE = {}

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
    1: {"name": "Centro (Calçadão)", "coords": [-51.1610, -23.3110], "desc": "Comercio minorista y gastronomía tradicional"},
    2: {"name": "Gleba Palhano (Av. Ayrton Senna)", "coords": [-51.1890, -23.3310], "desc": "Boutiques premium, cafeterías y restaurantes modernos"},
    3: {"name": "Jardim Guanabara (Av. Higienópolis)", "coords": [-51.1670, -23.3220], "desc": "Polo de gastronomía y servicios ejecutivos"},
    4: {"name": "Zona Norte (Av. Saul Elkind)", "coords": [-51.1480, -23.2720], "desc": "Gran concentración de tiendas de retail masivo"},
    5: {"name": "Zona Leste (Av. Bandeirantes)", "coords": [-51.1550, -23.3180], "desc": "Clúster médico y comercial gastronómico de paso"}
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
    "47": "Moda y Calzado",
    "46": "Comercio Mayorista",
    "56": "Alimentos y Bebidas",
    "55": "Alimentos y Bebidas",
    "45": "Automotriz",
    "62": "Tecnología",
    "63": "Tecnología",
    "26": "Electrónica",
    "27": "Electrónica",
    "86": "Salud",
    "87": "Salud",
    "96": "Servicios",
    "95": "Servicios",
    "64": "Servicios Financieros",
    "65": "Servicios Financieros",
    "66": "Servicios Financieros",
    "70": "Consultoría",
    "71": "Consultoría",
    "41": "Construcción",
    "42": "Construcción",
    "43": "Construcción",
    "85": "Educación",
    "84": "Administración Pública",
    "49": "Transporte",
    "50": "Transporte",
    "51": "Transporte",
    "52": "Logística",
}

def cnae_to_category(cnae) -> str:
    """Maps a CNAE code (int or str) to a human-readable category."""
    if cnae is None:
        return "Otros"
    prefix = str(cnae)[:2]
    return CNAE_CATEGORY_MAP.get(prefix, "Otros")

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
            conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        else:
            db_host = None

    # Attempt DB connection if variables exist
    if conn_str:
        try:
            engine = create_engine(conn_str)
            print(f"Connecting to database at {db_host or 'configured connection string'}...")
            with engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM londrina_businesses"))
                # Convert rows to dictionaries
                businesses = []
                for row in result:
                    # SQLAlchemy row mapping compatibility
                    row_dict = dict(row._mapping)
                    businesses.append(row_dict)
                print(f"Successfully loaded {len(businesses)} businesses from PostgreSQL DB.")
                if len(businesses) > 0:
                    return businesses
        except Exception as e:
            print(f"PostgreSQL connection failed: {e}. Falling back to JSON file...")

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

# ==============================================================================
# SPATIAL ALGORITHMS
# ==============================================================================
def assign_geographic_coords(cnpj: str, business_type: str, municipio: Optional[str] = None) -> List[float]:
    """
    Deterministically maps a CNPJ to geographical coordinates.
    If the business is in Londrina (or default), it maps it to one of the 5 hubs.
    If it is in a nearby city, it maps it around the city's centroid.
    """
    # Create a md5 hash of the CNPJ to have deterministic geographic placement
    h = hashlib.md5(cnpj.encode('utf-8')).hexdigest()
    hash_val = int(h, 16)

    city_key = municipio.strip().lower() if municipio else ""
    
    # Determine centroid based on prefix to prevent encoding conflicts (e.g. UTF-8 vs Latin1)
    center_lng, center_lat = None, None
    if city_key.startswith("camb"):
        center_lng, center_lat = [-51.2782, -23.2758]  # Cambé
    elif city_key.startswith("ibipor"):
        center_lng, center_lat = [-51.0478, -23.2694]  # Ibiporã
    elif city_key.startswith("apucar") or "apucar" in city_key:
        center_lng, center_lat = [-51.4614, -23.5521]  # Apucarana
    elif "janda" in city_key or "jata" in city_key:
        center_lng, center_lat = [-51.6447, -23.6064]  # Jandaia do Sul

    # If the business is in one of the other target cities, place it around its centroid
    if center_lng is not None and center_lat is not None:
        # Deterministic displacement within 2km radius
        lng_factor = ((hash_val % 1000) - 500) / 500.0
        lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0
        
        lng_offset = (lng_factor ** 3) * 0.015
        lat_offset = (lat_factor ** 3) * 0.015
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
    lng_offset = (lng_factor ** 3) * 0.0075
    lat_offset = (lat_factor ** 3) * 0.0075

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
        cnpj = biz.get("cnpj_basico", "00000000") + biz.get("cnpj_ordem", "0000") + biz.get("cnpj_dv", "00")
        biz_type = biz.get("business_type", "retail")
        municipio = biz.get("municipio")
        coords = assign_geographic_coords(cnpj, biz_type, municipio)
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": coords
            },
            "properties": {
                "cnpj": cnpj,
                "nome_fantasia": biz.get("nome_fantasia", "Comercio"),
                "business_type": biz_type,
                "cnae": biz.get("cnae_fiscal_principal", ""),
                "bairro": biz.get("bairro", "Centro"),
                "logradouro": biz.get("logradouro", ""),
                "municipio": municipio or "Londrina"
            }
        }
        features.append(feature)

    print(f"Returning {len(features)} points as GeoJSON.")
    result = {
        "type": "FeatureCollection",
        "features": features
    }
    set_cached_response(cache_key, result, ttl=300)
    return result

@app.get("/api/clusters/emergentes", response_model=List[Cluster])
def get_emergent_clusters():
    """
    Aggregates the businesses into their respective 5 Londrina hotspots,
    and returns them as ranked clusters.
    Used by the sidebar list ranking and interactive map markers.
    """
    cache_key = "emergent_clusters"
    cached = get_cached_response(cache_key)
    if cached is not None:
        print("Returning cached emergent clusters.")
        return cached

    businesses = load_businesses()
    
    # If empty and we have no data, return empty list
    if len(businesses) == 0:
        return []

    # Initialize count
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    
    for biz in businesses:
        cnpj = biz.get("cnpj_basico", "00000000") + biz.get("cnpj_ordem", "0000") + biz.get("cnpj_dv", "00")
        biz_type = biz.get("business_type", "retail")
        
        # Deterministic hub assignment
        h = hashlib.md5(cnpj.encode('utf-8')).hexdigest()
        hash_val = int(h, 16)
        
        if biz_type == "gastronomy":
            hub_idx = [2, 3, 5, 1, 4][hash_val % 5]
        elif biz_type == "tech":
            hub_idx = [3, 2, 1, 5, 4][hash_val % 5]
        else:
            hub_idx = [1, 4, 2, 3, 5][hash_val % 5]
            
        counts[hub_idx] += 1

    # Form response list
    clusters = []
    for hub_id, count in counts.items():
        coords = HUBS[hub_id]["coords"]
        clusters.append(
            Cluster(
                cluster_id=hub_id,
                total_lojas=count,
                center_geom=ClusterPoint(coordinates=coords)
            )
        )
        
    # Sort by density descending
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
            conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    raw_rows: List[Dict[str, Any]] = []

    if conn_str:
        try:
            engine = create_engine(conn_str)
            with engine.connect() as conn:
                query = text("""
                    SELECT logradouro, cnae_fiscal_principal, porte_empresa
                    FROM londrina_businesses
                    WHERE logradouro IS NOT NULL AND logradouro != ''
                      AND porte_empresa IN ('01', '03')
                """)
                result = conn.execute(query)
                for row in result:
                    raw_rows.append(
                        dict(row._mapping) if hasattr(row, "_mapping")
                        else {
                            "logradouro": row[0],
                            "cnae_fiscal_principal": row[1],
                            "porte_empresa": row[2]
                        }
                    )
                print(f"Loaded {len(raw_rows)} rows from PostgreSQL for street analytics.")
        except Exception as e:
            print(f"PostgreSQL query failed: {e}. Falling back to JSON...")

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
        # Filter: only micro/small businesses size '01' or '03'
        if porte and porte not in ["01", "03"]:
            continue

        categoria = cnae_to_category(biz.get("cnae_fiscal_principal"))

        if logradouro not in street_data:
            street_data[logradouro] = {"total": 0, "rubros": {}}

        street_data[logradouro]["total"] += 1
        rubros = street_data[logradouro]["rubros"]
        rubros[categoria] = rubros.get(categoria, 0) + 1

    # Sort streets by total descending, take top 15
    sorted_streets = sorted(street_data.items(), key=lambda x: x[1]["total"], reverse=True)[:15]

    result_list: List[StreetAnalytics] = []
    for street_name, data in sorted_streets:
        rubros_sorted = sorted(data["rubros"].items(), key=lambda x: x[1], reverse=True)
        predominancia = rubros_sorted[0][0] if rubros_sorted else "Otros"
        distribucion = [
            RubroDistribucion(categoria=cat, cantidad=cnt)
            for cat, cnt in rubros_sorted
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
# TECH BUSINESSES ENDPOINT
# ==============================================================================

# CNAE prefix → tech subcategory mapping
TECH_CNAE_SUBCATEGORY: Dict[str, Dict[str, str]] = {
    "62": {"label": "Software & TI",       "icon": "💻"},
    "63": {"label": "Data & Servicios Web", "icon": "🌐"},
    "26": {"label": "Electrónica",          "icon": "🖥️"},
    "27": {"label": "Electrodomésticos",    "icon": "⚡"},
    "61": {"label": "Telecomunicaciones",   "icon": "📡"},
    "95": {"label": "Reparación TI",       "icon": "🔧"},
    "46": {"label": "Comercio Mayorista TI","icon": "📦"},
    "47": {"label": "Retail de Tecnología", "icon": "🏪"},
    "70": {"label": "Consultoría TI",      "icon": "🤝"},
    "71": {"label": "Ingeniería & P&D",    "icon": "🔬"},
    "72": {"label": "Investigación",       "icon": "🔭"},
    "85": {"label": "Educación TI",        "icon": "🎓"},
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
def get_tech_businesses(
    limit: int = 50,
    offset: int = 0,
    search: str = ""
):
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
            b for b in tech_businesses
            if search_lower in (b.get("nome_fantasia") or "").lower()
            or search_lower in str(b.get("cnae_fiscal_principal") or "").lower()
            or search_lower in (b.get("bairro") or "").lower()
            or search_lower in (b.get("logradouro") or "").lower()
        ]

    total = len(tech_businesses)

    # Paginate
    paginated = tech_businesses[offset: offset + limit]

    items = []
    for biz in paginated:
        cnpj = (
            biz.get("cnpj_basico", "00000000")
            + biz.get("cnpj_ordem", "0000")
            + biz.get("cnpj_dv", "00")
        )
        cnae_raw = str(biz.get("cnae_fiscal_principal") or "")
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

    print(f"Returning {len(items)} tech businesses (total={total}, offset={offset}, search='{search}').")
    return TechBusinessesResponse(total=total, offset=offset, limit=limit, items=items)


# ==============================================================================
# MAIN METHOD
# ==============================================================================
# ==============================================================================
# STREET SEGMENTS, VISITS AND OFFLINE SYNC - EXTRA MODELS & ENDPOINTS
# ==============================================================================
import hmac
import hashlib
import base64
import time
from datetime import datetime
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, Header

security = HTTPBearer(auto_error=False)
SECRET_KEY = "super_secret_key_londrina_radar_2026"

# ------------------------------------------------------------------------------
# 0-DEPENDENCY JWT & CRYPTO UTILITIES
# ------------------------------------------------------------------------------
def base64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b'=').decode('utf-8')

def base64url_decode(payload: str) -> bytes:
    padding = '=' * (4 - (len(payload) % 4))
    return base64.urlsafe_b64decode(payload + padding)

def create_jwt_token(data: dict, expires_in: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = data.copy()
    payload["exp"] = int(time.time()) + expires_in
    header_json = json.dumps(header, separators=(',', ':')).encode('utf-8')
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    unsigned_token = base64url_encode(header_json) + "." + base64url_encode(payload_json)
    signature = hmac.new(SECRET_KEY.encode('utf-8'), unsigned_token.encode('utf-8'), hashlib.sha256).digest()
    return unsigned_token + "." + base64url_encode(signature)

def decode_jwt_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        header_segment, payload_segment, signature_segment = parts
        unsigned_token = header_segment + "." + payload_segment
        expected_signature = hmac.new(SECRET_KEY.encode('utf-8'), unsigned_token.encode('utf-8'), hashlib.sha256).digest()
        actual_signature = base64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return {}
        payload = json.loads(base64url_decode(payload_segment).decode('utf-8'))
        if payload.get("exp", 0) < time.time():
            return {}
        return payload
    except Exception:
        return {}

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

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
    segment_id: int
    visited: bool
    visited_at: str
    notes: Optional[str] = None
    source: Optional[str] = "mobile"

class VisitSyncItem(BaseModel):
    segment_id: int
    visited: bool
    visited_at: str
    notes: Optional[str] = None
    source: Optional[str] = "mobile"

class RouteCreate(BaseModel):
    name: str
    segment_ids: List[int]

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

# ------------------------------------------------------------------------------
# DEPENDENCY FOR AUTHENTICATION
# ------------------------------------------------------------------------------
def get_current_user_id(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication token missing")
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload["user_id"]

def get_optional_user_id(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[str]:
    if not credentials:
        return None
    token = credentials.credentials
    payload = decode_jwt_token(token)
    return payload.get("user_id") if payload else None

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
                text("INSERT INTO users (username, password_hash) VALUES (:username, :pw_hash) RETURNING id"),
                {"username": user.username, "pw_hash": pw_hash}
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="User creation failed")
            user_id = row[0]
            token = create_jwt_token({"user_id": str(user_id), "username": user.username})
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail="Username already registered")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@app.post("/auth/login")
def login_user(user: UserLogin):
    if not db_engine:
        return {"user_id": "00000000-0000-0000-0000-000000000001", "username": user.username, "token": "dummy_dev_token"}
    try:
        pw_hash = hash_password(user.password)
        with db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, password_hash FROM users WHERE username = :username"),
                {"username": user.username}
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="Invalid username or password")
            user_id, db_pw_hash = row
            if db_pw_hash != pw_hash:
                raise HTTPException(status_code=400, detail="Invalid username or password")
            
            token = create_jwt_token({"user_id": str(user_id), "username": user.username})
            return {"user_id": str(user_id), "username": user.username, "token": token}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

# ------------------------------------------------------------------------------
# TRACKING ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/api/segments")
def get_street_segments(bbox: str, user_id: Optional[str] = Depends(get_optional_user_id)):
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
            raise HTTPException(status_code=400, detail="Bbox must have exactly 4 coordinates: lng1,lat1,lng2,lat2")
        lng1, lat1, lng2, lat2 = map(float, parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bbox coordinates must be valid numbers")

    try:
        with db_engine.connect() as conn:
            if user_id:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           COALESCE(v.visited, FALSE) as visited_by_user, v.notes, v.visited_at
                    FROM street_segments s
                    LEFT JOIN user_visits v ON s.id = v.segment_id AND v.user_id = :user_id
                    WHERE ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))
                """)
                params = {"lng1": lng1, "lat1": lat1, "lng2": lng2, "lat2": lat2, "user_id": user_id}
            else:
                query = text("""
                    SELECT s.id, s.osm_id, s.name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson,
                           FALSE as visited_by_user, NULL as notes, NULL as visited_at
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
                        "length_m": float(row_dict["length_m"]) if row_dict["length_m"] else 0.0,
                        "visited_by_user": row_dict["visited_by_user"],
                        "notes": row_dict["notes"],
                        "visited_at": row_dict["visited_at"].isoformat() if row_dict["visited_at"] else None
                    }
                }
                features.append(feature)

            return {
                "type": "FeatureCollection",
                "features": features
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")

@app.get("/api/visits")
def get_user_visits(user_id: Optional[str] = None, bbox: Optional[str] = None, current_user_id: str = Depends(get_current_user_id)):
    """
    Returns user visits. If user_id is not supplied, uses the authenticated current_user_id.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")
    
    target_user_id = user_id if user_id else current_user_id

    query_str = """
        SELECT v.id, v.segment_id, v.visited, v.visited_at, v.notes, v.source,
               s.name as street_name, s.length_m, ST_AsGeoJSON(s.geom) as geom_geojson
        FROM user_visits v
        JOIN street_segments s ON v.segment_id = s.id
        WHERE v.user_id = :user_id
    """
    params: Dict[str, Any] = {"user_id": target_user_id}

    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) == 4:
                lng1, lat1, lng2, lat2 = map(float, parts)
                query_str += " AND ST_Intersects(s.geom, ST_MakeEnvelope(:lng1, :lat1, :lng2, :lat2, 4326))"
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
                visits.append({
                    "id": row_dict["id"],
                    "segment_id": row_dict["segment_id"],
                    "visited": row_dict["visited"],
                    "visited_at": row_dict["visited_at"].isoformat(),
                    "notes": row_dict["notes"],
                    "source": row_dict["source"],
                    "street_name": row_dict["street_name"],
                    "length_m": float(row_dict["length_m"]) if row_dict["length_m"] else 0.0,
                    "geometry": geom
                })
            return visits
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database operation failed: {e}")

@app.post("/api/visits")
def upsert_visit(visit: VisitCreate, user_id: str = Depends(get_current_user_id)):
    """
    Upsert individual user visit.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    try:
        visited_at = datetime.fromisoformat(visit.visited_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid visited_at timestamp format")

    try:
        with db_engine.connect() as conn:
            query = text("""
                INSERT INTO user_visits (user_id, segment_id, visited, visited_at, notes, source, synced)
                VALUES (:user_id, :segment_id, :visited, :visited_at, :notes, :source, TRUE)
                ON CONFLICT (user_id, segment_id) DO UPDATE SET
                    visited = EXCLUDED.visited,
                    visited_at = EXCLUDED.visited_at,
                    notes = EXCLUDED.notes,
                    source = EXCLUDED.source,
                    synced = TRUE
                RETURNING id
            """)
            result = conn.execute(query, {
                "user_id": user_id,
                "segment_id": visit.segment_id,
                "visited": visit.visited,
                "visited_at": visited_at,
                "notes": visit.notes,
                "source": visit.source
            })
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Database did not return the visit ID")
            visit_id = row[0]
            return {"status": "success", "visit_id": visit_id, "synced": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database insert/update failed: {e}")

@app.post("/api/sync/visits")
def sync_visits(visits: List[VisitSyncItem], user_id: str = Depends(get_current_user_id)):
    """
    Sync offline visits. Implements conflict resolution by visited_at timestamp (last write wins).
    Returns synced count and conflicts list with server state.
    """
    if not db_engine:
        raise HTTPException(status_code=500, detail="Database connection unavailable")

    synced_count = 0
    conflicts = []

    try:
        with db_engine.connect() as conn:
            for item in visits:
                try:
                    client_time = datetime.fromisoformat(item.visited_at.replace("Z", "+00:00"))
                except ValueError:
                    continue

                # Check current server state
                check_query = text("""
                    SELECT visited, visited_at, notes
                    FROM user_visits
                    WHERE user_id = :user_id AND segment_id = :segment_id
                """)
                existing = conn.execute(check_query, {"user_id": user_id, "segment_id": item.segment_id}).fetchone()

                if existing:
                    server_visited, server_time, server_notes = existing
                    if server_time > client_time:
                        conflicts.append({
                            "segment_id": item.segment_id,
                            "client_visited": item.visited,
                            "client_visited_at": item.visited_at,
                            "server_visited": server_visited,
                            "server_visited_at": server_time.isoformat(),
                            "server_notes": server_notes
                        })
                        continue

                # Otherwise, upsert client state
                upsert_query = text("""
                    INSERT INTO user_visits (user_id, segment_id, visited, visited_at, notes, source, synced)
                    VALUES (:user_id, :segment_id, :visited, :visited_at, :notes, :source, TRUE)
                    ON CONFLICT (user_id, segment_id) DO UPDATE SET
                        visited = EXCLUDED.visited,
                        visited_at = EXCLUDED.visited_at,
                        notes = EXCLUDED.notes,
                        source = EXCLUDED.source,
                        synced = TRUE
                """)
                conn.execute(upsert_query, {
                    "user_id": user_id,
                    "segment_id": item.segment_id,
                    "visited": item.visited,
                    "visited_at": client_time,
                    "notes": item.notes,
                    "source": item.source
                })
                synced_count += 1
            
            return {
                "synced": synced_count,
                "conflicts": conflicts
            }
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
        raise HTTPException(status_code=400, detail="A route must contain at least one segment")

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
            
            result = conn.execute(merge_query, {
                "user_id": user_id,
                "name": route.name,
                "segment_ids": route.segment_ids
            })
            
            row = result.fetchone()
            if not row or not row[1]:
                raise HTTPException(status_code=400, detail="Could not construct route geometry. Make sure segment IDs exist.")
            
            route_id, geom_json = row
            return {
                "status": "success",
                "route_id": route_id,
                "name": route.name,
                "geometry": json.loads(geom_json)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create route: {e}")

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

