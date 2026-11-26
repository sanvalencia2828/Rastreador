#!/usr/bin/env python3
"""Create or update the demo user. Credentials come from the environment only.

    DEMO_USER=demo DEMO_PASSWORD='...' python scripts/seed_demo_user.py

Uses the same database as the API (DATABASE_URL or DB_*), so run it where those are set.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.database import db_engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.bootstrap import ensure_schema  # noqa: E402


def main() -> int:
    username = os.environ.get("DEMO_USER", "").strip()
    password = os.environ.get("DEMO_PASSWORD", "")
    if not username or not password:
        print("Set DEMO_USER and DEMO_PASSWORD in the environment.", file=sys.stderr)
        return 1
    if len(password) < 12:
        print("DEMO_PASSWORD must be at least 12 characters.", file=sys.stderr)
        return 1
    if db_engine is None:
        print("No database configured (DATABASE_URL or DB_*).", file=sys.stderr)
        return 1

    ensure_schema()  # creates the users table if it does not exist yet
    with db_engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (username, password_hash) VALUES (:u, :h) "
                "ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash "
                "RETURNING id"
            ),
            {"u": username, "h": hash_password(password)},
        ).fetchone()[0]
    print(f"Demo user '{username}' ready (id {user_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
