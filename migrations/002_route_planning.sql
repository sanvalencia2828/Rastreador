-- Route planning model for business stops.
-- The existing routes/route_stops tables are extended instead of replaced so
-- city routes and legacy street routes remain readable.

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

ALTER TABLE visits ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mobile';

CREATE INDEX IF NOT EXISTS idx_routes_status ON routes(status);
CREATE INDEX IF NOT EXISTS idx_routes_planned_at ON routes(planned_at DESC);
CREATE INDEX IF NOT EXISTS idx_route_stops_business ON route_stops(business_id);
CREATE INDEX IF NOT EXISTS idx_route_stops_route_order ON route_stops(route_id, stop_order);
