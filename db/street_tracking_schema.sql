-- db/street_tracking_schema.sql
-- Table definitions for streets, user tracking visits, routes and density analysis.

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
    geom GEOMETRY(Geometry, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create spatial index
CREATE INDEX IF NOT EXISTS idx_routes_geom ON routes USING GIST(geom);

-- 4. Table for storing computed segment business densities
CREATE TABLE IF NOT EXISTS segment_density (
    segment_id INTEGER PRIMARY KEY REFERENCES street_segments(id) ON DELETE CASCADE,
    density DOUBLE PRECISION NOT NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for segment density joins
CREATE INDEX IF NOT EXISTS idx_segment_density_value ON segment_density(density);
