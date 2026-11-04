"""Los endpoints públicos no devuelven teléfono, correo ni complemento del volcado del CNPJ."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.cache import clear_response_cache
from app.main import app
from app.routes import businesses, geo

client = TestClient(app)

CONTACT = re.compile(r"telefone|\bddd|correio|\bemail|e_mail|complemento|\bfax\b", re.IGNORECASE)

# Una fila del volcado con todos sus datos de contacto; los valores son marcas fáciles de detectar.
BIZ = {
    "cnpj_basico": 1, "cnpj_ordem": 1, "cnpj_dv": 1, "nome_fantasia": "Loja", "business_type": "tech",
    "cnae_fiscal": 6201501, "bairro": "Centro", "logradouro": "Rua A", "numero": "10", "municipio": "Londrina",
    "latitude": -23.31, "longitude": -51.16,
    "telefone_1": "SECRET-TEL-1", "ddd_1": "SECRET-DDD", "telefone_2": "SECRET-TEL-2",
    "correio_eletronico": "SECRET-MAIL", "email": "SECRET-EMAIL", "complemento": "SECRET-COMPL",
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    clear_response_cache()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(geo, "load_businesses", lambda: [BIZ])
    monkeypatch.setattr(businesses, "load_businesses", lambda: [BIZ])
    monkeypatch.setattr(businesses, "db_engine", None)  # /near cae al camino con load_businesses
    yield
    clear_response_cache()


@pytest.mark.parametrize(
    "path",
    ["/api/heatmap", "/api/businesses/tech", "/api/businesses/near?lat=-23.31&lon=-51.16&radius=500"],
)
def test_responses_built_from_the_dump_have_no_contact_data(path):
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.text
    assert "SECRET-" not in body
    assert not CONTACT.search(body), CONTACT.search(body).group(0)
    assert json.loads(body)  # y la respuesta no está vacía: el test sí recorrió datos


def test_no_route_or_schema_mentions_a_contact_column():
    """Un SELECT o un campo nuevo con teléfono/correo/complemento hace fallar este test."""
    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for folder in ("routes", "schemas")
        for path in (root / folder).glob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CONTACT.search(line)
    ]
    assert offenders == []
