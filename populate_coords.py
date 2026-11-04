#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script para inicializar columnas ID, coordenadas y geom en 'londrina_businesses'
y poblarlas usando la lógica determinista del backend de api.py,
permitiendo que el script 'enriquecer_lojas.py' se ejecute correctamente.
"""

import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.services.geo import assign_geographic_coords, synthetic_coords_allowed  # noqa: E402


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

def main():
    if not synthetic_coords_allowed():
        sys.exit(
            "Este script escribe coordenadas INVENTADAS (hash del CNPJ) en latitude/longitude. "
            "Solo corre con ALLOW_SYNTHETIC_COORDS=1 y APP_ENV=development."
        )
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
        cursor.execute(
            "ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"ID ya existía o se maneja automáticamente: {e}")

    # 2. Añadir columnas de latitud y longitud si no existen
    print("Verificando/añadiendo columnas de coordenadas...")
    cursor.execute(
        "ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;"
    )
    cursor.execute(
        "ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;"
    )
    conn.commit()

    # 3. Habilitar extensión PostGIS (por si acaso) y agregar columna geométrica geom
    print("Asegurando extensión PostGIS...")
    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    conn.commit()

    print("Verificando/añadiendo columna geométrica geom...")
    try:
        cursor.execute(
            "ALTER TABLE londrina_businesses ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);"
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error al agregar columna geom: {e}")

    # 4. Obtener todos los registros para calcular y actualizar coordenadas (incluyendo municipio)
    cursor.execute(
        "SELECT id, cnpj_basico, cnpj_ordem, cnpj_dv, business_type, municipio FROM londrina_businesses;"
    )
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
        updates,
    )
    conn.commit()

    # Actualizar la columna 'geom' con las coordenadas calculadas
    cursor.execute(
        "UPDATE londrina_businesses SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;"
    )
    conn.commit()

    print(
        "¡Coordenadas y geometría geom cargadas correctamente en londrina_businesses!"
    )
    conn.close()


if __name__ == "__main__":
    main()
