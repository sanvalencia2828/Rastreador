-- street_tracking_schema.sql
-- Table definitions for streets, user visits and offline routes sync.

-- Enable PostGIS if not enabled (should be already enabled)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 1. Table for street segments
CREATE TABLE IF NOT EXISTS street_segments (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    length_m DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create spatial index
CREATE INDEX IF NOT EXISTS idx_street_segments_geom ON street_segments USING GIST(geom);

-- 2. Table for user visits
CREATE TABLE IF NOT EXISTS user_visits (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    segment_id INTEGER NOT NULL REFERENCES street_segments(id) ON DELETE CASCADE,
    visited BOOLEAN DEFAULT TRUE,
    visited_at TIMESTAMP NOT NULL,
    notes TEXT,
    source VARCHAR(50) DEFAULT 'mobile',
    synced BOOLEAN DEFAULT FALSE,
    UNIQUE(user_id, segment_id)
);

-- Create normal index
CREATE INDEX IF NOT EXISTS idx_user_visits_user_id ON user_visits(user_id);

-- 3. Table for saved routes
CREATE TABLE IF NOT EXISTS routes (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create spatial index
CREATE INDEX IF NOT EXISTS idx_routes_geom ON routes USING GIST(geom);

-- ==============================================================================
-- INSERT SEED DATA (Street Segments in Downtown Londrina for testing)
-- Centered around Hub 1: -51.1610, -23.3110
-- ==============================================================================
INSERT INTO street_segments (osm_id, name, geom, length_m)
VALUES 
(1001, 'Avenida Higienópolis - Section A', ST_GeomFromText('LINESTRING(-51.1630 -23.3150, -51.1610 -23.3120)', 4326), 400.0)
ON CONFLICT DO NOTHING;

INSERT INTO street_segments (osm_id, name, geom, length_m)
VALUES 
(1002, 'Rua Sergipe - Section B', ST_GeomFromText('LINESTRING(-51.1610 -23.3120, -51.1580 -23.3100)', 4326), 350.0)
ON CONFLICT DO NOTHING;

INSERT INTO street_segments (osm_id, name, geom, length_m)
VALUES 
(1003, 'Avenida Paraná - Section C', ST_GeomFromText('LINESTRING(-51.1610 -23.3100, -51.1610 -23.3130)', 4326), 300.0)
ON CONFLICT DO NOTHING;

INSERT INTO street_segments (osm_id, name, geom, length_m)
VALUES 
(1004, 'Rua Piauí - Section D', ST_GeomFromText('LINESTRING(-51.1630 -23.3130, -51.1580 -23.3130)', 4326), 500.0)
ON CONFLICT DO NOTHING;

-- Grant permissions (postgres is owner/superuser, but let's make sure)
GRANT ALL PRIVILEGES ON TABLE street_segments TO postgres;
GRANT ALL PRIVILEGES ON TABLE user_visits TO postgres;
GRANT ALL PRIVILEGES ON TABLE routes TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE street_segments_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE user_visits_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE routes_id_seq TO postgres;
