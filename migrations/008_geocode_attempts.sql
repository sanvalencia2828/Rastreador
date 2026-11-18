-- Reintentos acotados del geocodificador (enriquecer_lojas.py, MAX_GEOCODE_ATTEMPTS).
-- Idempotente. Aplicar manualmente antes de correr enriquecer_lojas.py.
ALTER TABLE estabelecimentos
    ADD COLUMN IF NOT EXISTS geocode_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS geocode_last_try TIMESTAMPTZ;
