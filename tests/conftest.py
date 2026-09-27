"""Keep tests off the production database and off a missing frontend build."""

import os

os.environ["DATABASE_URL"] = ""
os.environ["MAPS_RESOLVE_SHORT_LINKS"] = "0"
os.environ.setdefault("DEV_USER_ID", "00000000-0000-0000-0000-000000000001")
os.environ["FRONTEND_DIST"] = os.path.join(os.path.dirname(__file__), "_missing_frontend")

import pytest

from app.deps import set_repository


@pytest.fixture(autouse=True)
def _clear_repo_override():
    set_repository(None)
    yield
    set_repository(None)
