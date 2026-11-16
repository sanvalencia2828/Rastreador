CREATE TABLE IF NOT EXISTS clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    nombre_cliente TEXT,
    nombre_negocio TEXT,
    direccion TEXT,
    bairro TEXT,
    municipio TEXT,
    cep VARCHAR(10),
    lat NUMERIC(10,7),
    lon NUMERIC(10,7),
    geocode_status VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    geocode_source VARCHAR(20),
    nota TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT clientes_user_external_key UNIQUE (user_id, external_id),
    CONSTRAINT clientes_geocode_status_check CHECK (geocode_status IN ('ok', 'pendiente')),
    CONSTRAINT clientes_geocode_source_check CHECK (geocode_source IS NULL OR geocode_source IN ('usuario', 'nominatim', 'manual')),
    CONSTRAINT clientes_ok_requires_coords CHECK (geocode_status <> 'ok' OR lat IS NOT NULL),
    CONSTRAINT clientes_coords_pair CHECK ((lat IS NULL) = (lon IS NULL)),
    CONSTRAINT clientes_lat_range CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT clientes_lon_range CHECK (lon BETWEEN -180 AND 180)
);
CREATE INDEX IF NOT EXISTS idx_clientes_user_nombre ON clientes(user_id, nombre_negocio, id);
-- Tables created by the first draft of this migration lack coords_pair and the 'manual' source.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'clientes'::regclass AND conname = 'clientes_coords_pair') THEN
        ALTER TABLE clientes ADD CONSTRAINT clientes_coords_pair CHECK ((lat IS NULL) = (lon IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'clientes'::regclass AND conname = 'clientes_geocode_source_check'
                     AND position('manual' in pg_get_constraintdef(oid)) > 0) THEN
        ALTER TABLE clientes DROP CONSTRAINT IF EXISTS clientes_geocode_source_check;
        ALTER TABLE clientes ADD CONSTRAINT clientes_geocode_source_check
            CHECK (geocode_source IS NULL OR geocode_source IN ('usuario', 'nominatim', 'manual'));
    END IF;
END $$;
