-- 007: street_coverage per user (table + trigger). Run on existing databases BEFORE deploying the per-user endpoint:
--   psql "$DATABASE_URL" -f migrations/007_street_coverage_per_user.sql
-- The trigger on visits is untouched; CREATE OR REPLACE swaps the function in place.
-- street_coverage becomes per-user: rows are keyed by (user_id, logradouro, municipio).
-- Legacy rows keep user_id NULL: nobody can be credited with them, so no user sees them (they are not deleted).
ALTER TABLE street_coverage ADD COLUMN IF NOT EXISTS user_id UUID;
DO $$
DECLARE c TEXT;
BEGIN
    FOR c IN SELECT con.conname FROM pg_constraint con
              WHERE con.conrelid = 'street_coverage'::regclass AND con.contype = 'u'
                AND (SELECT array_agg(att.attname::text ORDER BY att.attname) FROM pg_attribute att
                      WHERE att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)) = ARRAY['logradouro', 'municipio']
    LOOP
        EXECUTE format('ALTER TABLE street_coverage DROP CONSTRAINT %I', c);
    END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS street_coverage_user_street ON street_coverage (user_id, logradouro, municipio);

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
    -- No default city: the municipality must come from the establishment record.
    biz_municipio := NULL;
    biz_bairro    := NEW.bairro;

    IF NEW.cnpj IS NOT NULL THEN
        -- Receita dumps carry only the municipality CODE (Maringa = 7691), not a name, so that
        -- code decides; any other city keeps using estabelecimentos.municipio as before.
        SELECT CASE WHEN codigo_municipio = 7691 THEN 'MARINGA' ELSE municipio END, bairro
          INTO biz_municipio, biz_bairro
          FROM estabelecimentos
         WHERE cnpj_completo = NEW.cnpj
         LIMIT 1;
        IF biz_bairro IS NULL THEN
            biz_bairro := NEW.bairro;
        END IF;
    END IF;

    -- Unresolvable municipality (street walk-by without CNPJ, or CNPJ not loaded): no coverage row.
    IF biz_municipio IS NULL THEN
        RETURN NEW;
    END IF;

    -- Total businesses registered on that street (from estabelecimentos)
    SELECT COUNT(*) INTO total_count
      FROM estabelecimentos
     WHERE logradouro = NEW.logradouro
       AND ((biz_municipio = 'MARINGA' AND codigo_municipio = 7691)
         OR (biz_municipio <> 'MARINGA' AND municipio = biz_municipio));

    -- Visits are attributed to this city only through their CNPJ (visits has no municipality column);
    -- walk-by visits without CNPJ cannot be placed in a city, so they are not counted here.
    SELECT COUNT(DISTINCT v.cnpj) INTO covered_count
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Centroid of the visit points on that street (same city)
    SELECT ST_Centroid(ST_Collect(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)))
      INTO centroid
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Latest visit timestamp + total visit event count (same city)
    SELECT MAX(v.visited_at), COUNT(*) INTO latest_visit, total_visits
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND v.user_id = NEW.user_id
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Upsert the coverage row (recompute everything for consistency)
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
