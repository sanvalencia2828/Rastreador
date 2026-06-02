#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script para inicializar columnas ID, coordenadas y geom en 'londrina_businesses'
y poblarlas usando la lógica determinista del backend de api.py,
permitiendo que el script 'enriquecer_lojas.py' se ejecute correctamente.
"""

import os
import hashlib
import psycopg2

# Cargar variables de entorno del archivo .env
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
            print(f"Loaded environment variables from {dotenv_path}")
        except Exception as e:
            print(f"Warning: Could not read {dotenv_path}: {e}")

load_env_file()

# Configuración de hubs de Londrina del api.py
HUBS = {
    1: {"name": "Centro (Calçadão)", "coords": [-51.1610, -23.3110]},
    2: {"name": "Gleba Palhano (Av. Ayrton Senna)", "coords": [-51.1890, -23.3310]},
    3: {"name": "Jardim Guanabara (Av. Higienópolis)", "coords": [-51.1670, -23.3220]},
    4: {"name": "Zona Norte (Av. Saul Elkind)", "coords": [-51.1480, -23.2720]},
    5: {"name": "Zona Leste (Av. Bandeirantes)", "coords": [-51.1550, -23.3180]}
}

def assign_geographic_coords(cnpj: str, business_type: str, municipio: str = None) -> list:
    """Calcula deterministamente coordenadas a partir del CNPJ, tipo de negocio y ciudad."""
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

    # Si es una ciudad vecina, dispersar los puntos alrededor de su centroide
    if center_lng is not None and center_lat is not None:
        lng_factor = ((hash_val % 1000) - 500) / 500.0
        lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0
        
        lng_offset = (lng_factor ** 3) * 0.015
        lat_offset = (lat_factor ** 3) * 0.015
        return [center_lng + lng_offset, center_lat + lat_offset]

    # Por defecto: Hubs de Londrina
    if business_type == "gastronomy":
        hub_idx = [2, 3, 5, 1, 4][hash_val % 5]
    else:
        hub_idx = [1, 4, 2, 3, 5][hash_val % 5]

    hub = HUBS[hub_idx]
    center_lng, center_lat = hub["coords"]

    lng_factor = ((hash_val % 1000) - 500) / 500.0
    lat_factor = (((hash_val // 1000) % 1000) - 500) / 500.0

    lng_offset = (lng_factor ** 3) * 0.0075
    lat_offset = (lat_factor ** 3) * 0.0075

    return [center_lng + lng_offset, center_lat + lat_offset]

def main():
    db_user = os.environ.get("DB_USER", "postgres")
    db_password = os.environ.get("DB_PASSWORD", "postgres")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "londrina_comercio")

    conn_str = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    print(f"Conectando a {db_host}...")
    
    conn = psycopg2.connect(conn_str)
    cursor = conn.cursor()

    # 1. Preparar la tabla: Añadir columna serial ID si no existe
    print("Verificando/añadiendo columna ID...")
    try:
        cursor.execute("ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"ID ya existía o se maneja automáticamente: {e}")

    # 2. Añadir columnas de latitud y longitud si no existen
    print("Verificando/añadiendo columnas de coordenadas...")
    cursor.execute("ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;")
    cursor.execute("ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;")
    conn.commit()

    # 3. Habilitar extensión PostGIS (por si acaso) y agregar columna geométrica geom
    print("Asegurando extensión PostGIS...")
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    conn.commit()

    print("Verificando/añadiendo columna geométrica geom...")
    try:
        cursor.execute("ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error al agregar columna geom: {e}")

    # 4. Obtener todos los registros para calcular y actualizar coordenadas (incluyendo municipio)
    cursor.execute("SELECT id, cnpj_basico, cnpj_ordem, cnpj_dv, business_type, municipio FROM londrina_businesses;")
    rows = cursor.fetchall()
    print(f"Calculando coordenadas para {len(rows)} comercios...")

    updates = []
    for row in rows:
        row_id, cnpj_basico, cnpj_ordem, cnpj_dv, business_type, municipio = row
        # Reconstruir CNPJ completo de 14 dígitos
        cnpj_completo = f"{cnpj_basico or ''}{cnpj_ordem or ''}{cnpj_dv or ''}"
        if len(cnpj_completo) < 14:
            # Rellenar con ceros si falta algo
            cnpj_completo = cnpj_completo.zfill(14)
            
        lng, lat = assign_geographic_coords(cnpj_completo, business_type, municipio)
        updates.append((lat, lng, row_id))

    # 5. Guardar en base de datos
    print("Actualizando coordenadas y columna geométrica...")
    cursor.executemany(
        "UPDATE londrina_businesses SET latitude = %s, longitude = %s WHERE id = %s;",
        updates
    )
    conn.commit()

    # Actualizar la columna 'geom' con las coordenadas calculadas
    cursor.execute("UPDATE londrina_businesses SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
    conn.commit()

    print("¡Coordenadas y geometría geom cargadas correctamente en londrina_businesses!")
    conn.close()

if __name__ == "__main__":
    main()
