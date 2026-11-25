-- Clientes atrasados (pago o visita pendiente): /api/routes/clientes-dia los incluye siempre y no los descarta por el tope.
-- Idempotente. Mismo DDL que app/db/bootstrap.py CLIENTES_ATRASADO_DDL (un test los mantiene idénticos).
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS atrasado BOOLEAN NOT NULL DEFAULT FALSE;
