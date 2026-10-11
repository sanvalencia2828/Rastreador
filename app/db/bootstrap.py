"""Idempotent schema setup run at startup."""

from sqlalchemy import text

from app.core.database import db_engine


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
        print(f"Error initializing business visit metrics columns: {e}")


def ensure_schema() -> None:
    """Create or patch the tables the API expects; safe to run repeatedly."""
    _ensure_business_visit_metrics_schema()

    # Initialize User Table
    if db_engine:
        try:
            with db_engine.connect() as conn:
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
            print(f"Error initializing users table: {e}")

    if db_engine:
        try:
            with db_engine.connect() as conn:
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
            print(f"Error initializing daily_routes table: {e}")

    if db_engine:
        try:
            with db_engine.connect() as conn:
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
                conn.commit()
                print("Successfully initialized routes tables in DB.")
        except Exception as e:
            print(f"Error initializing routes tables: {e}")


    if db_engine:
        try:
            with db_engine.begin() as conn:
                conn.execute(text("ALTER TABLE visits ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'mobile';"))
        except Exception as e:
            print(f"Error initializing visit source column: {e}")
