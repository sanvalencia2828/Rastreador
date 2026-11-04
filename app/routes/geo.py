"""Health, heatmap, clusters, street analytics and BR-369 corridor."""

import hashlib
import os
from typing import List, Dict, Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import db_engine
from app.core.security import is_dev_env
from app.core.cache import get_cached_response, set_cached_response
from app.schemas.analytics import (
    Cluster,
    ClusterPoint,
    RubroDistribucion,
    StreetAnalytics,
)
from app.services.business_loader import load_businesses
from app.services.geo import (
    BR369_CITIES,
    HUBS,
    assign_geographic_coords,
    cnae_to_category,
    format_cnpj,
)

router = APIRouter()


# ==============================================================================
# API ENDPOINTS
# ==============================================================================
@router.get("/health")
def health_check():
    """Health check endpoint for Docker container checks"""
    return {"status": "ok", "message": "Rastreador CNPJ backend is running"}


def synthetic_coords_allowed() -> bool:
    """Invented (hash-based) coordinates only with ALLOW_SYNTHETIC_COORDS=1, never outside development."""
    return os.getenv("ALLOW_SYNTHETIC_COORDS") == "1" and is_dev_env()


@router.get("/api/heatmap")
def get_heatmap_geojson():
    """
    Returns a GeoJSON FeatureCollection of businesses that have real coordinates.
    Businesses without them are skipped and counted in `omitted_no_coords`; with
    ALLOW_SYNTHETIC_COORDS=1 (development only) they get invented points marked synthetic=true.
    """
    allow_synthetic = synthetic_coords_allowed()
    cache_key = f"heatmap_geojson:{'synthetic' if allow_synthetic else 'real'}"
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
    omitted = 0
    for biz in businesses:
        cnpj = format_cnpj(biz)
        biz_type = biz.get("business_type", "retail")
        municipio = biz.get("municipio")

        lat = biz.get("latitude")
        lon = biz.get("longitude")
        synthetic = lat is None or lon is None
        if not synthetic:
            coords = [float(lon), float(lat)]
        elif allow_synthetic:
            coords = assign_geographic_coords(cnpj, biz_type, municipio)
        else:
            omitted += 1
            continue

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
                "synthetic": synthetic,
            },
        }
        features.append(feature)

    print(f"Returning {len(features)} points as GeoJSON ({omitted} omitted without real coordinates).")
    result = {
        "type": "FeatureCollection",
        "features": features,
        "omitted_no_coords": omitted,
        "synthetic_allowed": allow_synthetic,
    }
    if not features and omitted:
        result["note"] = (
            f"{omitted} businesses were loaded but none has real coordinates, so the map is empty. "
            "Geocode them (enriquecer_lojas.py / populate the latitude and longitude columns)."
        )
    set_cached_response(cache_key, result, ttl=300)
    return result


@router.get("/api/clusters/emergentes", response_model=List[Cluster])
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
    if db_engine:
        try:
            with db_engine.connect() as conn:
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


@router.get("/api/analytics/streets", response_model=List[StreetAnalytics])
def get_commercial_streets_analytics():
    """
    Returns the top 15 commercial streets in Londrina.
    Each street includes total business count, distribution by category (rubro),
    and the predominant category. Uses PostgreSQL when available, JSON fallback otherwise.
    """
    raw_rows: List[Dict[str, Any]] = []

    if db_engine:
        for table_name in ["estabelecimentos", "londrina_businesses"]:
            try:
                with db_engine.connect() as conn:
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


@router.get("/api/corridor/br369")
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
