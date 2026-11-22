-- Reintentos acotados del geocodificador (enriquecer_lojas.py, MAX_GEOCODE_ATTEMPTS).
-- Idempotente. Mismo DDL que app/db/bootstrap.py GEOCODE_ATTEMPTS_DDL (un test los mantiene idénticos).
ALTER TABLE estabelecimentos
    ADD COLUMN IF NOT EXISTS geocode_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS geocode_last_try TIMESTAMPTZ;
