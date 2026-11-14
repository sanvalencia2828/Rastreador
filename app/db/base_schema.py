"""Base schema (init.sql + street_tracking_schema.sql) as idempotent DDL for managed Postgres.

Differences from the .sql files, which stay as they are for docker-compose:
no GRANT ... TO postgres (the owner already has rights), no DROP TABLE of visits/routes
(that would wipe data on every start), no street_segments demo seed, triggers are
DROP IF EXISTS + CREATE. Only public data is seeded: the cities lookup.
"""

BASE_DDL = """
CREATE TABLE IF NOT EXISTS estabelecimentos (
    id SERIAL PRIMARY KEY,
    cnpj_basico VARCHAR(8),
    cnpj_ordem VARCHAR(4),
    cnpj_dv VARCHAR(2),
    cnpj_completo VARCHAR(14) UNIQUE,
    identificador_matriz_filial INTEGER,
    nome_fantasia VARCHAR(255),
    situacao_cadastral INTEGER,
    data_situacao_cadastral DATE,
    motivo_situacao_cadastral INTEGER,
    nome_cidade_exterior VARCHAR(255),
    codigo_pais INTEGER,
    data_inicio_atividade DATE,
    cnae_fiscal INTEGER,
    cnae_fiscal_descricao TEXT,
    descricao_tipo_logradouro VARCHAR(50),
    logradouro VARCHAR(255),
    numero VARCHAR(20),
    complemento VARCHAR(255),
    bairro VARCHAR(100),
    cep VARCHAR(8),
    uf VARCHAR(2),
    codigo_municipio INTEGER,
    municipio VARCHAR(100),
    ddd_1 VARCHAR(2),
    telefone_1 VARCHAR(15),
    ddd_2 VARCHAR(2),
    telefone_2 VARCHAR(15),
    ddd_fax VARCHAR(2),
    fax VARCHAR(15),
    correio_eletronico VARCHAR(255),
    situacao_especial VARCHAR(100),
    data_situacao_especial DATE,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    geom geometry(Point, 4326),
    last_visit_date DATE,
    visits_count INTEGER NOT NULL DEFAULT 0,
    avg_visit_interval_days DOUBLE PRECISION,
    geocoded BOOLEAN DEFAULT FALSE,
    business_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_cnpj_completo ON estabelecimentos(cnpj_completo);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_municipio ON estabelecimentos(municipio);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_uf ON estabelecimentos(uf);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_cnae_fiscal ON estabelecimentos(cnae_fiscal);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_situacao_cadastral ON estabelecimentos(situacao_cadastral);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_data_inicio_atividade ON estabelecimentos(data_inicio_atividade);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_geolocation ON estabelecimentos(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_last_visit_date ON estabelecimentos(last_visit_date);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id SERIAL PRIMARY KEY,
    center_geom GEOMETRY(POINT, 4326),
    total_lojas INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS heatmap_data (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(POINT, 4326),
    weight INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_clusters_center_geom ON clusters USING GIST(center_geom);
CREATE INDEX IF NOT EXISTS idx_heatmap_data_geom ON heatmap_data USING GIST(geom);

CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    state VARCHAR(2) NOT NULL DEFAULT 'PR',
    lat NUMERIC(10,7),
    lon NUMERIC(10,7),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, state)
);
CREATE INDEX IF NOT EXISTS idx_cities_state ON cities(state);
INSERT INTO cities (name, state, lat, lon) VALUES
('Londrina', 'PR', -23.3103, -51.1628),
('Cambé', 'PR', -23.2778, -51.2675),
('Apucarana', 'PR', -23.5489, -51.4594),
('Pirapó', 'PR', -23.4167, -51.6500),
('Cambira', 'PR', -23.3500, -51.5667),
('Jandaia do Sul', 'PR', -23.2003, -51.5822),
('Maringá', 'PR', -23.4205, -51.9330)
ON CONFLICT (name, state) DO NOTHING;

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_estabelecimentos_updated_at ON estabelecimentos;
CREATE TRIGGER update_estabelecimentos_updated_at
    BEFORE UPDATE ON estabelecimentos
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'routes_status_check') THEN
        ALTER TABLE routes ADD CONSTRAINT routes_status_check
            CHECK (status IN ('planned', 'active', 'completed', 'cancelled'));
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_routes_geom ON routes USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_routes_user_id ON routes(user_id);
CREATE INDEX IF NOT EXISTS idx_routes_status ON routes(status);
CREATE INDEX IF NOT EXISTS idx_routes_planned_at ON routes(planned_at DESC);

CREATE TABLE IF NOT EXISTS visits (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    route_id UUID REFERENCES routes(id) ON DELETE CASCADE,
    cnpj VARCHAR(20),
    lat NUMERIC(10,7) NOT NULL,
    lon NUMERIC(10,7) NOT NULL,
    logradouro TEXT NOT NULL,
    bairro TEXT,
    notes TEXT,
    source VARCHAR(50) DEFAULT 'mobile',
    visited_at TIMESTAMPTZ DEFAULT NOW()
);
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
CREATE INDEX IF NOT EXISTS idx_route_stops_business ON route_stops(business_id);
CREATE INDEX IF NOT EXISTS idx_route_stops_route_order ON route_stops(route_id, stop_order);

CREATE TABLE IF NOT EXISTS business_status (
    cnpj       VARCHAR(20) PRIMARY KEY,
    status     VARCHAR(10) NOT NULL DEFAULT 'new',
    route_id   UUID REFERENCES routes(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (status IN ('new', 'visited', 'client'))
);
CREATE INDEX IF NOT EXISTS idx_business_status_status ON business_status(status);
DROP TRIGGER IF EXISTS update_business_status_updated_at ON business_status;
CREATE TRIGGER update_business_status_updated_at
    BEFORE UPDATE ON business_status
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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
    user_id UUID
);
CREATE UNIQUE INDEX IF NOT EXISTS street_coverage_user_street ON street_coverage (user_id, logradouro, municipio);
CREATE INDEX IF NOT EXISTS idx_street_coverage_municipio ON street_coverage(municipio);
CREATE INDEX IF NOT EXISTS idx_street_coverage_last_visited ON street_coverage(last_visited);
CREATE INDEX IF NOT EXISTS idx_street_coverage_geom ON street_coverage USING GIST(geom);
DROP TRIGGER IF EXISTS update_street_coverage_updated_at ON street_coverage;
CREATE TRIGGER update_street_coverage_updated_at
    BEFORE UPDATE ON street_coverage
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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
    biz_municipio := NULL;
    biz_bairro    := NEW.bairro;

    IF NEW.cnpj IS NOT NULL THEN
        SELECT CASE WHEN codigo_municipio = 7691 THEN 'MARINGA' ELSE municipio END, bairro
          INTO biz_municipio, biz_bairro
          FROM estabelecimentos
         WHERE cnpj_completo = NEW.cnpj
         LIMIT 1;
        IF biz_bairro IS NULL THEN
            biz_bairro := NEW.bairro;
        END IF;
    END IF;

    IF biz_municipio IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT COUNT(*) INTO total_count
      FROM estabelecimentos
     WHERE logradouro = NEW.logradouro
       AND ((biz_municipio = 'MARINGA' AND codigo_municipio = 7691)
         OR (biz_municipio <> 'MARINGA' AND municipio = biz_municipio));

    SELECT COUNT(DISTINCT v.cnpj) INTO covered_count
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    SELECT ST_Centroid(ST_Collect(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)))
      INTO centroid
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    SELECT MAX(v.visited_at), COUNT(*) INTO latest_visit, total_visits
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    INSERT INTO street_coverage
        (user_id, logradouro, bairro, municipio, state, last_visited,
         visit_count, total_businesses, covered_businesses, geom, updated_at)
    VALUES
        (NEW.user_id, NEW.logradouro, biz_bairro, biz_municipio, 'PR', latest_visit,
         total_visits, total_count, covered_count, centroid, NOW())
    ON CONFLICT (user_id, logradouro, municipio) DO UPDATE SET
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
"""
