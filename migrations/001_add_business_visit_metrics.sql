-- Add visit metrics to the canonical business table.
-- Run this migration on databases created before these columns were added to init.sql.

ALTER TABLE estabelecimentos
    ADD COLUMN IF NOT EXISTS last_visit_date DATE,
    ADD COLUMN IF NOT EXISTS visits_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS avg_visit_interval_days DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_estabelecimentos_last_visit_date
    ON estabelecimentos(last_visit_date);

-- Backfill persisted metrics from the existing visit history. Dates are
-- distinct per business, matching the API recalculation rules.
WITH distinct_visit_dates AS (
    SELECT
        e.id AS business_id,
        v.visited_at::date AS visit_date
    FROM estabelecimentos e
    JOIN visits v ON v.cnpj = e.cnpj_completo
    WHERE v.visited_at IS NOT NULL
    GROUP BY e.id, v.visited_at::date
), intervals AS (
    SELECT
        business_id,
        visit_date,
        visit_date - LAG(visit_date) OVER (
            PARTITION BY business_id ORDER BY visit_date
        ) AS interval_days
    FROM distinct_visit_dates
), metrics AS (
    SELECT
        business_id,
        COUNT(*)::integer AS visits_count,
        MAX(visit_date) AS last_visit_date,
        AVG(interval_days)::double precision AS avg_visit_interval_days
    FROM intervals
    GROUP BY business_id
)
UPDATE estabelecimentos e
SET visits_count = metrics.visits_count,
    last_visit_date = metrics.last_visit_date,
    avg_visit_interval_days = metrics.avg_visit_interval_days
FROM metrics
WHERE e.id = metrics.business_id;
