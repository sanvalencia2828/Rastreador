import json
from pathlib import Path

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_root_is_503_when_frontend_missing():
    response = client.get("/")
    assert response.status_code == 503
    assert response.json()["detail"] == "frontend not built"


def test_spa_serves_index_and_history_fallback(monkeypatch, tmp_path: Path):
    (tmp_path / "index.html").write_text("<html><body>spa-shell</body></html>", encoding="utf-8")
    (tmp_path / "routes").mkdir()
    (tmp_path / "routes" / "index.html").write_text("<html><body>routes-page</body></html>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))

    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert "spa-shell" in root.text

    routes = client.get("/routes")
    assert routes.status_code == 200
    assert "routes-page" in routes.text

    unknown = client.get("/planner/today")
    assert unknown.status_code == 200
    assert "spa-shell" in unknown.text

    asset = client.get("/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text


def test_api_paths_are_not_rewritten_to_html():
    missing = client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")

    docs = client.get("/api/v1/docs")
    assert docs.status_code == 200
    body = docs.json()
    assert body["ok"] is True
    assert "endpoints" in body

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "/api/v1/routes" in spec.json()["paths"]


def test_path_traversal_does_not_escape_dist(monkeypatch, tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    response = client.get("/../secret.txt")
    assert "nope" not in response.text
    secret.unlink(missing_ok=True)
