from fastapi.testclient import TestClient

from api import app
from app.deps import set_repository
from app.memory_repo import MemoryRouteRepository

client = TestClient(app)
USER = {"user_id": "00000000-0000-0000-0000-000000000001"}


def _repo() -> MemoryRouteRepository:
    repo = MemoryRouteRepository()
    set_repository(repo)
    return repo


def test_routes_require_database_when_not_configured():
    response = client.get("/api/v1/routes")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database not configured"


def test_import_maps_persists_visit_date_and_tarjeta_buttons():
    repo = _repo()
    maps = "https://www.google.com/maps/place/Rua+Sergipe,+Londrina/@-23.311,-51.162,17z"
    created = client.post(
        "/api/v1/routes/import-maps",
        json={"city_id": 3, "date": "2026-09-26", "visit_date": "2026-09-26", "text": maps},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["date"] == "2026-09-26"
    assert body["stops"][0]["visit_date"] == "2026-09-26"
    assert body["stops"][0]["tarjeta_status"] == "TT"
    assert body["stops"][0]["lat"] == -23.311
    assert body["stops"][0]["lng"] == -51.162
    assert repo.routes[body["id"]]["stops"][0]["address"]

    again = client.post(
        "/api/v1/routes/import-maps",
        json={
            "city_id": 3,
            "date": "2026-09-26",
            "text": "https://www.google.com/maps/search/?api=1&query=-23.32,-51.17",
        },
    )
    assert again.status_code == 201
    assert again.json()["id"] == body["id"]
    assert len(again.json()["stops"]) == 2
    assert again.json()["stops"][1]["distance_m"] is not None

    stop_id = body["stops"][0]["id"]
    marked = client.patch(
        f"/api/v1/routes/{body['id']}/stops/{stop_id}/tarjeta",
        json={"tarjeta_status": "VV", "visit_date": "2026-09-25", "tarjeta_by": "sana"},
    )
    assert marked.status_code == 200
    assert marked.json()["tarjeta_status"] == "VV"
    assert marked.json()["visit_date"] == "2026-09-25"
    assert marked.json()["tarjeta_at"]
    assert marked.json()["tarjeta_by"] == "sana"

    locked = client.patch(f"/api/v1/routes/{body['id']}", json={"status": "planned"})
    assert locked.status_code == 200
    assert locked.json()["status"] == "locked"
    assert locked.json()["stops"][0]["locked"] is True

    removed = client.delete(f"/api/v1/routes/{body['id']}/stops/{stop_id}")
    assert removed.status_code == 409

    listed = client.get("/api/v1/routes?city_id=3&date=2026-09-26&status=locked")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]


def test_invalid_tarjeta_and_empty_import():
    _repo()
    bad = client.patch(
        "/api/v1/routes/missing/stops/missing/tarjeta",
        json={"tarjeta_status": "ZZ"},
    )
    assert bad.status_code == 400
    empty = client.post("/api/v1/routes/import-maps", json={"city_id": 1, "text": "hola"})
    assert empty.status_code == 400


def test_legend_has_contract_codes():
    response = client.get("/api/v1/tarjeta-statuses")
    codes = {item["code"] for item in response.json()}
    assert codes == {"TT", "TS", "TC", "VV", "TF", "PT", "VS"}


def test_existing_api_prefix_still_registered():
    response = client.get("/api/cities")
    assert response.headers["content-type"].startswith("application/json")
    assert "text/html" not in response.headers["content-type"]
