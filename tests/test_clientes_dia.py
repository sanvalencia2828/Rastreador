"""POST /api/routes/clientes-dia con datos sintéticos (sin base): selección, tope, orden por ciudad y horas."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_jwt_token
from app.main import app
from app.routes import planned_routes as pr
from app.services.geo import haversine_km

client = TestClient(app)
UA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
H = {"Authorization": f"Bearer {create_jwt_token({'user_id': UA})}"}


def _row(n, city, lat, lon, diaria=False, atrasado=False, status="ok"):
    return SimpleNamespace(id=f"{n:08d}-0000-0000-0000-000000000000", nombre_negocio=f"N{n}", nombre_cliente="",
                           direccion="d", bairro="b", municipio=city, lat=lat, lon=lon, geocode_status=status,
                           visita_diaria=diaria, atrasado=atrasado)


def cid(n):
    return f"{n:08d}-0000-0000-0000-000000000000"


# Apucarana (-23.55, -51.46), Arapongas (-23.42, -51.42), Maringá (-23.42, -51.93): coordenadas sintéticas
APU = [_row(1, "Apucarana", -23.552, -51.461, diaria=True), _row(2, "APUCARANA", -23.560, -51.470, atrasado=True)]
ARA = [_row(3, "Arapongas", -23.419, -51.424, diaria=True), _row(4, "Arapongas", -23.405, -51.430)]  # 4: normal
MGA = [_row(5, "Maringa", -23.420, -51.933, atrasado=True), _row(6, "Maringá", -23.430, -51.940)]  # 6: normal
PEND = _row(7, "Maringá", None, None, diaria=True, status="pendiente")


@pytest.fixture
def rows(monkeypatch):
    data = []
    monkeypatch.setattr(pr, "db_engine", object())
    monkeypatch.setattr(pr, "_load_clientes", lambda uid: data)
    return data


def dia(**body):
    return client.post("/api/routes/clientes-dia", headers=H, json={"start_city": "Apucarana", "hora_salida": "09:30", **body})


def test_includes_daily_overdue_and_extras_only(rows):
    rows += [*APU, *ARA, *MGA, PEND]
    r = dia(extra_ids=[cid(4)])
    assert r.status_code == 200, r.text
    d = r.json()
    by_name = {s["nombre"]: s for s in d["stops"]}
    assert set(by_name) == {"N1", "N2", "N3", "N4", "N5"}  # N6 no es diario, atrasado ni extra
    assert by_name["N1"]["diario"] and not by_name["N1"]["atrasado"]
    assert by_name["N2"]["atrasado"] and by_name["N5"]["atrasado"] and not by_name["N4"]["diario"]
    assert [x["nombre"] for x in d["sin_ubicacion"]] == ["N7"]
    assert set(d["stops"][0]) == {"id", "nombre", "ciudad", "lat", "lon", "km_desde_anterior", "llegada", "diario", "atrasado"}


def test_order_is_by_city_from_start_and_not_mixed(rows):
    rows += [*MGA, *ARA, *APU]  # desordenados a propósito
    d = dia(extra_ids=[cid(4), cid(6)]).json()
    assert [s["ciudad"] for s in d["stops"]] == ["Apucarana"] * 2 + ["Arapongas"] * 2 + ["Maringá"] * 2
    assert [s["nombre"] for s in d["stops"]][:2] == ["N1", "N2"]  # N1 está en el centro, donde se sale
    # desde Maringá empieza por Maringá y cada ciudad sigue en un solo bloque
    d = client.post("/api/routes/clientes-dia", headers=H, json={"start_city": "maringa", "extra_ids": [cid(4), cid(6)]}).json()
    seq = [s["ciudad"] for s in d["stops"]]
    assert seq[:2] == ["Maringá"] * 2
    blocks = [c for i, c in enumerate(seq) if i == 0 or seq[i - 1] != c]
    assert len(blocks) == len(set(blocks)) == 3


def test_overdue_are_never_dropped_before_others(rows):
    rows += [*APU, *ARA, *MGA]
    d = dia(extra_ids=[cid(4), cid(6)], max_paradas=2).json()
    assert sorted(s["nombre"] for s in d["stops"]) == ["N2", "N5"]  # los dos atrasados, aunque Maringá queda lejos
    assert all(s["atrasado"] for s in d["stops"])
    dropped = [x["nombre"] for x in d["fuera_por_tope"]]
    assert sorted(dropped) == ["N1", "N3", "N4", "N6"]
    d = dia(extra_ids=[cid(4), cid(6)], max_paradas=4).json()
    assert sorted(x["nombre"] for x in d["fuera_por_tope"]) == ["N4", "N6"]  # primero caen los extras


def test_arrival_times_and_km(rows):
    rows += [APU[0], ARA[0]]
    d = client.post("/api/routes/clientes-dia", headers=H,
                    json={"start_lat": -23.552, "start_lon": -51.461, "hora_salida": "09:30"}).json()
    a, b = d["stops"]
    assert a["km_desde_anterior"] == 0 and a["llegada"] == "09:30"  # sale desde el mismo punto
    km = haversine_km(-23.552, -51.461, -23.419, -51.424)
    assert b["km_desde_anterior"] == round(km, 1)
    t = 9 * 60 + 30 + pr.VISITA_MIN + km / pr.VELOCIDAD_KMH * 60
    assert b["llegada"] == f"{round(t) // 60:02d}:{round(t) % 60:02d}"
    assert d["hora_fin"] == pr._hhmm(t + pr.VISITA_MIN) and d["maps_links"]


def test_unknown_extra_ids_are_counted_not_leaked(rows):
    rows += [APU[0]]
    d = dia(extra_ids=["99999999-0000-0000-0000-000000000000"]).json()
    assert d["extra_no_encontrados"] == 1 and [s["nombre"] for s in d["stops"]] == ["N1"]


def test_empty_day(rows):
    d = dia().json()
    assert d["stops"] == [] and d["hora_fin"] == "09:30" and d["maps_links"] == []


@pytest.mark.parametrize("body", [
    {"hora_salida": "09:30"},  # sin inicio
    {"start_lat": -23.5, "hora_salida": "09:30"},  # lat sin lon
    {"start_city": "Apucarana", "hora_salida": "9:30"},
    {"start_city": "Apucarana", "hora_salida": "24:00"},
    {"start_city": "Apucarana", "extra_ids": ["no-es-uuid"]},
    {"start_city": "Apucarana", "max_paradas": 0},
])
def test_validation_422(rows, body):
    assert client.post("/api/routes/clientes-dia", headers=H, json=body).status_code == 422


def test_unknown_start_city_422(rows):
    r = client.post("/api/routes/clientes-dia", headers=H, json={"start_city": "Londrina"})
    assert r.status_code == 422 and "Ciudad desconocida" in r.json()["detail"]


def test_requires_login(rows, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")  # en development el login se salta
    assert client.post("/api/routes/clientes-dia", json={"start_city": "Apucarana"}).status_code == 401
