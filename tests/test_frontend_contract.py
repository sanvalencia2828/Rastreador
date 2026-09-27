from pathlib import Path


def test_api_proxy_reads_env_and_does_not_hardcode_hosts():
    proxy = Path("frontend/src/app/api/[...path]/route.ts").read_text(encoding="utf-8")
    config = Path("frontend/next.config.ts").read_text(encoding="utf-8")
    assert "onrender.com" not in proxy
    assert "vercel.app" not in proxy
    assert "BACKEND_URL" in proxy
    assert "VITE_API_URL" in proxy
    assert "localhost:8001" not in config.split("onVercel")[0]


def test_routes_page_calls_relative_v1_and_not_localhost():
    page = Path("frontend/src/app/routes/page.tsx").read_text(encoding="utf-8")
    assert "localhost" not in page
    assert "http://127.0.0.1" not in page
    assert "/api/v1/routes/import-maps" in page
    assert "/tarjeta" in page
    helper = Path("frontend/src/app/lib/api.ts").read_text(encoding="utf-8")
    assert "localhost" in helper
    assert "NODE_ENV" in helper
