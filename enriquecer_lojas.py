#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script para enriquecer datos de locales comerciales con información geográfica jerárquica
y metadatos PostGIS. Incluye autodetección de tablas y 4 niveles de geocodificación.
"""

import time
import psycopg2
import requests
from typing import Optional, Dict, Any, Tuple
import json
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import os

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
            logger.info(f"Loaded environment variables from {dotenv_path}")
        except Exception as e:
            logger.warning(f"Could not read {dotenv_path}: {e}")

load_env_file()

# Configuración de Nominatim
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {
    'User-Agent': 'LondrinaComercio-Enricher/1.0 (londrina.comercio@antigravity.dev)'
}

def conectar_db() -> psycopg2.extensions.connection:
    """Establece conexión con la base de datos PostgreSQL"""
    db_url = os.environ.get("DATABASE_URL")
    try:
        if db_url:
            logger.info("Conectando a PostgreSQL usando DATABASE_URL...")
            conn = psycopg2.connect(db_url)
        else:
            db_user = os.environ.get("DB_USER")
            db_password = os.environ.get("DB_PASSWORD")
            db_host = os.environ.get("DB_HOST")
            db_port = os.environ.get("DB_PORT", "5432")
            db_name = os.environ.get("DB_NAME")

            if all([db_user, db_password, db_host, db_name]):
                conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
                logger.info(f"Conectando a PostgreSQL en {db_host} usando variables de entorno...")
                conn = psycopg2.connect(conn_str)
            else:
                logger.info("Conectando usando configuración local hardcoded...")
                db_config = {
                    'host': os.environ.get("DB_HOST", "localhost"),
                    'port': int(os.environ.get("DB_PORT", 5432)),
                    'database': os.environ.get("DB_NAME", "londrina_comercio"),
                    'user': os.environ.get("DB_USER", "postgres"),
                    'password': os.environ.get("DB_PASSWORD", "postgres")
                }
                conn = psycopg2.connect(**db_config)
        logger.info("Conexión a la base de datos establecida correctamente")
        return conn
    except Exception as e:
        logger.error(f"Error al conectar a la base de datos: {e}")
        raise

def autodetectar_tabla_lojas(conn: psycopg2.extensions.connection) -> str:
    """Autodetección de tabla que contiene datos de locales comerciales"""
    cursor = conn.cursor()

    # Prioridad: Buscar tablas conocidas de locales comerciales
    query_conocidas = """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_name IN ('londrina_businesses', 'estabelecimentos')
    AND table_schema = 'public'
    ORDER BY CASE table_name 
        WHEN 'londrina_businesses' THEN 1 
        WHEN 'estabelecimentos' THEN 2 
    END;
    """
    cursor.execute(query_conocidas)
    result = cursor.fetchone()
    if result:
        tabla = result[0]
        logger.info(f"Tabla de locales preferida detectada: {tabla}")
        return tabla

    # Buscar tablas que contengan columnas típicas de locales comerciales
    query = """
    SELECT table_name
    FROM information_schema.columns
    WHERE (column_name LIKE '%loja%' OR column_name LIKE '%local%' OR column_name LIKE '%comercio%')
    AND table_schema = 'public'
    GROUP BY table_name
    ORDER BY COUNT(*) DESC
    LIMIT 1;
    """

    cursor.execute(query)
    result = cursor.fetchone()

    if result:
        tabla = result[0]
        logger.info(f"Tabla de locales detectada automáticamente: {tabla}")
        return tabla

    # Si no encuentra por nombre, buscar por columnas de coordenadas
    query_coords = """
    SELECT table_name
    FROM information_schema.columns
    WHERE (column_name LIKE '%lat%' OR column_name LIKE '%latitude%' OR column_name = 'y')
    AND table_schema = 'public'
    INTERSECT
    SELECT table_name
    FROM information_schema.columns
    WHERE (column_name LIKE '%lon%' OR column_name LIKE '%longitude%' OR column_name = 'x')
    AND table_schema = 'public'
    LIMIT 1;
    """

    cursor.execute(query_coords)
    result = cursor.fetchone()

    if result:
        tabla = result[0]
        logger.info(f"Tabla de locales detectada por coordenadas: {tabla}")
        return tabla

    raise Exception("No se pudo autodetectar tabla de locales comerciales")

def obtener_metadatos_postgis(conn: psycopg2.extensions.connection, tabla: str) -> Dict[str, Any]:
    """Obtiene metadatos espaciales de la tabla usando funciones PostGIS"""
    cursor = conn.cursor()

    metadatos = {}

    # Obtener el SRID de la geometría
    try:
        cursor.execute(f"SELECT ST_SRID(geom) FROM {tabla} LIMIT 1;")
        srid_result = cursor.fetchone()
        metadatos['srid'] = srid_result[0] if srid_result else 4326
        logger.info(f"SRID detectado: {metadatos['srid']}")
    except:
        conn.rollback()
        metadatos['srid'] = 4326
        logger.warning("No se pudo obtener SRID, usando 4326 por defecto")

    # Obtener el tipo de geometría
    try:
        cursor.execute(f"SELECT GeometryType(geom) FROM {tabla} LIMIT 1;")
        geom_type_result = cursor.fetchone()
        metadatos['geometry_type'] = geom_type_result[0] if geom_type_result else 'POINT'
        logger.info(f"Tipo de geometría: {metadatos['geometry_type']}")
    except:
        conn.rollback()
        metadatos['geometry_type'] = 'POINT'
        logger.warning("No se pudo obtener tipo de geometría, usando POINT por defecto")

    # Obtener el extent de la tabla
    try:
        cursor.execute(f"SELECT ST_Extent(geom) FROM {tabla};")
        extent_result = cursor.fetchone()
        metadatos['extent'] = extent_result[0] if extent_result else None
        logger.info("Extent de la tabla obtenido")
    except:
        conn.rollback()
        metadatos['extent'] = None
        logger.warning("No se pudo obtener el extent de la tabla")

    return metadatos

def geocodificar_completo(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Realiza una única consulta a Nominatim a zoom 18 y calcula
    los niveles 2, 3 y 4 localmente en memoria.
    """
    params = {
        'lat': lat,
        'lon': lon,
        'format': 'json',
        'addressdetails': 1,
        'zoom': 18
    }

    try:
        response = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        resultado = {
            'direccion': data.get('display_name', ''),
            'tipo_lugar': data.get('type', ''),
            'categoria': data.get('category', ''),
            'importance': data.get('importance', 0)
        }

        # Extraer componentes de dirección
        address = data.get('address', {})
        resultado.update({
            'calle': address.get('road', ''),
            'numero': address.get('house_number', ''),
            'codigo_postal': address.get('postcode', ''),
            'barrio': address.get('suburb', address.get('neighbourhood', '')),
            'ciudad': address.get('city', address.get('town', '')),
            'estado': address.get('state', ''),
            'pais': address.get('country', ''),
            # Nivel 2
            'distrito': address.get('district', ''),
            'municipio': address.get('county', ''),
            'region': address.get('state_district', ''),
            'zona_comercial': '',
            'area_metropolitana': '',
            # Nivel 3
            'macrozona': '',
            'cuadrante': '',
            'corredor_principal': '',
            'polo_desarrollo': '',
            # Nivel 4
            'microregion': address.get('county', ''),
            'mesoregion': address.get('state_district', ''),
            'region_economica': '',
            'cluster_economico': '',
            'densidad_comercial': ''
        })

        # --- Lógica de Nivel 2 ---
        ciudad = address.get('city', address.get('town', '')).lower()
        if 'londrina' in ciudad:
            if lat > -23.3:
                resultado['zona_comercial'] = 'Zona Norte'
            elif lat < -23.32:
                resultado['zona_comercial'] = 'Zona Sul'
            else:
                resultado['zona_comercial'] = 'Centro'
            resultado['area_metropolitana'] = 'Região Metropolitana de Londrina'

        # --- Lógica de Nivel 3 ---
        # Centro de Londrina aproximadamente: -23.31, -51.16
        if -23.30 <= lat <= -23.29 and -51.17 <= lon <= -51.15:
            resultado['macrozona'] = 'Centro Histórico'
            resultado['cuadrante'] = 'Centro'
        elif -23.29 <= lat <= -23.27 and -51.15 <= lon <= -51.13:
            resultado['macrozona'] = 'Zona Nova'
            resultado['cuadrante'] = 'Noreste'
        elif -23.32 <= lat <= -23.30 and -51.18 <= lon <= -51.16:
            resultado['macrozona'] = 'Zona Oeste'
            resultado['cuadrante'] = 'Sudoeste'
        elif -23.34 <= lat <= -23.32 and -51.15 <= lon <= -51.13:
            resultado['macrozona'] = 'Zona Sul'
            resultado['cuadrante'] = 'Sureste'
        else:
            resultado['macrozona'] = 'Zona Periférica'
            resultado['cuadrante'] = 'Exterior'

        # Corredor principal
        if -51.17 <= lon <= -51.15:
            resultado['corredor_principal'] = 'Av. Brasil'
        elif -51.16 <= lon <= -51.14:
            resultado['corredor_principal'] = 'Av. Londrina'
        elif -23.32 <= lat <= -23.30:
            resultado['corredor_principal'] = 'Av. Paulista'
        else:
            resultado['corredor_principal'] = 'Otros corredores'

        # --- Lógica de Nivel 4 ---
        estado = address.get('state', '').lower()
        if 'paraná' in estado or 'parana' in estado:
            resultado['region_economica'] = 'Núcleo Norte Paranaense'
            resultado['cluster_economico'] = 'Área Metropolitana de Londrina'

            # Determinar densidad comercial
            if -23.32 <= lat <= -23.29 and -51.18 <= lon <= -51.14:
                resultado['densidad_comercial'] = 'Alta'
            elif -23.35 <= lat <= -23.27 and -51.20 <= lon <= -51.12:
                resultado['densidad_comercial'] = 'Media'
            else:
                resultado['densidad_comercial'] = 'Baja'

        logger.info(f"Geocodificación completa realizada para {lat}, {lon}")
        return resultado
    except Exception as e:
        logger.error(f"Error en geocodificación completa: {e}")
        return None

def procesar_locales(conn: psycopg2.extensions.connection, tabla: str) -> None:
    """Procesa todos los locales comerciales y enriquece sus datos"""
    cursor = conn.cursor()

    # Actualizar tabla con nueva columna si no existe
    try:
        cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS datos_enriquecidos JSONB;")
        cursor.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS enriquecido BOOLEAN DEFAULT FALSE;")
        conn.commit()
        logger.info("Columnas de enriquecimiento creadas o verificadas")
    except Exception as e:
        logger.error(f"Error al crear columnas de enriquecimiento: {e}")
        conn.rollback()

    # Obtener todos los locales sin datos enriquecidos
    query = f"""
    SELECT id, ST_Y(geom) as lat, ST_X(geom) as lon
    FROM {tabla}
    WHERE enriquecido IS NULL OR enriquecido = FALSE
    ORDER BY id;
    """

    cursor.execute(query)
    locales = cursor.fetchall()

    logger.info(f"Procesando {len(locales)} locales comerciales...")

    locales_procesados = 0

    for local_id, lat, lon in locales:
        try:
            logger.info(f"Procesando local ID {local_id} ({lat}, {lon})")

            # Obtener datos usando la función de geocodificación única optimizada
            datos_combinados = geocodificar_completo(lat, lon)
            time.sleep(1.1)  # Respetar límites de rate de Nominatim (1 request por segundo)

            # Guardar en la base de datos
            if datos_combinados:
                cursor.execute(
                    f"UPDATE {tabla} SET datos_enriquecidos = %s, enriquecido = TRUE WHERE id = %s",
                    (json.dumps(datos_combinados, ensure_ascii=False), local_id)
                )
                conn.commit()
                logger.info(f"Local ID {local_id} enriquecido correctamente")
                locales_procesados += 1
            else:
                logger.warning(f"No se pudieron obtener datos para el local ID {local_id}")

        except Exception as e:
            logger.error(f"Error al procesar local ID {local_id}: {e}")
            conn.rollback()

    logger.info(f"Proceso completado. {locales_procesados} locales procesados exitosamente.")

def main():
    """Función principal"""
    try:
        # Conectar a la base de datos
        conn = conectar_db()

        # Autodetectar tabla de locales
        tabla_locales = autodetectar_tabla_lojas(conn)

        # Obtener metadatos PostGIS
        metadatos = obtener_metadatos_postgis(conn, tabla_locales)
        logger.info(f"Metadatos PostGIS: {metadatos}")

        # Procesar locales
        procesar_locales(conn, tabla_locales)

        # Cerrar conexión
        conn.close()
        logger.info("Proceso de enriquecimiento finalizado correctamente")

    except Exception as e:
        logger.error(f"Error en el proceso principal: {e}")
        raise

if __name__ == "__main__":
    main()