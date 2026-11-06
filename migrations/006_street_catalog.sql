-- Street catalog (Maringa) + time log. Same DDL as app/db/bootstrap.py STREETS_DDL (a test keeps them identical).
-- Needs PostGIS (street_segments.geom). Reference data comes from scripts/cargar_calles_db.py.
CREATE TABLE IF NOT EXISTS street_segments (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    length_m DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE street_segments ADD COLUMN IF NOT EXISTS municipio TEXT;
ALTER TABLE street_segments ADD COLUMN IF NOT EXISTS street_key TEXT;
CREATE INDEX IF NOT EXISTS idx_street_segments_geom ON street_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_street_segments_key ON street_segments(municipio, street_key);

CREATE TABLE IF NOT EXISTS street_catalog (
    id SERIAL PRIMARY KEY,
    municipio TEXT NOT NULL,
    street_key TEXT NOT NULL,
    osm_key TEXT,
    tipo TEXT,
    nombre TEXT NOT NULL,
    n_comercios_activos INTEGER NOT NULL DEFAULT 0,
    numero_min INTEGER,
    numero_max INTEGER,
    sin_numero INTEGER NOT NULL DEFAULT 0,
    ceps TEXT[] NOT NULL DEFAULT '{}',
    length_m DOUBLE PRECISION,
    pareado_pct INTEGER,
    spread_m DOUBLE PRECISION,
    match_type TEXT,
    estado TEXT NOT NULL,
    en_plan_automatico BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT street_catalog_key UNIQUE (municipio, street_key),
    CONSTRAINT street_catalog_estado_check CHECK (estado IN ('ok', 'calle_larga', 'ambigua', 'sin_geometria'))
);
CREATE INDEX IF NOT EXISTS idx_street_catalog_osm_key ON street_catalog(municipio, osm_key);

-- Measured minutes per street, derived from visits.visited_at of a route (approximation: includes walking and pauses).
CREATE TABLE IF NOT EXISTS street_time_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    route_id UUID NOT NULL,
    municipio TEXT NOT NULL,
    street_key TEXT NOT NULL,
    seconds INTEGER NOT NULL CHECK (seconds > 0),
    n_visitas INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT street_time_log_user_route_street UNIQUE (user_id, route_id, street_key)
);
-- The first draft was UNIQUE (route_id, street_key): two users sharing a route id would collide.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'street_time_log'::regclass
                 AND conname = 'street_time_log_route_street') THEN
        ALTER TABLE street_time_log DROP CONSTRAINT street_time_log_route_street;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'street_time_log'::regclass
                     AND conname = 'street_time_log_user_route_street') THEN
        ALTER TABLE street_time_log ADD CONSTRAINT street_time_log_user_route_street UNIQUE (user_id, route_id, street_key);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_street_time_log_user ON street_time_log(user_id, municipio, street_key);
