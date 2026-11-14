CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS routes (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'optimized', 'in_progress', 'done')),
    entry_point_id BIGINT NOT NULL REFERENCES tracking_points(id),
    exit_point_id BIGINT NOT NULL REFERENCES tracking_points(id),
    total_km NUMERIC(10, 2),
    total_min NUMERIC(10, 2),
    optimized_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (entry_point_id != exit_point_id)
);

CREATE TABLE IF NOT EXISTS route_stops (
    id BIGSERIAL PRIMARY KEY,
    route_id BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    point_id BIGINT NOT NULL REFERENCES tracking_points(id),
    seq INT NOT NULL CHECK (seq >= 1),
    locked BOOLEAN NOT NULL DEFAULT false,
    eta_min NUMERIC(10, 2),
    distance_km NUMERIC(10, 2),
    UNIQUE(route_id, seq),
    UNIQUE(route_id, point_id)
);

CREATE INDEX IF NOT EXISTS idx_route_stops_route_id ON route_stops(route_id);
CREATE INDEX IF NOT EXISTS idx_route_stops_point_id ON route_stops(point_id);
CREATE INDEX IF NOT EXISTS idx_routes_entry_exit ON routes(entry_point_id, exit_point_id);
