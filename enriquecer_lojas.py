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
  - Direcciones sin resultado quedan pendientes y se reintentan hasta MAX_GEOCODE_ATTEMPTS
  - Normalización de encoding Latin-1/UTF-8 en direcciones
"""

import time
import psycopg2
import psycopg2.extras
import requests
import os
import sys
import logging

from cities import CITIES
from typing import Optional, Tuple

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
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
    "User-Agent": "LondrinaRadarComercial-Geocoder/1.0 (londrina.radar@antigravity.dev)"
}
GEOCODE_MUNICIPIOS = tuple(c.name for c in CITIES)
MAX_CONSECUTIVE_ERRORS = 5  # errores de red seguidos antes de abortar
# Requiere las columnas de migrations/008_geocode_attempts.sql. La API las crea al arrancar
# (app/db/bootstrap.py); si corres este script antes de desplegar la API, aplica ese archivo a mano.
MAX_GEOCODE_ATTEMPTS = 3
CHECKPOINT_INTERVAL = 50  # commit cada N registros
RATE_LIMIT_SLEEP = 1.1  # segundos entre requests (Nominatim TOS: max 1 req/s)

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
    conn.set_client_encoding("UTF8")
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
        if num and num not in ("0", "S/N", "SN", "s/n"):
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
    Retorna (lat, lon) o None si no hay resultados. Lanza excepción si falla la red/HTTP.
    """
    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "addressdetails": 0,
    }
    # Los errores de red/HTTP se propagan: el llamador los distingue de "sin resultados".
    resp = requests.get(
        NOMINATIM_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data and len(data) > 0:
        return (float(data[0]["lat"]), float(data[0]["lon"]))
    return None


class GeocodingAborted(RuntimeError):
    """Demasiados errores de red seguidos; no tiene sentido seguir."""


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
    Retorna (geocodificados, no_encontrados, errores).
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
          AND municipio = ANY(%s)
          AND COALESCE(geocode_attempts, 0) < %s
        ORDER BY id
    """, (list(GEOCODE_MUNICIPIOS), MAX_GEOCODE_ATTEMPTS))
    pendientes = cursor.fetchall()
    total = len(pendientes)
    logger.info(f"Registros pendientes de geocodificar: {total}")

    if total == 0:
        cursor.close()
        return (0, 0, 0)

    geocoded_count = 0
    not_found_count = 0
    error_count = 0
    consecutive_errors = 0

    for i, row in enumerate(pendientes, 1):
        row_id, cnpj_completo, logradouro, numero, bairro, municipio, business_type = (
            row
        )
        btype = business_type or "tech"

        address = build_address(logradouro, numero, bairro, municipio)
        logger.info(f'[{i}/{total}] ID={row_id} Geocode: "{address[:80]}..."')

        lat, lon = None, None
        source = None

        try:
            result = geocode_address(address)
            if result:
                lat, lon = result
                source = "nominatim"
            else:
                logger.warning(
                    f"  Dirección no encontrada en Nominatim para ID={row_id}; queda pendiente"
                )
        except Exception as e:
            # Error de red/HTTP: no es "no encontrado" y no consume un intento.
            error_count += 1
            consecutive_errors += 1
            logger.error(f"  Error geocoding ID={row_id}: {e}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                conn.commit()
                raise GeocodingAborted(
                    f"{consecutive_errors} errores de red seguidos (último: {e}); "
                    "abortando. Revisa la conexión y vuelve a correr."
                )
            time.sleep(RATE_LIMIT_SLEEP)
            continue
        consecutive_errors = 0

        if lat is None or lon is None:
            # Sin resultado real: no se escriben coords inventadas ni geocoded=TRUE;
            # se registra el intento y la fila se reintenta hasta MAX_GEOCODE_ATTEMPTS.
            not_found_count += 1
            try:
                cursor.execute(
                    """
                    UPDATE estabelecimentos
                    SET geocode_attempts = COALESCE(geocode_attempts, 0) + 1,
                        geocode_last_try = NOW()
                    WHERE id = %s
                """,
                    (row_id,),
                )
            except Exception as e:
                logger.error(f"  DB attempt update error ID={row_id}: {e}")
                conn.rollback()
                error_count += 1
            time.sleep(RATE_LIMIT_SLEEP)
            continue
        geocoded_count += 1

        # Actualizar DB
        try:
            cursor.execute(
                """
                UPDATE estabelecimentos
                SET latitude = %s,
                    longitude = %s,
                    geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    geocoded = TRUE
                WHERE id = %s
            """,
                (lat, lon, lon, lat, row_id),
            )
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
        f"{not_found_count} no encontrados, {error_count} errores"
    )
    return (geocoded_count, not_found_count, error_count)


def main():
    """Función principal."""
    logger.info("=" * 60)
    logger.info("  Geocodificador Forward Nominatim - estabelecimentos")
    logger.info("=" * 60)

    try:
        conn = get_db_connection()
        ok, not_found, err = geocode_all_pending(conn)
        conn.close()

        logger.info("=" * 60)
        logger.info(f"  Total procesados: {ok + not_found + err}")
        logger.info(f"  Nominatim:     {ok}")
        logger.info(f"  No encontrados: {not_found}")
        logger.info(f"  Errores:       {err}")
        logger.info("=" * 60)
        logger.info("Geocodificación completada.")
    except GeocodingAborted as e:
        logger.error(str(e))
        sys.exit(2)
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
