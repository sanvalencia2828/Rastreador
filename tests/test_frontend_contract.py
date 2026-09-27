from pathlib import Path


def test_routes_page_calls_relative_v1_and_not_localhost():
    page = Path("frontend/src/app/routes/page.tsx").read_text(encoding="utf-8")
    assert "localhost" not in page
    assert "http://127.0.0.1" not in page
    assert "/api/v1/routes/import-maps" in page
    assert "/tarjeta" in page
    helper = Path("frontend/src/app/lib/api.ts").read_text(encoding="utf-8")
    assert "localhost" in helper
    assert "NODE_ENV" in helper
