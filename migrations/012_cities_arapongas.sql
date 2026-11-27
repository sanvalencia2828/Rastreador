-- Arapongas (PR) en cities: sus clientes no salían en Cidades. Centro igual que cities.py y lib/ciudades.ts.
-- Idempotente. Mismo SQL que app/db/bootstrap.py ARAPONGAS_CITY_SQL (un test los mantiene idénticos).
INSERT INTO cities (name, state, lat, lon) VALUES ('Arapongas', 'PR', -23.4194, -51.4244)
ON CONFLICT (name, state) DO NOTHING;
