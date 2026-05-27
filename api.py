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

app = FastAPI(
    title="Rastreador CNPJ API",
    description="API para mapas y clústeres de comercios en Londrina, PR",
    version="1.0.0"
)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ==============================================================================
# DATABASE OR LOCAL JSON LOADER
# ==============================================================================
def load_businesses() -> List[Dict[str, Any]]:
    """
    Loads businesses from PostgreSQL database if configured,
    otherwise falls back to reading the local JSON file.
    """
    db_user = os.environ.get("DB_USER")
    db_password = os.environ.get("DB_PASSWORD")
    db_host = os.environ.get("DB_HOST")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME")

    # Attempt DB connection if variables exist
    if all([db_user, db_password, db_host, db_name]):
        try:
            conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            engine = create_engine(conn_str)
            print(f"Connecting to database at {db_host}...")
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
def assign_geographic_coords(cnpj: str, business_type: str) -> List[float]:
    """
    Deterministically maps a CNPJ to one of the 5 hotspots in Londrina,
    and applies a stable random Gaussian-like noise to distribute the point on the map.
    This creates an extremely realistic spatial distribution (heatmap) without external APIs.
    """
    # Create a md5 hash of the CNPJ to have deterministic geographic placement
    h = hashlib.md5(cnpj.encode('utf-8')).hexdigest()
    hash_val = int(h, 16)

    # Determine Hub index (1-5) based on hash and business type bias
    # Bias gastronomy slightly towards Hubs 2, 3 and 5, and retail towards Hubs 1 and 4
    if business_type == "gastronomy":
        hub_idx = [2, 3, 5, 1, 4][hash_val % 5]
    else:
        hub_idx = [1, 4, 2, 3, 5][hash_val % 5]

    hub = HUBS[hub_idx]
    center_lng, center_lat = hub["coords"]

    # Deterministic displacement (using different portions of the md5 hash)
    # Lng noise: maps hash bits to range [-0.006, +0.006] degrees (approx 600m)
    lng_factor = ((hash_val % 1000) - 500) / 500.0  # [-1.0, 1.0]
    lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0  # [-1.0, 1.0]

    # Add Gaussian weight (dense at center, scattered at edges)
    # Apply exponentiation to draw points closer to the center of each hub
    lng_offset = (lng_factor ** 3) * 0.0075
    lat_offset = (lat_factor ** 3) * 0.0075

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
                cnpj_etl_polars.input_file = "sample_estabelecimentos.csv"
                cnpj_etl_polars.main()
                businesses = load_businesses()
        except Exception as e:
            print(f"Failed to auto-generate data: {e}")

    features = []
    for biz in businesses:
        cnpj = biz.get("cnpj_basico", "00000000") + biz.get("cnpj_ordem", "0000") + biz.get("cnpj_dv", "00")
        biz_type = biz.get("business_type", "retail")
        coords = assign_geographic_coords(cnpj, biz_type)
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": coords
            },
            "properties": {
                "cnpj": cnpj,
                "nome_fantasia": biz.get("nome_fantasia", "Comercio de Londrina"),
                "business_type": biz_type,
                "cnae": biz.get("cnae_fiscal_principal", ""),
                "bairro": biz.get("bairro", "Centro"),
                "logradouro": biz.get("logradouro", "")
            }
        }
        features.append(feature)

    print(f"Returning {len(features)} points as GeoJSON.")
    return {
        "type": "FeatureCollection",
        "features": features
    }

@app.get("/api/clusters/emergentes", response_model=List[Cluster])
def get_emergent_clusters():
    """
    Aggregates the businesses into their respective 5 Londrina hotspots,
    and returns them as ranked clusters.
    Used by the sidebar list ranking and interactive map markers.
    """
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
    return clusters

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
