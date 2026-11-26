"""Ruta de tarjetas sin base de datos: reglas de ciudades, tope de paradas, orden y privacidad de la respuesta.

Las reglas que viven en SQL (entregas, inactivos, coordenadas, clientes cercanos, 7 días, usuarios) se prueban
contra Postgres real en tests/test_tarjetas_pg.py.
"""

import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_jwt_token
from app.main import app
from app.routes import tarjetas as R
from app.services import tarjetas as T

client = TestClient(app)
UA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONTACT = re.compile(r"telefone|telefono|\bddd|correio|correo|\bemail|e_mail|complemento|\bfax\b", re.IGNORECASE)


def bearer(user_id=UA):
    return {"Authorization": f"Bearer {create_jwt_token({'user_id': user_id})}"}


def _row(i, municipio="Maringá", lat=-23.4205, lon=-51.9330):
    return {
        "id": i, "cnpj_completo": f"{i:014d}", "nome_fantasia": f"Loja {i}", "descricao_tipo_logradouro": "RUA",
        "logradouro": "DAS FLORES", "numero": str(i), "bairro": "ZONA 7", "municipio": municipio,
        "business_type": "food", "lat": lat, "lon": lon,
        # columnas de contacto que nunca deben salir aunque una consulta las trajera
        "telefone_1": "SECRET-TEL", "correio_eletronico": "SECRET-MAIL",
    }


class _Engine:
    @contextmanager
    def connect(self):
        yield object()


@pytest.fixture
def fake(monkeypatch):
    seen = {"candidatos": [], "guardadas": []}

    def candidatos(conn, user_id, nombres, inicio, limite, business_type=None, cnae=None):
        seen["candidatos"].append({"user_id": user_id, "nombres": nombres, "inicio": inicio, "limite": limite,
                                   "business_type": business_type, "cnae": cnae})
        rows = [_row(i, nombres[0], -23.4205 + 0.001 * (5 - i), -51.9330) for i in range(1, 6)]
        return rows[:limite]

    monkeypatch.setattr(R, "db_engine", _Engine())
    monkeypatch.setattr(T, "candidatos", candidatos)
    monkeypatch.setattr(T, "geocodificados", lambda conn, user_id, nombres: {n: (5, 5) for n in nombres})
    monkeypatch.setattr(R, "create_route", lambda body, user_id: seen["guardadas"].append((body, user_id)) or {"id": "r-1"})
    monkeypatch.delenv("OSRM_URL", raising=False)
    return seen


def test_cities_more_than_25_km_apart_cannot_share_a_route(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá", "Arapongas"], "juntar": True}, headers=bearer())
    assert res.status_code == 422
    assert "Arapongas" in res.json()["detail"] and "25 km" in res.json()["detail"]


def test_maringa_and_marialva_share_one_route(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá", "Marialva"], "juntar": True}, headers=bearer())
    assert res.status_code == 200
    rutas = res.json()["rutas"]
    assert len(rutas) == 1 and rutas[0]["ciudades"] == ["Maringá", "Marialva"]
    assert fake["candidatos"][0]["nombres"] == ["Maringá", "Marialva"]


def test_one_route_per_city_by_default(fake):
    res = client.post("/api/tarjetas/ruta", json={}, headers=bearer())
    assert res.status_code == 200
    assert [r["ciudades"] for r in res.json()["rutas"]] == [["Maringá"], ["Marialva"], ["Arapongas"]]


def test_unknown_city_is_422(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Lima"]}, headers=bearer())
    assert res.status_code == 422 and "Lima" in res.json()["detail"]


@pytest.mark.parametrize("n", [0, 81])
def test_max_paradas_is_bounded(fake, n):
    assert client.post("/api/tarjetas/ruta", json={"max_paradas": n}, headers=bearer()).status_code == 422


def test_max_paradas_filters_and_user_reach_the_query(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Marialva"], "max_paradas": 3, "business_type": "food",
                                                  "cnae": 4711302, "user_id": "otro"}, headers=bearer())
    assert res.status_code == 200
    (call,) = fake["candidatos"]
    assert call == {"user_id": UA, "nombres": ["Marialva"], "inicio": (-23.4855, -51.7927), "limite": 3,
                    "business_type": "food", "cnae": 4711302}
    assert res.json()["rutas"][0]["total"] == 3


def test_route_is_ordered_from_the_origin_and_saved_as_planned_route(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá"]}, headers=bearer())
    r = res.json()["rutas"][0]
    # filas a 0..4 km al norte del centro: se recorren de la más cercana a la más lejana
    assert [p["business_id"] for p in r["paradas"]] == [5, 4, 3, 2, 1]
    assert r["paradas"][0]["distancia_m"] == 0 and 100 < r["paradas"][1]["distancia_m"] < 120
    assert r["paradas"][0]["maps_url"] == "https://www.google.com/maps/dir/?api=1&destination=-23.4205,-51.933"
    assert r["route_id"] == "r-1" and r["fuente_orden"] == "linea_recta"
    body, user_id = fake["guardadas"][0]
    assert user_id == UA and body.business_ids == [5, 4, 3, 2, 1] and (body.start_lat, body.start_lng) == (-23.4205, -51.933)


def test_gps_is_the_origin_only_near_the_city(fake):
    client.post("/api/tarjetas/ruta", json={"cities": ["Maringá"], "lat": -23.40, "lon": -51.92}, headers=bearer())
    client.post("/api/tarjetas/ruta", json={"cities": ["Arapongas"], "lat": -23.40, "lon": -51.92}, headers=bearer())
    assert [c["inicio"] for c in fake["candidatos"]] == [(-23.40, -51.92), (-23.4194, -51.4244)]


def test_response_has_no_contact_data(fake):
    res = client.post("/api/tarjetas/ruta", json={"cities": ["Maringá"]}, headers=bearer())
    assert res.status_code == 200 and res.json()["rutas"][0]["paradas"]
    assert "SECRET-" not in res.text
    assert not CONTACT.search(res.text), CONTACT.search(res.text).group(0)


def test_city_without_geocoded_businesses_explains_what_is_missing(fake, monkeypatch):
    monkeypatch.setattr(T, "candidatos", lambda *a, **k: [])
    monkeypatch.setattr(T, "geocodificados", lambda conn, user_id, nombres: {})
    r = client.post("/api/tarjetas/ruta", json={"cities": ["Mandaguari"]}, headers=bearer()).json()["rutas"][0]
    assert r["paradas"] == [] and r["route_id"] is None
    assert "geocodificados" in r["aviso"] and "geocodificar" in r["aviso"]
    assert fake["guardadas"] == []


def test_entrega_rejects_bad_input():
    for body in ({"cnpj": "123", "resultado": "cerrado"},
                 {"cnpj": "1" * 14, "resultado": "otro"},
                 {"cnpj": "1" * 14, "resultado": "cerrado", "nota": "x" * 501},
                 {"cnpj": "1" * 14, "resultado": "cerrado", "lat": -23.4}):
        assert client.post("/api/tarjetas/entregas", json=body, headers=bearer()).status_code == 422


def test_new_endpoints_require_login(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    for method, path, body in [("POST", "/api/tarjetas/ruta", {}), ("GET", "/api/tarjetas/resumen", None),
                               ("POST", "/api/tarjetas/entregas", {"cnpj": "1" * 14, "resultado": "cerrado"}),
                               ("GET", f"/api/tarjetas/ruta/{UA}", None)]:
        assert client.request(method, path, json=body).status_code == 401


def test_rules_in_sql_match_the_spec():
    sql = " ".join(T.CANDIDATOS_SQL.text.split())
    assert "e.situacao_cadastral = 2" in sql and "e.geocoded IS TRUE" in sql
    assert "e.latitude IS NOT NULL AND e.longitude IS NOT NULL" in sql
    assert "t.resultado IN ('tarjeta_entregada', 'interesado', 'rechazo')" in sql
    assert "t.fecha > (NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 7" in sql
    assert "< 30" in sql and sql.count("CAST(:user_id AS uuid)") == 2
