-- Resultado de cada parada de la ruta de tarjetas (app/routes/tarjetas.py). visits no tiene columna de resultado
-- y cada fila suya dispara street_coverage, así que va en una tabla propia. Una fila por usuario, negocio y día.
-- Idempotente. Mismo DDL que app/db/bootstrap.py TARJETA_ENTREGAS_DDL (un test los mantiene idénticos).
CREATE TABLE IF NOT EXISTS tarjeta_entregas (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cnpj_completo VARCHAR(14) NOT NULL,
    fecha DATE NOT NULL DEFAULT ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date),
    resultado VARCHAR(20) NOT NULL,
    nota VARCHAR(500),
    lat NUMERIC(10,7),
    lon NUMERIC(10,7),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tarjeta_entregas_resultado_check CHECK (resultado IN ('tarjeta_entregada', 'cerrado', 'rechazo', 'interesado', 'no_encontrado')),
    CONSTRAINT tarjeta_entregas_coords_pair CHECK ((lat IS NULL) = (lon IS NULL)),
    CONSTRAINT tarjeta_entregas_lat_range CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT tarjeta_entregas_lon_range CHECK (lon BETWEEN -180 AND 180)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tarjeta_entregas_user_cnpj_fecha ON tarjeta_entregas(user_id, cnpj_completo, fecha);
