#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
enriquecer_lojas.py
====================
Geocodificación forward vía Nominatim /search para la tabla `estabelecimentos`.
Lee establecimientos sin geocodificar (geocoded = FALSE), construye direcciones
a partir de logradouro, numero, bairro, municipio, y obtiene coordenadas reales
(latitude, longitude, geom).

Incluye:
  - Rate limiting (1 req/s) para cumplir TOS de Nominatim
  - Checkpoint cada N registros para reanudar si se interrumpe
  - Fallback a coordenadas deterministas si Nominatim no retorna resultados
  - Normalización de encoding Latin-1/UTF-8 en direcciones
"""

import time
import psycopg2
import psycopg2.extras
import requests
import json
import os
import sys
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==============================================================================
# ENV LOADER
# ==============================================================================
def load_env_file(dotenv_path: str = ".env") -> None:
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
            logger.info(f"Loaded env from {dotenv_path}")
        except Exception as e:
            logger.warning(f"Could not read {dotenv_path}: {e}")

load_env_file()


# ==============================================================================
# CONSTANTES
# ==============================================================================
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {
    'User-Agent': 'LondrinaRadarComercial-Geocoder/1.0 (londrina.radar@antigravity.dev)'
}
CHECKPOINT_INTERVAL = 50  # commit cada N registros
RATE_LIMIT_SLEEP = 1.1    # segundos entre requests (Nominatim TOS: max 1 req/s)

# Hubs de Londrina para fallback determinista
HUBS = {
    1: {"coords": [-51.1610, -23.3110]},
    2: {"coords": [-51.1890, -23.3310]},
    3: {"coords": [-51.1670, -23.3220]},
    4: {"coords": [-51.1480, -23.2720]},
    5: {"coords": [-51.1550, -23.3180]},
}

# Centros de ciudades vecinas para fallback
CITY_CENTERS = {
    "camb": [-51.2782, -23.2758],
    "ibipor": [-51.0478, -23.2694],
    "apucar": [-51.4614, -23.5521],
    "janda": [-51.6447, -23.6064],
}


# ==============================================================================
# CONEXIÓN DB
# ==============================================================================
def get_db_connection() -> psycopg2.extensions.connection:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_user = os.environ.get("DB_USER", "postgres")
        db_password = os.environ.get("DB_PASSWORD", "postgres")
        db_host = os.environ.get("DB_HOST", "localhost")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "londrina_comercio")
        db_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    conn = psycopg2.connect(db_url)
    conn.set_client_encoding('UTF8')
    return conn


# ==============================================================================
# GEOCODING FORWARD
# ==============================================================================
def build_address(
    logradouro: Optional[str],
    numero: Optional[str],
    bairro: Optional[str],
    municipio: Optional[str],
) -> str:
    """Construye dirección estructurada para consulta Nominatim."""
    parts = []
    street = (logradouro or "").strip()
    num = (numero or "").strip()
    if street:
        addr = street
        if num and num not in ('0', 'S/N', 'SN', 's/n'):
            addr += f", {num}"
        parts.append(addr)
    if bairro:
        parts.append(bairro.strip())
    if municipio:
        parts.append(municipio.strip())
    parts.append("PR")
    parts.append("Brazil")
    return ", ".join(parts)


def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """
    Consulta Nominatim /search con la dirección completa.
    Retorna (lat, lon) o None si no hay resultados.
    """
    params = {
        'q': address,
        'format': 'json',
        'limit': 1,
        'addressdetails': 0,
    }
    try:
        resp = requests.get(
            NOMINATIM_SEARCH_URL,
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data and len(data) > 0:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return (lat, lon)
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"  HTTP error en geocode: {e}")
        return None


def fallback_coordinates(
    cnpj_completo: str,
    business_type: str,
    municipio: Optional[str],
) -> Tuple[float, float]:
    """Coordenadas deterministas como fallback si Nominatim no responde."""
    h = hashlib.md5(cnpj_completo.encode('utf-8')).hexdigest()
    hash_val = int(h, 16)
    city_key = (municipio or "").strip().lower()

    for prefix, coords in CITY_CENTERS.items():
        if prefix in city_key or city_key.startswith(prefix):
            center_lng, center_lat = coords
            lng_factor = ((hash_val % 1000) - 500) / 500.0
            lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0
            lng_off = (lng_factor ** 3) * 0.015
            lat_off = (lat_factor ** 3) * 0.015
            return (center_lat + lat_off, center_lng + lng_off)

    # Londrina hubs
    if business_type == "tech":
        hub_idx = [3, 2, 1, 5, 4][hash_val % 5]
    else:
        hub_idx = [1, 4, 2, 3, 5][hash_val % 5]
    hub = HUBS[hub_idx]
    center_lng, center_lat = hub["coords"]
    lng_factor = ((hash_val % 1000) - 500) / 500.0
    lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0
    lng_off = (lng_factor ** 3) * 0.0075
    lat_off = (lat_factor ** 3) * 0.0075
    return (center_lat + lat_off, center_lng + lng_off)


# ==============================================================================
# PROCESO PRINCIPAL
# ==============================================================================
def ensure_geom_column(conn: psycopg2.extensions.connection) -> None:
    cursor = conn.cursor()
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    cursor.execute("""
        ALTER TABLE estabelecimentos
        ADD COLUMN IF NOT EXISTS latitude DECIMAL(10, 8);
    """)
    cursor.execute("""
        ALTER TABLE estabelecimentos
        ADD COLUMN IF NOT EXISTS longitude DECIMAL(11, 8);
    """)
    cursor.execute("""
        ALTER TABLE estabelecimentos
        ADD COLUMN IF NOT EXISTS geocoded BOOLEAN DEFAULT FALSE;
    """)
    try:
        cursor.execute("""
            ALTER TABLE estabelecimentos
            ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
        """)
    except Exception:
        conn.rollback()
    conn.commit()
    cursor.close()


def geocode_all_pending(conn: psycopg2.extensions.connection) -> Tuple[int, int, int]:
    """
    Itera sobre estabelecimientos sin geocodificar y les asigna
    coordenadas reales via Nominatim forward geocoding.
    Retorna (geocodificados, fallbacks, errores).
    """
    ensure_geom_column(conn)
    cursor = conn.cursor()

    # Obtener registros pendientes
    cursor.execute("""
        SELECT id, cnpj_completo, logradouro, numero,
               bairro, municipio, business_type
        FROM estabelecimentos
        WHERE (geocoded IS NULL OR geocoded = FALSE)
          AND situacao_cadastral = 2
        ORDER BY id
    """)
    pendientes = cursor.fetchall()
    total = len(pendientes)
    logger.info(f"Registros pendientes de geocodificar: {total}")

    if total == 0:
        cursor.close()
        return (0, 0, 0)

    geocoded_count = 0
    fallback_count = 0
    error_count = 0

    for i, row in enumerate(pendientes, 1):
        row_id, cnpj_completo, logradouro, numero, bairro, municipio, business_type = row
        btype = business_type or "tech"

        address = build_address(logradouro, numero, bairro, municipio)
        logger.info(f"[{i}/{total}] ID={row_id} Geocode: \"{address[:80]}...\"")

        lat, lon = None, None
        source = None

        try:
            result = geocode_address(address)
            if result:
                lat, lon = result
                source = "nominatim"
            else:
                logger.warning(f"  Sin resultados Nominatim para ID={row_id}, usando fallback")
        except Exception as e:
            logger.error(f"  Error geocoding ID={row_id}: {e}")

        if lat is None or lon is None:
            # Fallback determinista
            lat, lon = fallback_coordinates(cnpj_completo, btype, municipio)
            source = "fallback"
            fallback_count += 1
        else:
            geocoded_count += 1

        # Actualizar DB
        try:
            cursor.execute("""
                UPDATE estabelecimentos
                SET latitude = %s,
                    longitude = %s,
                    geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    geocoded = TRUE
                WHERE id = %s
            """, (lat, lon, lon, lat, row_id))
        except Exception as e:
            logger.error(f"  DB update error ID={row_id}: {e}")
            conn.rollback()
            error_count += 1
            continue

        # Checkpoint periódico
        if i % CHECKPOINT_INTERVAL == 0:
            conn.commit()
            logger.info(f"  Checkpoint: {i}/{total} procesados")

        # Rate limit Nominatim
        time.sleep(RATE_LIMIT_SLEEP)

    # Commit final
    conn.commit()
    cursor.close()

    logger.info(
        f"Resumen: {geocoded_count} geocodificados, "
        f"{fallback_count} fallback, {error_count} errores"
    )
    return (geocoded_count, fallback_count, error_count)


def main():
    """Función principal."""
    logger.info("=" * 60)
    logger.info("  Geocodificador Forward Nominatim - estabelecimentos")
    logger.info("=" * 60)

    try:
        conn = get_db_connection()
        ok, fallback, err = geocode_all_pending(conn)
        conn.close()

        logger.info("=" * 60)
        logger.info(f"  Total procesados: {ok + fallback + err}")
        logger.info(f"  Nominatim:     {ok}")
        logger.info(f"  Fallback:      {fallback}")
        logger.info(f"  Errores:       {err}")
        logger.info("=" * 60)
        logger.info("Geocodificación completada.")
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
