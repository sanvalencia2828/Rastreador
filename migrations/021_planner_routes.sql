-- 021_planner_routes.sql
-- Idempotent planner schema for routes + route_stops.
--
-- There is no numbered migration 020 in this repository. The baseline lives in
-- init.sql, street_tracking_schema.sql, and the runtime DDL in api.py:
--   cities.id          INTEGER / SERIAL
--   routes.id          UUID (not BIGSERIAL)
--   route_stops        child table, historically stop_order + lon
-- This file is safe to re-run. It alters the existing tables when they are
-- already there and creates them when they are not.
-- `planned` is deprecated and mapped to `locked`.

DO $ext$
BEGIN
    EXECUTE 'CREATE EXTENSION IF NOT EXISTS pgcrypto';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgcrypto skipped: %', SQLERRM;
END
$ext$;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    state VARCHAR(2) NOT NULL DEFAULT 'PR',
    lat NUMERIC(10, 7),
    lon NUMERIC(10, 7),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (name, state)
);

INSERT INTO cities (name, state, lat, lon)
SELECT v.name, v.state, v.lat, v.lon
FROM (
    VALUES
        ('Londrina', 'PR', -23.3103::numeric, -51.1628::numeric),
        ('Cambé', 'PR', -23.2778::numeric, -51.2675::numeric),
        ('Apucarana', 'PR', -23.5489::numeric, -51.4594::numeric),
        ('Pirapó', 'PR', -23.4167::numeric, -51.6500::numeric),
        ('Cambira', 'PR', -23.3500::numeric, -51.5667::numeric),
        ('Jandaia do Sul', 'PR', -23.2003::numeric, -51.5822::numeric)
) AS v(name, state, lat, lon)
WHERE NOT EXISTS (
    SELECT 1 FROM cities c WHERE c.name = v.name AND c.state = v.state
);

CREATE TABLE IF NOT EXISTS routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    city_id INTEGER,
    name VARCHAR(255),
    status TEXT NOT NULL DEFAULT 'draft',
    vehicle_id TEXT,
    "date" DATE NOT NULL DEFAULT CURRENT_DATE,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT routes_status_check CHECK (status IN ('draft', 'locked', 'committed'))
);

ALTER TABLE routes ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS city_id INTEGER;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS name VARCHAR(255);
ALTER TABLE routes ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS vehicle_id TEXT;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS "date" DATE;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS meta JSONB;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

UPDATE routes SET status = 'locked' WHERE lower(status) = 'planned';
UPDATE routes
   SET status = 'draft'
 WHERE status IS NULL
    OR lower(status) NOT IN ('draft', 'locked', 'committed');
UPDATE routes
   SET "date" = COALESCE("date", created_at::date, CURRENT_DATE)
 WHERE "date" IS NULL;
UPDATE routes SET meta = '{}'::jsonb WHERE meta IS NULL;
UPDATE routes
   SET created_at = COALESCE(created_at, NOW())
 WHERE created_at IS NULL;
UPDATE routes
   SET updated_at = COALESCE(updated_at, created_at, NOW())
 WHERE updated_at IS NULL;

ALTER TABLE routes ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE routes ALTER COLUMN status SET NOT NULL;
ALTER TABLE routes ALTER COLUMN "date" SET DEFAULT CURRENT_DATE;
ALTER TABLE routes ALTER COLUMN "date" SET NOT NULL;
ALTER TABLE routes ALTER COLUMN meta SET DEFAULT '{}'::jsonb;
ALTER TABLE routes ALTER COLUMN meta SET NOT NULL;
ALTER TABLE routes ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE routes ALTER COLUMN updated_at SET DEFAULT NOW();
ALTER TABLE routes ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE routes DROP CONSTRAINT IF EXISTS routes_status_check;
ALTER TABLE routes
    ADD CONSTRAINT routes_status_check
    CHECK (status IN ('draft', 'locked', 'committed'));

CREATE TABLE IF NOT EXISTS route_stops (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    stop_order INTEGER,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    order_id TEXT,
    stop_ref TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    address TEXT,
    cep VARCHAR(10),
    display_name TEXT,
    maps_url TEXT,
    source TEXT DEFAULT 'google_maps',
    visit_date DATE NOT NULL DEFAULT CURRENT_DATE,
    tarjeta_status VARCHAR(2) NOT NULL DEFAULT 'TT',
    tarjeta_at TIMESTAMPTZ,
    tarjeta_by TEXT,
    eta_s INTEGER,
    distance_m INTEGER,
    meta JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT route_stops_tarjeta_status_check
        CHECK (tarjeta_status IN ('TT', 'TS', 'TC', 'VV', 'TF', 'PT', 'VS')),
    CONSTRAINT route_stops_route_id_seq_key UNIQUE (route_id, seq)
);

ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS seq INTEGER;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS stop_order INTEGER;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS locked BOOLEAN;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS order_id TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS stop_ref TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS cep VARCHAR(10);
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS maps_url TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS visit_date DATE;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS tarjeta_status VARCHAR(2);
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS tarjeta_at TIMESTAMPTZ;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS tarjeta_by TEXT;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS eta_s INTEGER;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS distance_m INTEGER;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS meta JSONB;
ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

ALTER TABLE route_stops ALTER COLUMN lat DROP NOT NULL;
ALTER TABLE route_stops ALTER COLUMN lon DROP NOT NULL;
ALTER TABLE route_stops ALTER COLUMN address DROP NOT NULL;

UPDATE route_stops SET seq = stop_order WHERE seq IS NULL AND stop_order IS NOT NULL;
UPDATE route_stops SET lng = lon::double precision WHERE lng IS NULL AND lon IS NOT NULL;
UPDATE route_stops SET lon = lng WHERE lon IS NULL AND lng IS NOT NULL;
UPDATE route_stops SET visit_date = CURRENT_DATE WHERE visit_date IS NULL;
UPDATE route_stops SET locked = FALSE WHERE locked IS NULL;
UPDATE route_stops SET source = 'google_maps' WHERE source IS NULL;
UPDATE route_stops SET meta = '{}'::jsonb WHERE meta IS NULL;
UPDATE route_stops SET created_at = NOW() WHERE created_at IS NULL;
UPDATE route_stops
   SET tarjeta_status = 'TT'
 WHERE tarjeta_status IS NULL
    OR tarjeta_status NOT IN ('TT', 'TS', 'TC', 'VV', 'TF', 'PT', 'VS');

-- Renumber only when seq is missing or duplicated, so a re-run does not shuffle
-- a healthy route.
DO $mig$
BEGIN
    IF EXISTS (SELECT 1 FROM route_stops WHERE seq IS NULL)
       OR EXISTS (
            SELECT 1
              FROM route_stops
             GROUP BY route_id, seq
            HAVING COUNT(*) > 1
       )
    THEN
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY route_id
                       ORDER BY COALESCE(seq, stop_order, 999999), id
                   ) AS rn
              FROM route_stops
        )
        UPDATE route_stops AS s
           SET seq = ranked.rn
          FROM ranked
         WHERE s.id = ranked.id;
    END IF;
END
$mig$;

UPDATE route_stops SET stop_order = seq WHERE stop_order IS NULL AND seq IS NOT NULL;

ALTER TABLE route_stops ALTER COLUMN seq SET NOT NULL;
ALTER TABLE route_stops ALTER COLUMN locked SET DEFAULT FALSE;
ALTER TABLE route_stops ALTER COLUMN locked SET NOT NULL;
ALTER TABLE route_stops ALTER COLUMN visit_date SET DEFAULT CURRENT_DATE;
ALTER TABLE route_stops ALTER COLUMN visit_date SET NOT NULL;
ALTER TABLE route_stops ALTER COLUMN tarjeta_status SET DEFAULT 'TT';
ALTER TABLE route_stops ALTER COLUMN tarjeta_status SET NOT NULL;
ALTER TABLE route_stops ALTER COLUMN source SET DEFAULT 'google_maps';
ALTER TABLE route_stops ALTER COLUMN meta SET DEFAULT '{}'::jsonb;
ALTER TABLE route_stops ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE route_stops DROP CONSTRAINT IF EXISTS route_stops_tarjeta_status_check;
ALTER TABLE route_stops
    ADD CONSTRAINT route_stops_tarjeta_status_check
    CHECK (tarjeta_status IN ('TT', 'TS', 'TC', 'VV', 'TF', 'PT', 'VS'));

DELETE FROM route_stops AS s
 WHERE NOT EXISTS (SELECT 1 FROM routes AS r WHERE r.id = s.route_id);

ALTER TABLE route_stops DROP CONSTRAINT IF EXISTS route_stops_route_id_fkey;
ALTER TABLE route_stops
    ADD CONSTRAINT route_stops_route_id_fkey
    FOREIGN KEY (route_id) REFERENCES routes(id) ON DELETE CASCADE;

DO $mig$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'route_stops_route_id_seq_key'
    ) THEN
        ALTER TABLE route_stops
            ADD CONSTRAINT route_stops_route_id_seq_key UNIQUE (route_id, seq);
    END IF;
END
$mig$;

DO $mig$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'routes_city_id_fkey'
    ) THEN
        BEGIN
            ALTER TABLE routes
                ADD CONSTRAINT routes_city_id_fkey
                FOREIGN KEY (city_id) REFERENCES cities(id);
        EXCEPTION
            WHEN others THEN
                RAISE NOTICE 'routes.city_id foreign key skipped: %', SQLERRM;
        END;
    END IF;
END
$mig$;

CREATE INDEX IF NOT EXISTS idx_routes_city_date_status
    ON routes (city_id, "date", status);
CREATE INDEX IF NOT EXISTS idx_route_stops_visit_tarjeta
    ON route_stops (visit_date, tarjeta_status);
CREATE INDEX IF NOT EXISTS idx_route_stops_route_id
    ON route_stops (route_id);

CREATE OR REPLACE FUNCTION route_stops_sync_compat()
RETURNS TRIGGER AS $fn$
BEGIN
    IF NEW.seq IS NULL THEN
        NEW.seq := COALESCE(NEW.stop_order, 1);
    END IF;
    IF NEW.stop_order IS NULL THEN
        NEW.stop_order := NEW.seq;
    END IF;
    IF NEW.lng IS NULL AND NEW.lon IS NOT NULL THEN
        NEW.lng := NEW.lon::double precision;
    END IF;
    IF NEW.lon IS NULL AND NEW.lng IS NOT NULL THEN
        NEW.lon := NEW.lng;
    END IF;
    IF NEW.visit_date IS NULL THEN
        NEW.visit_date := CURRENT_DATE;
    END IF;
    IF NEW.tarjeta_status IS NULL OR NEW.tarjeta_status = '' THEN
        NEW.tarjeta_status := 'TT';
    END IF;
    IF NEW.meta IS NULL THEN
        NEW.meta := '{}'::jsonb;
    END IF;
    IF NEW.source IS NULL OR NEW.source = '' THEN
        NEW.source := 'google_maps';
    END IF;
    IF NEW.locked IS NULL THEN
        NEW.locked := FALSE;
    END IF;
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_route_stops_sync_compat ON route_stops;
CREATE TRIGGER trg_route_stops_sync_compat
    BEFORE INSERT OR UPDATE ON route_stops
    FOR EACH ROW
    EXECUTE PROCEDURE route_stops_sync_compat();

CREATE OR REPLACE FUNCTION routes_touch_updated_at()
RETURNS TRIGGER AS $fn$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_routes_touch_updated_at ON routes;
CREATE TRIGGER trg_routes_touch_updated_at
    BEFORE UPDATE ON routes
    FOR EACH ROW
    EXECUTE PROCEDURE routes_touch_updated_at();

INSERT INTO schema_migrations (version)
VALUES ('021')
ON CONFLICT (version) DO UPDATE SET applied_at = NOW();
