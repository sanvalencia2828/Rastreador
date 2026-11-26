-- 005: street_coverage no longer assumes LONDRINA.
-- Triggers already created keep the old function body until this runs:
--   psql "$DATABASE_URL" -f migrations/005_street_coverage_no_default_city.sql
-- CREATE OR REPLACE swaps the function in place; the trigger on visits is untouched.
-- Existing street_coverage rows are NOT modified.
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
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Centroid of the visit points on that street (same city)
    SELECT ST_Centroid(ST_Collect(ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)))
      INTO centroid
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Latest visit timestamp + total visit event count (same city)
    SELECT MAX(v.visited_at), COUNT(*) INTO latest_visit, total_visits
      FROM visits v
     WHERE v.logradouro = NEW.logradouro
       AND EXISTS (SELECT 1 FROM estabelecimentos e WHERE e.cnpj_completo = v.cnpj
                      AND ((biz_municipio = 'MARINGA' AND e.codigo_municipio = 7691)
                        OR (biz_municipio <> 'MARINGA' AND e.municipio = biz_municipio)));

    -- Upsert the coverage row (recompute everything for consistency)
    INSERT INTO street_coverage
        (logradouro, bairro, municipio, state, last_visited,
         visit_count, total_businesses, covered_businesses, geom, updated_at)
    VALUES
        (NEW.logradouro, biz_bairro, biz_municipio, 'PR', latest_visit,
         total_visits, total_count, covered_count, centroid, NOW())
    ON CONFLICT (logradouro, municipio) DO UPDATE SET
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
