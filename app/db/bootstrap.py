"""Idempotent schema setup run at startup."""

from sqlalchemy import text

from app.core.database import db_engine
from app.db.base_schema import BASE_DDL


def _err(e: Exception) -> str:
    """Class + first line of the message (never the URL: the engine hides parameters)."""
    return f"{type(e).__name__}: {(str(e).splitlines() or [''])[0]}"


# Same DDL as migrations/004_clientes.sql (a test keeps them identical).
CLIENTES_DDL = """
CREATE TABLE IF NOT EXISTS clientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_id VARCHAR(64) NOT NULL,
    nombre_cliente TEXT,
    nombre_negocio TEXT,
    direccion TEXT,
    bairro TEXT,
    municipio TEXT,
    cep VARCHAR(10),
    lat NUMERIC(10,7),
    lon NUMERIC(10,7),
    geocode_status VARCHAR(20) NOT NULL DEFAULT 'pendiente',
    geocode_source VARCHAR(20),
    nota TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT clientes_user_external_key UNIQUE (user_id, external_id),
    CONSTRAINT clientes_geocode_status_check CHECK (geocode_status IN ('ok', 'pendiente')),
    CONSTRAINT clientes_geocode_source_check CHECK (geocode_source IS NULL OR geocode_source IN ('usuario', 'nominatim', 'manual')),
    CONSTRAINT clientes_ok_requires_coords CHECK (geocode_status <> 'ok' OR lat IS NOT NULL),
    CONSTRAINT clientes_coords_pair CHECK ((lat IS NULL) = (lon IS NULL)),
    CONSTRAINT clientes_lat_range CHECK (lat BETWEEN -90 AND 90),
    CONSTRAINT clientes_lon_range CHECK (lon BETWEEN -180 AND 180)
);
CREATE INDEX IF NOT EXISTS idx_clientes_user_nombre ON clientes(user_id, nombre_negocio, id);
-- Tables created by the first draft of this migration lack coords_pair and the 'manual' source.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'clientes'::regclass AND conname = 'clientes_coords_pair') THEN
        ALTER TABLE clientes ADD CONSTRAINT clientes_coords_pair CHECK ((lat IS NULL) = (lon IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'clientes'::regclass AND conname = 'clientes_geocode_source_check'
                     AND position('manual' in pg_get_constraintdef(oid)) > 0) THEN
        ALTER TABLE clientes DROP CONSTRAINT IF EXISTS clientes_geocode_source_check;
        ALTER TABLE clientes ADD CONSTRAINT clientes_geocode_source_check
            CHECK (geocode_source IS NULL OR geocode_source IN ('usuario', 'nominatim', 'manual'));
    END IF;
END $$;
"""

# Same DDL as migrations/006_street_catalog.sql (a test keeps them identical).
STREETS_DDL = """
CREATE TABLE IF NOT EXISTS street_segments (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    name VARCHAR(255),
    geom GEOMETRY(LineString, 4326),
    length_m DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE street_segments ADD COLUMN IF NOT EXISTS municipio TEXT;
ALTER TABLE street_segments ADD COLUMN IF NOT EXISTS street_key TEXT;
CREATE INDEX IF NOT EXISTS idx_street_segments_geom ON street_segments USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_street_segments_key ON street_segments(municipio, street_key);

CREATE TABLE IF NOT EXISTS street_catalog (
    id SERIAL PRIMARY KEY,
    municipio TEXT NOT NULL,
    street_key TEXT NOT NULL,
    osm_key TEXT,
    tipo TEXT,
    nombre TEXT NOT NULL,
    n_comercios_activos INTEGER NOT NULL DEFAULT 0,
    numero_min INTEGER,
    numero_max INTEGER,
    sin_numero INTEGER NOT NULL DEFAULT 0,
    ceps TEXT[] NOT NULL DEFAULT '{}',
    length_m DOUBLE PRECISION,
    pareado_pct INTEGER,
    spread_m DOUBLE PRECISION,
    match_type TEXT,
    estado TEXT NOT NULL,
    en_plan_automatico BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT street_catalog_key UNIQUE (municipio, street_key),
    CONSTRAINT street_catalog_estado_check CHECK (estado IN ('ok', 'calle_larga', 'ambigua', 'sin_geometria'))
);
CREATE INDEX IF NOT EXISTS idx_street_catalog_osm_key ON street_catalog(municipio, osm_key);

-- Measured minutes per street, derived from visits.visited_at of a route (approximation: includes walking and pauses).
CREATE TABLE IF NOT EXISTS street_time_log (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    route_id UUID NOT NULL,
    municipio TEXT NOT NULL,
    street_key TEXT NOT NULL,
    seconds INTEGER NOT NULL CHECK (seconds > 0),
    n_visitas INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT street_time_log_user_route_street UNIQUE (user_id, route_id, street_key)
);
-- The first draft was UNIQUE (route_id, street_key): two users sharing a route id would collide.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'street_time_log'::regclass
                 AND conname = 'street_time_log_route_street') THEN
        ALTER TABLE street_time_log DROP CONSTRAINT street_time_log_route_street;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'street_time_log'::regclass
                     AND conname = 'street_time_log_user_route_street') THEN
        ALTER TABLE street_time_log ADD CONSTRAINT street_time_log_user_route_street UNIQUE (user_id, route_id, street_key);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_street_time_log_user ON street_time_log(user_id, municipio, street_key);
"""

# Same DDL as migrations/008_geocode_attempts.sql (a test keeps them identical).
GEOCODE_ATTEMPTS_DDL = """
ALTER TABLE estabelecimentos
    ADD COLUMN IF NOT EXISTS geocode_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS geocode_last_try TIMESTAMPTZ;
"""


# Same DDL as migrations/009_tarjeta_entregas.sql (a test keeps them identical).
TARJETA_ENTREGAS_DDL = """
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
"""

# Same DDL as migrations/010_clientes_visita_diaria.sql (a test keeps them identical).
CLIENTES_VISITA_DIARIA_DDL = """
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS visita_diaria BOOLEAN NOT NULL DEFAULT FALSE;
"""

# Same DDL as migrations/011_clientes_atrasado.sql (a test keeps them identical).
CLIENTES_ATRASADO_DDL = """
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS atrasado BOOLEAN NOT NULL DEFAULT FALSE;
"""


def _ensure_clientes_schema() -> None:
    """Private per-user customer list; idempotent."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text(CLIENTES_DDL))
            conn.execute(text(CLIENTES_VISITA_DIARIA_DDL))
            conn.execute(text(CLIENTES_ATRASADO_DDL))
    except Exception as e:
        print(f"Error initializing clientes table ({_err(e)})")


def _ensure_route_stops_cliente_id() -> None:
    """Paradas que son clientes del usuario (business_id sigue siendo para el volcado CNPJ); idempotente."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                DO $$ BEGIN
                    IF to_regclass('route_stops') IS NOT NULL THEN
                        ALTER TABLE route_stops
                            ADD COLUMN IF NOT EXISTS cliente_id UUID REFERENCES clientes(id) ON DELETE SET NULL;
                        CREATE INDEX IF NOT EXISTS idx_route_stops_cliente ON route_stops(cliente_id);
                    END IF;
                END $$;
            """))
    except Exception as e:
        print(f"Error adding route_stops.cliente_id ({_err(e)})")


def _ensure_maringa_city() -> None:
    """Maringa (PR) en cities. Centro: -23.4253, -51.9386 (23°25'31\"S 51°56'19\"O, ficha del municipio en Wikipedia)."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                DO $$ BEGIN
                    IF to_regclass('cities') IS NOT NULL THEN
                        INSERT INTO cities (name, state, lat, lon) VALUES ('Maringá', 'PR', -23.4253, -51.9386)
                        ON CONFLICT (name, state) DO NOTHING;
                    END IF;
                END $$;
            """))
    except Exception as e:
        print(f"Error seeding Maringa city ({_err(e)})")


# Arapongas (PR): hay clientes allí y sin fila en cities no aparecían en Cidades. Centro: -23.4194, -51.4244
# (el mismo que cities.py y frontend/src/app/lib/ciudades.ts). Igual que migrations/012_cities_arapongas.sql.
ARAPONGAS_CITY_SQL = """
INSERT INTO cities (name, state, lat, lon) VALUES ('Arapongas', 'PR', -23.4194, -51.4244)
ON CONFLICT (name, state) DO NOTHING;
"""


def _ensure_city_list() -> None:
    """Swap Pirapó/Cambira for Marialva/Mandaguari and add Arapongas in existing DBs (ON CONFLICT DO NOTHING); idempotent.

    An old city is deleted only if no foreign key row points at it; otherwise it stays and a warning is logged.
    """
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            if conn.execute(text("SELECT to_regclass('cities')")).scalar() is None:
                return
            conn.execute(text("""
                INSERT INTO cities (name, state, lat, lon) VALUES
                    ('Marialva', 'PR', -23.4855, -51.7927),
                    ('Mandaguari', 'PR', -23.5478, -51.6708)
                ON CONFLICT (name, state) DO NOTHING
            """))
            conn.execute(text(ARAPONGAS_CITY_SQL))
            fks = conn.execute(text("""
                SELECT con.conrelid::regclass::text, att.attname
                  FROM pg_constraint con
                  JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
                 WHERE con.contype = 'f' AND con.confrelid = 'cities'::regclass
            """)).all()
            for name in ("Pirapó", "Cambira"):
                cid = conn.execute(text("SELECT id FROM cities WHERE name = :n AND state = 'PR'"), {"n": name}).scalar()
                if cid is None:
                    continue
                used_by = [t for t, col in fks
                           if conn.execute(text(f'SELECT EXISTS (SELECT 1 FROM {t} WHERE "{col}" = :i)'), {"i": cid}).scalar()]
                if used_by:
                    print(f"WARNING: city {name} (id {cid}) kept: referenced by {', '.join(used_by)}")
                else:
                    conn.execute(text("DELETE FROM cities WHERE id = :i"), {"i": cid})
    except Exception as e:
        print(f"Error updating city list ({_err(e)})")


def _ensure_streets_schema() -> None:
    """Street catalog + time log (needs PostGIS); idempotent."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text(STREETS_DDL))
    except Exception as e:
        print(f"Error initializing street catalog ({_err(e)})")


def _ensure_business_visit_metrics_schema() -> None:
    """Apply the small idempotent schema change when no migration runner exists."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE estabelecimentos
                    ADD COLUMN IF NOT EXISTS last_visit_date DATE,
                    ADD COLUMN IF NOT EXISTS visits_count INTEGER NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS avg_visit_interval_days DOUBLE PRECISION
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_estabelecimentos_last_visit_date
                    ON estabelecimentos(last_visit_date)
            """))
    except Exception as e:
        print(f"Error initializing business visit metrics columns ({_err(e)})")


def _ensure_geocode_attempts_schema() -> None:
    """Bounded geocoder retries (enriquecer_lojas.py, load_filtered_cnpj.py); idempotent."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text(GEOCODE_ATTEMPTS_DDL))
    except Exception as e:
        print(f"Error initializing geocode attempts columns ({_err(e)})")


def _ensure_tarjeta_entregas_schema() -> None:
    """Results of the business-card route (app/routes/tarjetas.py); idempotent."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text(TARJETA_ENTREGAS_DDL))
    except Exception as e:
        print(f"Error initializing tarjeta_entregas table ({_err(e)})")


def _ensure_postgis() -> None:
    """Enable PostGIS (Render allows CREATE EXTENSION for the database owner); warn loudly if it fails."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    except Exception as e:
        print(f"WARNING: could not enable PostGIS ({_err(e)}); routes/streets tables will fail until it is enabled")


def _ensure_base_schema() -> None:
    """Tables from init.sql / street_tracking_schema.sql, which only docker-compose runs; idempotent."""
    if not db_engine:
        return
    try:
        with db_engine.begin() as conn:
            conn.execute(text(BASE_DDL))
    except Exception as e:
        print(f"Error initializing base schema ({_err(e)})")


def ensure_schema() -> None:
    """Create or patch the tables the API expects; safe to run repeatedly."""
    _ensure_postgis()
    _ensure_base_schema()
    _ensure_business_visit_metrics_schema()
    _ensure_geocode_attempts_schema()

    # Initialize User Table
    if db_engine:
        try:
            with db_engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        username VARCHAR(255) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """))
                print("Successfully initialized users table in DB.")
        except Exception as e:
            print(f"Error initializing users table ({_err(e)})")

    if db_engine:
        try:
            with db_engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS daily_routes (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id UUID NOT NULL REFERENCES users(id),
                        name VARCHAR(255) NOT NULL,
                        day_of_week VARCHAR(20),
                        streets TEXT[] DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """))
                print("Successfully initialized daily_routes table in DB.")
        except Exception as e:
            print(f"Error initializing daily_routes table ({_err(e)})")

    if db_engine:
        try:
            with db_engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS routes (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id UUID,
                        city_id INTEGER REFERENCES cities(id),
                        name VARCHAR(255) NOT NULL,
                        geom GEOMETRY(LineString, 4326),
                        start_lat NUMERIC(10,7),
                        start_lng NUMERIC(10,7),
                        status VARCHAR(20) NOT NULL DEFAULT 'planned',
                        planned_at TIMESTAMPTZ DEFAULT NOW(),
                        started_at TIMESTAMPTZ,
                        ended_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ,
                        completed_date DATE,
                        total_stops_planned INTEGER NOT NULL DEFAULT 0,
                        total_stops_done INTEGER NOT NULL DEFAULT 0,
                        total_distance_km DOUBLE PRECISION NOT NULL DEFAULT 0,
                        total_duration_min DOUBLE PRECISION NOT NULL DEFAULT 0,
                        notes TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                conn.execute(text("ALTER TABLE routes ALTER COLUMN user_id DROP NOT NULL;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id);"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS start_lat NUMERIC(10,7);"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS start_lng NUMERIC(10,7);"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'planned';"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS planned_at TIMESTAMPTZ DEFAULT NOW();"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS completed_date DATE;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_stops_planned INTEGER NOT NULL DEFAULT 0;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_stops_done INTEGER NOT NULL DEFAULT 0;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_distance_km DOUBLE PRECISION NOT NULL DEFAULT 0;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS total_duration_min DOUBLE PRECISION NOT NULL DEFAULT 0;"))
                conn.execute(text("ALTER TABLE routes ADD COLUMN IF NOT EXISTS notes TEXT;"))
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint WHERE conname = 'routes_status_check'
                        ) THEN
                            ALTER TABLE routes ADD CONSTRAINT routes_status_check
                                CHECK (status IN ('planned', 'active', 'completed', 'cancelled'));
                        END IF;
                    END $$;
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS route_stops (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        route_id UUID REFERENCES routes(id) ON DELETE CASCADE,
                        business_id INTEGER REFERENCES estabelecimentos(id),
                        stop_order INTEGER NOT NULL,
                        address TEXT NOT NULL,
                        lat NUMERIC(10,7) NOT NULL,
                        lon NUMERIC(10,7) NOT NULL,
                        cep VARCHAR(10),
                        display_name TEXT,
                        visited BOOLEAN NOT NULL DEFAULT FALSE,
                        visited_at TIMESTAMPTZ,
                        skipped BOOLEAN NOT NULL DEFAULT FALSE,
                        skip_reason TEXT,
                        notes TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES estabelecimentos(id);"))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS visited BOOLEAN NOT NULL DEFAULT FALSE;"))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS visited_at TIMESTAMPTZ;"))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT FALSE;"))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS skip_reason TEXT;"))
                conn.execute(text("ALTER TABLE route_stops ADD COLUMN IF NOT EXISTS notes TEXT;"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stops_route ON route_stops(route_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_routes_city_id ON routes(city_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_routes_status ON routes(status);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_routes_planned_at ON routes(planned_at DESC);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_route_stops_business ON route_stops(business_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_route_stops_route_order ON route_stops(route_id, stop_order);"))
                print("Successfully initialized routes tables in DB.")
        except Exception as e:
            print(f"Error initializing routes tables ({_err(e)})")


    if db_engine:
        try:
            with db_engine.begin() as conn:
                conn.execute(text("ALTER TABLE visits ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mobile';"))
        except Exception as e:
            print(f"Error initializing visit source column ({_err(e)})")

    _ensure_clientes_schema()  # needs users, created above
    _ensure_tarjeta_entregas_schema()  # needs users
    _ensure_route_stops_cliente_id()  # needs clientes and route_stops
    _ensure_maringa_city()
    _ensure_city_list()
    _ensure_streets_schema()  # needs PostGIS
