-- Reintentos acotados del geocodificador (enriquecer_lojas.py, MAX_GEOCODE_ATTEMPTS).
-- Idempotente. Mismo DDL que app/db/bootstrap.py GEOCODE_ATTEMPTS_DDL (un test los mantiene idénticos).
-- La API la crea al arrancar (app/db/bootstrap.py). Si corres enriquecer_lojas.py o load_filtered_cnpj.py --apply antes de desplegar la API, aplica este archivo a mano.
ALTER TABLE estabelecimentos
    ADD COLUMN IF NOT EXISTS geocode_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS geocode_last_try TIMESTAMPTZ;
