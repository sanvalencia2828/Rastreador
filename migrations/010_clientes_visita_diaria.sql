-- Clientes que se visitan todos los días: Gerar Semana los agrega a cada día en vez de repartirlos.
-- Idempotente. Mismo DDL que app/db/bootstrap.py CLIENTES_VISITA_DIARIA_DDL (un test los mantiene idénticos).
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS visita_diaria BOOLEAN NOT NULL DEFAULT FALSE;
