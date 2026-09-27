from datetime import date

from app.maps_import import parse_maps_text, today_in_app_tz


def test_place_url_extracts_coords_and_address():
    text = (
        "visita\n"
        "https://www.google.com/maps/place/Rua+Sergipe,+Londrina/@-23.311,-51.162,17z\n"
    )
    stops = parse_maps_text(text)
    assert len(stops) == 1
    assert stops[0]["lat"] == -23.311
    assert stops[0]["lng"] == -51.162
    assert "Rua Sergipe" in stops[0]["address"]
    assert stops[0]["source"] == "google_maps"
    assert stops[0]["maps_url"].startswith("https://www.google.com/maps/place/")


def test_dir_url_splits_points_and_ignores_non_maps():
    text = (
        "https://www.google.com/maps/dir/-23.310,-51.160/-23.320,-51.170/\n"
        "https://example.com/not-maps\n"
    )
    stops = parse_maps_text(text)
    assert [stop["lat"] for stop in stops] == [-23.310, -23.320]
    assert [stop["lng"] for stop in stops] == [-51.160, -51.170]


def test_query_and_3d_forms():
    query = parse_maps_text("https://www.google.com/maps/search/?api=1&query=-23.55,-51.46")
    assert query[0]["lat"] == -23.55
    assert query[0]["lng"] == -51.46
    data = parse_maps_text("https://www.google.com/maps/place/Loja/data=!3d-23.2!4d-51.5")
    assert data[0]["lat"] == -23.2
    assert data[0]["lng"] == -51.5


def test_short_link_is_kept_without_fetch():
    stops = parse_maps_text("https://maps.app.goo.gl/abc123")
    assert len(stops) == 1
    assert stops[0]["lat"] is None
    assert stops[0]["maps_url"] == "https://maps.app.goo.gl/abc123"


def test_today_uses_app_timezone(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/Sao_Paulo")
    assert isinstance(today_in_app_tz(), date)
