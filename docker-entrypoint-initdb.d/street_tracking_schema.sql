-- street_tracking_schema.sql
-- Street segments, route-based business visits and street coverage tracking.
--
-- Reconciliation note (2026-07):
--   The old `user_visits` (segment-level upserts) and `routes` (SERIAL id)
--   tables have been replaced by:
--     - `routes`        : UUID id (consistent with daily_routes in init.sql)
--     - `visits`        : business/CNPJ-level visit history with GPS coords
--     - `street_coverage`: aggregated coverage per street + municipality
--   `street_segments` is kept for OSM-based map rendering. The seed data
--   for downtown Londrina street segments is preserved below.

-- Enable PostGIS if not enabled (should be already enabled)
CREATE EXTENSION IF NOT EXISTS postgis;

-- ==============================================================================
-- 1. STREET SEGMENTS (OSM-derived, for map rendering / route building)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS street_segments (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    length_m DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_street_segments_geom ON street_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_street_segments_name ON street_segments(name);

-- ==============================================================================
-- 2. ROUTES (saved tracks assembled from street segments)
--    UUID id to match daily_routes convention and the visits.route_id FK.
-- ==============================================================================
-- Drop the legacy tables if they exist (safe on fresh DBs).
-- Order matters: visits (FK -> routes) first, then routes, then user_visits.
DROP TABLE IF EXISTS visits;
DROP TABLE IF EXISTS routes;
DROP TABLE IF EXISTS user_visits;

CREATE TABLE IF NOT EXISTS routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    city_id INTEGER REFERENCES cities(id),
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    start_lat NUMERIC(10,7),
    start_lng NUMERIC(10,7),
    status VARCHAR(20) NOT NULL DEFAULT 'planned',
    planned_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    completed_date DATE,
    total_stops_planned INTEGER NOT NULL DEFAULT 0,
    total_stops_done INTEGER NOT NULL DEFAULT 0,
    total_distance_km DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_duration_min DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE routes ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);
ALTER TABLE routes ADD COLUMN IF NOT EXISTS start_lat NUMERIC(10,7);
ALTER TABLE routes ADD COLUMN IF NOT EXISTS start_lng NUMERIC(10,7);
ALTER TABLE routes ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'planned';
ALTER TABLE routes ADD COLUMN IF NOT EXISTS planned_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE routes ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS completed_date DATE;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_stops_planned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_stops_done INTEGER NOT NULL DEFAULT 0;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_distance_km DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_duration_min DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS notes TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'routes_status_check'
    ) THEN
        ALTER TABLE routes ADD CONSTRAINT routes_status_check
            CHECK (status IN ('planned', 'active', 'completed', 'cancelled'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_routes_geom ON routes USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_routes_user_id ON routes(user_id);
CREATE INDEX IF NOT EXISTS idx_routes_status ON routes(status);
CREATE INDEX IF NOT EXISTS idx_routes_planned_at ON routes(planned_at DESC);

-- ==============================================================================
-- 3. VISITS (individual business-level visits with GPS coords + history)
--    Replaces the old `user_visits` segment-level table.
--    `user_id` is stored directly for efficient per-user queries without
--    requiring a route join (route_id is optional / nullable).
-- ==============================================================================
CREATE TABLE IF NOT EXISTS visits (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    route_id UUID REFERENCES routes(id) ON DELETE CASCADE,
    cnpj VARCHAR(20),                       -- CNPJ of the visited business (nullable: street walk-by)
    lat NUMERIC(10,7) NOT NULL,
    lon NUMERIC(10,7) NOT NULL,
    logradouro TEXT NOT NULL,
    bairro TEXT,
    notes TEXT,                             -- free-form field observations (preserved from user_visits)
    source VARCHAR(50) DEFAULT 'mobile',
    visited_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE visits ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mobile';

CREATE INDEX IF NOT EXISTS idx_visits_user ON visits(user_id);
CREATE INDEX IF NOT EXISTS idx_visits_cnpj ON visits(cnpj);
CREATE INDEX IF NOT EXISTS idx_visits_route ON visits(route_id);
CREATE INDEX IF NOT EXISTS idx_visits_logradouro ON visits(logradouro);
CREATE INDEX IF NOT EXISTS idx_visits_time ON visits(visited_at DESC);

CREATE TABLE IF NOT EXISTS route_stops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    business_id INTEGER REFERENCES estabelecimentos(id),
    stop_order INTEGER NOT NULL,
    visited BOOLEAN NOT NULL DEFAULT FALSE,
    visited_at TIMESTAMPTZ,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,
    skip_reason TEXT,
    notes TEXT,
    address TEXT NOT NULL DEFAULT '',
    lat NUMERIC(10,7) NOT NULL DEFAULT 0,
    lon NUMERIC(10,7) NOT NULL DEFAULT 0,
    cep VARCHAR(10),
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES estabelecimentos(id);
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS visited BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS visited_at TIMESTAMPTZ;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS skip_reason TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_route_stops_business ON route_stops(business_id);
CREATE INDEX IF NOT EXISTS idx_route_stops_route_order ON route_stops(route_id, stop_order);

-- ==============================================================================
-- 3b. BUSINESS STATUS (global per-business status: new / visited / client)
--     Decoupled from visits history so a loja can be flagged as "client"
--     without depending on a route. cnpj is the PK so ON CONFLICT (cnpj)
--     upserts work. route_id is optional for future route-scoped status.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS business_status (
    cnpj       VARCHAR(20) PRIMARY KEY,
    status     VARCHAR(10) NOT NULL DEFAULT 'new',
    route_id   UUID REFERENCES routes(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (status IN ('new', 'visited', 'client'))
);

CREATE INDEX IF NOT EXISTS idx_business_status_status ON business_status(status);

-- Trigger to keep updated_at fresh on business_status
DROP TRIGGER IF EXISTS update_business_status_updated_at ON business_status;
CREATE TRIGGER update_business_status_updated_at
    BEFORE UPDATE ON business_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- 4. STREET COVERAGE (aggregated per street + municipality)
--    Automatically maintained by the `update_street_coverage()` trigger below.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS street_coverage (
    id SERIAL PRIMARY KEY,
    logradouro TEXT NOT NULL,
    bairro TEXT,
    municipio TEXT NOT NULL,
    state VARCHAR(2) NOT NULL DEFAULT 'PR',
    last_visited TIMESTAMPTZ,
    visit_count INTEGER DEFAULT 0,
    total_businesses INTEGER DEFAULT 0,
    covered_businesses INTEGER DEFAULT 0,
    geom GEOMETRY(Point, 4326),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(logradouro, municipio)
);

CREATE INDEX IF NOT EXISTS idx_street_coverage_municipio ON street_coverage(municipio);
CREATE INDEX IF NOT EXISTS idx_street_coverage_last_visited ON street_coverage(last_visited);
CREATE INDEX IF NOT EXISTS idx_street_coverage_geom ON street_coverage USING GIST(geom);

-- Trigger to keep updated_at fresh on street_coverage
DROP TRIGGER IF EXISTS update_street_coverage_updated_at ON street_coverage;
CREATE TRIGGER update_street_coverage_updated_at
    BEFORE UPDATE ON street_coverage
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- 5. TRIGGER: auto-update street_coverage on every visit INSERT
--    Looks up the business municipality/bairro from `estabelecimentos` (if the
--    CNPJ is known) and recomputes all aggregate counters for that street so
--    the coverage row stays consistent even on repeated visits.
-- ==============================================================================
CREATE OR REPLACE FUNCTION update_street_coverage()
RETURNS TRIGGER AS $$
DECLARE
    biz_municipio TEXT;
    biz_bairro    TEXT;
    total_count   INTEGER;
    covered_count INTEGER;
    centroid      GEOMETRY;
    latest_visit  TIMESTAMPTZ;
    total_visits  INTEGER;
BEGIN
    -- No default city: the municipality must come from the establishment record.
    biz_municipio := NULL;
    biz_bairro    := NEW.bairro;

    IF NEW.cnpj IS NOT NULL THEN
        -- Receita dumps carry only the municipality CODE (Maringa = 7691), not a name, so that
        -- code decides; any other city keeps using estabelecimentos.municipio as before.
        SELECT CASE WHEN codigo_municipio = 7691 THEN 'MARINGA' ELSE municipio END, bairro
          INTO biz_municipio, biz_bairro
          FROM estabelecimentos
         WHERE cnpj_completo = NEW.cnpj
         LIMIT 1;
        IF biz_bairro IS NULL THEN
            biz_bairro := NEW.bairro;
        END IF;
    END IF;

    -- Unresolvable municipality (street walk-by without CNPJ, or CNPJ not loaded): no coverage row.
    IF biz_municipio IS NULL THEN
        RETURN NEW;
    END IF;

    -- Total businesses registered on that street (from estabelecimentos)
    SELECT COUNT(*) INTO total_count
      FROM estabelecimentos
     WHERE logradouro = NEW.logradouro
       AND ((biz_municipio = 'MARINGA' AND codigo_municipio = 7691)
         OR (biz_municipio <> 'MARINGA' AND municipio = biz_municipio));

    -- Visits are attributed to this city only through their CNPJ (visits has no municipality column);
    -- walk-by visits without CNPJ cannot be placed in a city, so they are not counted here.
    SELECT COUNT(DISTINCT v.cnpj) INTO covered_count
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Centroid of the visit points on that street (same city)
    SELECT ST_Centroid(ST_Collect(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)))
      INTO centroid
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Latest visit timestamp + total visit event count (same city)
    SELECT MAX(v.visited_at), COUNT(*) INTO latest_visit, total_visits
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Upsert the coverage row (recompute everything for consistency)
    INSERT INTO street_coverage
        (logradouro, bairro, municipio, state, last_visited,
         visit_count, total_businesses, covered_businesses, geom, updated_at)
    VALUES
        (NEW.logradouro, biz_bairro, biz_municipio, 'PR', latest_visit,
         total_visits, total_count, covered_count, centroid, NOW())
    ON CONFLICT (logradouro, municipio) DO UPDATE SET
        bairro            = EXCLUDED.bairro,
        last_visited      = EXCLUDED.last_visited,
        visit_count       = EXCLUDED.visit_count,
        total_businesses  = EXCLUDED.total_businesses,
        covered_businesses= EXCLUDED.covered_businesses,
        geom              = EXCLUDED.geom,
        updated_at        = NOW();

    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_update_street_coverage ON visits;
CREATE TRIGGER trigger_update_street_coverage
    AFTER INSERT ON visits
    FOR EACH ROW
    EXECUTE FUNCTION update_street_coverage();

-- ==============================================================================
-- SEED DATA — Street segments in downtown Londrina for testing
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

-- ==============================================================================
-- GRANTS
-- ==============================================================================
GRANT ALL PRIVILEGES ON TABLE street_segments TO postgres;
GRANT ALL PRIVILEGES ON TABLE routes TO postgres;
GRANT ALL PRIVILEGES ON TABLE route_stops TO postgres;
GRANT ALL PRIVILEGES ON TABLE visits TO postgres;
GRANT ALL PRIVILEGES ON TABLE business_status TO postgres;
GRANT ALL PRIVILEGES ON TABLE street_coverage TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE street_segments_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE visits_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE street_coverage_id_seq TO postgres;

SELECT 'Street tracking schema (visits + business_status + street_coverage) initialized successfully' as message;
