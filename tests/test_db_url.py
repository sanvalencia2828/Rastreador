from app.core.database import normalize_db_url


def test_normalize_db_url():
    assert normalize_db_url("postgres://u:p@h/db") == "postgresql://u:p@h/db"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"
    assert normalize_db_url(None) is None
